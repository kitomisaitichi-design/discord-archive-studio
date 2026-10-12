from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from studio.launching import LibraryLock,bind_server,save_address,running_port,preferred_port
from studio.store import Store
from studio.runtime import Connection,Worker
from studio.server import Server
from studio.pacing import varied_delay
from studio.exporting import options,Exporter


class LaunchTests(unittest.TestCase):
    def test_preferred_port_preserves_browser_origin_and_ignores_other_library(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);save_address(root,8767)
            self.assertEqual(preferred_port(root),8767)
            info=root/'service.json';info.write_text(info.read_text().replace('"port": 8767','"port": 70000'))
            self.assertEqual(preferred_port(root),8765)
            save_address(root,8767)
            self.assertEqual(preferred_port(root/'other'),8765)

    def test_studio_instances_cannot_share_one_port(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp));connection=Connection(store);worker=Worker(store,connection)
            first=Server(('127.0.0.1',0),store,connection,worker)
            try:
                second=bind_server(lambda address:Server(address,store,connection,worker),preferred=first.server_port)
                try:self.assertNotEqual(second.server_port,first.server_port)
                finally:second.server_close()
            finally:first.server_close()

    def test_occupied_local_port_chooses_free_port_without_touching_occupant(self):
        with socket.socket() as occupied:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                occupied.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            occupied.bind(('127.0.0.1',0));occupied.listen()
            port=occupied.getsockname()[1]
            server=bind_server(lambda address:ThreadingHTTPServer(address,BaseHTTPRequestHandler),preferred=port)
            try:
                self.assertNotEqual(server.server_port,port)
                self.assertEqual(occupied.getsockname()[1],port)
            finally:server.server_close()

    def test_fixed_occupied_port_surfaces_error(self):
        with socket.socket() as occupied:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                occupied.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            occupied.bind(('127.0.0.1',0));occupied.listen()
            with self.assertRaises(OSError):bind_server(lambda address:ThreadingHTTPServer(address,BaseHTTPRequestHandler),occupied.getsockname()[1])

    def test_one_backend_per_library_and_relaunch_finds_saved_port(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with LibraryLock(root) as first:
                self.assertTrue(first.acquired)
                with LibraryLock(root) as second:self.assertFalse(second.acquired)
                store=Store(root);connection=Connection(store)
                server=Server(('127.0.0.1',0),store,connection,Worker(store,connection))
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    save_address(root,server.server_port)
                    self.assertEqual(running_port(root,0),server.server_port)
                    self.assertIn(str(server.server_port),(root/'OPEN-ARCHIVE-UI.url').read_text())
                    with self.assertRaises(RuntimeError):running_port(root/'unrelated',0)
                finally:server.shutdown();server.server_close();thread.join(2)
            with LibraryLock(root) as reopened:self.assertTrue(reopened.acquired)

    def test_all_four_format_cards_and_timing_controls_are_present(self):
        from html.parser import HTMLParser
        class Inputs(HTMLParser):
            def __init__(self):super().__init__();self.formats=[];self.ids=[]
            def handle_starttag(self,tag,attrs):
                a=dict(attrs)
                if tag=='input' and a.get('name')=='format':self.formats.append(a.get('value'))
                if a.get('id'):self.ids.append(a['id'])
        parser=Inputs();parser.feed((Path(__file__).parents[1]/'web/index.html').read_text(encoding='utf-8'))
        self.assertEqual(parser.formats,['json','html','md','txt'])
        self.assertIn('timing-variation',parser.ids);self.assertIn('app-address',parser.ids)


class PacingTests(unittest.TestCase):
    def test_stochastic_waits_never_shorten_baseline_and_fixed_mode_is_exact(self):
        samples=[varied_delay(300,25) for _ in range(200)]
        self.assertTrue(all(300<=s<=375 for s in samples))
        self.assertGreater(len(set(samples)),190)
        self.assertEqual(varied_delay(300,0),300)

    def test_server_reset_remains_minimum_despite_random_page_delay(self):
        from studio.discord import Discord
        from test_network import Response
        response=Response(b'{}');response.headers={'X-RateLimit-Remaining':'0','X-RateLimit-Reset-After':'9'}
        client=Discord('not-a-live-token');client.wait=lambda _:None
        with patch('studio.discord.build_opener') as opener,patch('studio.discord.time.monotonic',return_value=100),patch('studio.discord.varied_delay',return_value=3):
            opener.return_value.open.return_value=response
            client.get('users/@me');self.assertEqual(client.next_request,110)

    def test_format_rendering_uses_local_cache_without_a_discord_read(self):
        from test_studio import SID,CID,message
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'Data');store.catalog([{'id':SID,'name':'Local'}],[{'id':CID,'name':'general'}],SID)
            store.upsert(CID,[message('9001')])
            with patch('studio.discord.Discord.get',side_effect=AssertionError('Local formats must not fetch Discord')):
                result=Exporter(store).publish(SID,options({'formats':['json','html','md','txt']}),root/'Exports')
            self.assertTrue(Path(result['path']).is_file())
