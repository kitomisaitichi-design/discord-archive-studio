from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import subprocess
import socket
import threading
import time
from urllib.parse import urlparse, parse_qs
from .access import Inaccessible
from .discord import PermissionError, AuthError
from .exporting import options, DEFAULT_OPTIONS, media_limit, media_reason
from .importing import import_data
from .store import packed, valid_id
from .launching import library_identity


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name!='nt'
    def server_bind(self):
        if os.name=='nt':
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()

    def __init__(self, address, store, connection, worker):
        super().__init__(address, Handler)
        self.store, self.connection, self.worker = store, connection, worker
        self.session = secrets.token_urlsafe(32)
        self.cookie_name = 'studio_'+str(self.server_port)
        self.pair_code = None
        self.pair_expiry = 0
        self.web = Path(__file__).resolve().parent.parent / 'web'
        self.mutation_lock = threading.RLock()
        self.window_state = {}
        self.native_window_enabled = False

    def state(self):
        destination = self.worker.destination()
        channels = self.store.channels()
        inventories = {}
        for channel in channels:
            sid = channel['server_id']
            if sid not in inventories:
                inventories[sid] = self.store.setting('inventory:'+sid, {})
            inventory = inventories[sid]
            channel['accessible'] = bool(self.connection.account and inventory.get('owner') == self.connection.account['id'] and channel['id'] in inventory.get('ids', []))
        with self.store.db() as db:
            pubs = [dict(r) for r in db.execute('SELECT server_id,path,updated,size FROM publications')]
            presets = [dict(r, options=json.loads(r['options'])) for r in db.execute('SELECT * FROM presets ORDER BY name')]
        return {'version': self.store.version, 'connection': self.connection.status(), 'servers': self.store.servers(),
                'channels': channels, 'queue': self.store.jobs(), 'history': self.store.jobs(True),
                'stats': self.store.stats(), 'schedules': self.store.schedules(), 'publications': pubs,
                'destination': destination, 'cooldown_until': self.store.setting('cooldown_until', 0),
                'defaults': DEFAULT_OPTIONS, 'presets': presets, 'demo': self.store.setting('demo', False),
                'media_tasks': self.store.media_tasks(), 'auto_connect':self.store.setting('auto_connect',True),
                'worker_error': self.store.setting('worker_error', '')}


class Handler(BaseHTTPRequestHandler):
    server_version = 'DiscordArchiveStudio/1.0'
    def log_message(self, format, *args):
        # Request paths may carry private search text; avoid persisting them in server logs.
        pass

    def host_valid(self):
        port = self.server.server_port
        return self.headers.get('Host') in ('127.0.0.1:%s' % port, 'localhost:%s' % port)

    def authorized(self):
        cookies = dict(part.strip().split('=', 1) for part in self.headers.get('Cookie', '').split(';') if '=' in part)
        return self.host_valid() and hmac.compare_digest(cookies.get(self.server.cookie_name, ''), self.server.session)

    def extension_origin(self):
        origin = self.headers.get('Origin', '')
        return origin if re.fullmatch(r'chrome-extension://[a-p]{32}', origin) else None

    def send_headers(self, status=200, kind='application/json; charset=utf-8', extra=None, length=None):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://cdn.discordapp.com https://media.discordapp.net; media-src 'self' https://cdn.discordapp.com https://media.discordapp.net; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        if length is not None:
            self.send_header('Content-Length', str(length))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def json(self, data, status=200, extra=None):
        payload = packed(data).encode('utf-8')
        self.send_headers(status, extra=extra, length=len(payload))
        self.wfile.write(payload)

    def error(self, error, status=400, extra=None):
        self.json({'error': str(error)}, status, extra)

    def do_OPTIONS(self):
        origin = self.extension_origin()
        if not self.host_valid() or not origin or not self.path.startswith('/api/bridge/'):
            self.error('Origin is not allowed.', 403)
            return
        self.send_headers(204, extra={'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Methods': 'POST, OPTIONS',
                                'Access-Control-Allow-Headers': 'Content-Type, X-Bridge-Key', 'Access-Control-Max-Age': '600'}, length=0)

    def do_GET(self):
        try:
            if not self.host_valid():
                self.error('Invalid local host.', 403)
                return
            route = urlparse(self.path)
            query = {k: v[-1] for k, v in parse_qs(route.query).items()}
            if route.path == '/api/health':
                self.json({'app': 'Discord Archive Studio', 'version': '1.0.1','library_id':library_identity(self.server.store.root)})
                return
            if route.path in ('/', '/index.html'):
                payload = (self.server.web / 'index.html').read_bytes()
                self.send_headers(kind='text/html; charset=utf-8', extra={'Set-Cookie': self.server.cookie_name+'='+self.server.session+'; HttpOnly; SameSite=Strict; Path=/'}, length=len(payload))
                self.wfile.write(payload)
                return
            if not self.authorized():
                self.error('Open the local app to establish your session.', 403)
                return
            if route.path == '/api/state':
                self.json(self.server.state())
            elif route.path == '/api/search':
                result = self.server.store.search(query.get('q', ''), query.get('channel'), query.get('server'), query.get('person'), query.get('start'), query.get('end'), query.get('offset', 0), query.get('limit', 80))
                attachment_ids = {str(a.get('id')) for m in result['messages'] for a in m.get('attachments', [])}
                local = {}
                if attachment_ids:
                    with self.server.store.db() as db:
                        for m in result['messages']:
                            for a in m.get('attachments',[]):
                                aid = str(a.get('id'))
                                row = db.execute('SELECT * FROM media WHERE attachment_id=?',(aid,)).fetchone()
                                task = db.execute('SELECT status,detail FROM media_requests WHERE attachment_id=?',(aid,)).fetchone()
                                a['download_status'] = media_reason(a,media_limit(a,100),dict(row) if row else None) or (task['detail'] if task else 'Manual download only')
                                if row and not media_reason(a,media_limit(a,100),dict(row)):
                                    local[aid]='/media/'+row['hash']
                result['media'] = local
                self.json(result)
            elif route.path == '/api/users':
                self.json(self.server.store.users())
            elif route.path == '/api/message':
                mid = valid_id(query.get('id', ''))
                with self.server.store.db() as db:
                    row = db.execute('SELECT m.raw,c.name,c.server_id FROM messages m JOIN channels c ON c.id=m.channel_id WHERE m.id=?', (mid,)).fetchone()
                    revisions = [json.loads(r['raw']) for r in db.execute('SELECT raw FROM revisions WHERE message_id=? ORDER BY captured DESC', (mid,))]
                if not row:
                    raise ValueError('This referenced message has not been captured in the library.')
                self.json({'message':dict(json.loads(row['raw']),channel_name=row['name'],server_id=row['server_id']), 'revisions':revisions})
            elif route.path == '/api/events':
                self.events()
            elif re.fullmatch(r'/media/[a-f0-9]{64}', route.path):
                digest = route.path.rsplit('/', 1)[-1]
                path = self.server.store.root / 'media' / digest
                with self.server.store.db() as db:
                    row = db.execute('SELECT filename FROM media WHERE hash=? LIMIT 1', (digest,)).fetchone()
                if not row or not path.is_file():
                    self.error('Attachment has not been saved.', 404)
                    return
                kind = mimetypes.guess_type(row['filename'])[0] or 'application/octet-stream'
                active = kind in ('text/html', 'image/svg+xml', 'application/javascript')
                self.send_headers(kind='application/octet-stream' if active else kind,
                             extra={'Content-Disposition': 'attachment'} if active else None, length=path.stat().st_size)
                with path.open('rb') as source:
                    while block := source.read(256*1024):
                        self.wfile.write(block)
            elif route.path in ('/app.js', '/style.css'):
                path = self.server.web / route.path.lstrip('/')
                payload = path.read_bytes()
                self.send_headers(kind='text/javascript; charset=utf-8' if path.suffix=='.js' else 'text/css; charset=utf-8', length=len(payload))
                self.wfile.write(payload)
            else:
                self.error('Not found.', 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            self.error(error)

    def events(self):
        self.send_headers(kind='text/event-stream', extra={'X-Accel-Buffering': 'no'})
        version, last_connection = -1, None
        try:
            while True:
                current_connection = packed(self.server.connection.status())
                if version != self.server.store.version or current_connection != last_connection:
                    state = self.server.state()
                    version, last_connection = state['version'], current_connection
                    self.wfile.write(('data: '+packed(state)+'\n\n').encode('utf-8'))
                else:
                    self.wfile.write(b': keepalive\n\n')
                self.wfile.flush()
                with self.server.store.changed:
                    self.server.store.changed.wait(10)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_POST(self):
        extra = None
        try:
            if not self.host_valid():
                self.error('Invalid local host.', 403)
                return
            route = urlparse(self.path)
            bridge = route.path.startswith('/api/bridge/')
            if bridge:
                origin = self.extension_origin()
                if self.headers.get('Origin') and not origin:
                    self.error('Browser connector origin is invalid.', 403)
                    return
                extra = {'Access-Control-Allow-Origin': origin} if origin else None
            else:
                origin = self.headers.get('Origin')
                allowed = ['http://127.0.0.1:%s' % self.server.server_port, 'http://localhost:%s' % self.server.server_port]
                if not self.authorized() or self.headers.get('X-Studio-Action') != 'local' or (origin and origin not in allowed):
                    self.error('Local app authorization is required.', 403)
                    return
            size = int(self.headers.get('Content-Length', 0))
            if size < 0 or size > 128*1024*1024:
                raise ValueError('Request exceeds the 128 MB input limit.')
            content = self.rfile.read(size)
            if route.path == '/api/import':
                filename = parse_qs(route.query).get('name', ['import.json'])[-1]
                with self.server.mutation_lock:
                    result = import_data(self.server.store, content, Path(filename).name)
                self.json(result)
                return
            data = json.loads(content or b'{}')
            result = self.action(route.path, data, bridge)
            self.json(result or {'ok': True}, extra=extra)
        except AuthError as error:
            self.server.connection.expired(error.digest)
            self.error(error, 409, extra)
        except (Inaccessible, PermissionError) as error:
            if not bridge:
                sid = str(data.get('server', '0')) if 'data' in locals() else '0'
                self.server.worker.access.quarantine(sid, str(error))
            self.error(error, 409, extra)
        except Exception as error:
            self.error(error, 400, extra)

    def action(self, path, data, bridge=False):
        store, connection, worker = self.server.store, self.server.connection, self.server.worker
        if bridge:
            origin = self.extension_origin()
            declared = str(data.get('extension_id',''))
            if declared and not re.fullmatch('[a-p]{32}',declared):
                raise ValueError('Invalid browser connector ID.')
            if origin and declared and origin!='chrome-extension://'+declared:
                raise ValueError('Browser connector ID does not match its origin.')
            origin = origin or ('chrome-extension://'+declared if declared else None)
            if not origin:
                raise ValueError('Browser connector ID or origin is required.')
            if path == '/api/bridge/pair':
                code = str(data.get('code', ''))
                if not self.server.pair_code or time.time() > self.server.pair_expiry or not hmac.compare_digest(code, self.server.pair_code):
                    raise ValueError('Pairing code is invalid or expired. Generate another code in the app.')
                key = secrets.token_urlsafe(32)
                keys = store.setting('bridge_keys', {})
                keys[origin] = hashlib.sha256(key.encode()).hexdigest()
                store.set_setting('bridge_keys', keys)
                self.server.pair_code = None
                return {'key': key}
            expected = store.setting('bridge_keys', {}).get(origin, '')
            key = hashlib.sha256(self.headers.get('X-Bridge-Key', '').encode()).hexdigest()
            if not expected or not hmac.compare_digest(key, expected):
                raise ValueError('Browser connector is not paired.')
            if path == '/api/bridge/connect':
                account = connection.accept(data.get('token'), 'browser')
                worker.signal()
                return {'connected': True, 'account': account}
            raise ValueError('Unknown connector action.')
        if path == '/api/window-mode':
            if not self.server.native_window_enabled:
                return {'native': False}
            from .window import set_mode
            return set_mode(data.get('mode'),self.server.server_port,self.server.window_state)
        elif path == '/api/connect':
            thread = threading.Thread(target=lambda: connection.connect_desktop(manual=True), daemon=True)
            thread.start()
        elif path == '/api/disconnect':
            connection.disconnect()
            store.set_setting('bridge_keys', {})
        elif path == '/api/pair-code':
            self.server.pair_code = secrets.token_hex(6)
            self.server.pair_expiry = time.time()+600
            return {'code': self.server.pair_code, 'expires_in': 600}
        elif path == '/api/catalog':
            api = connection.api()
            sid = valid_id(data.get('server', '0'))
            inventory = worker.access.inventory(api, connection.account['id'], sid, bool(data.get('archived')))
            return {'channels': len(inventory)}
        elif path == '/api/servers':
            guilds = connection.api().guilds()
            store.catalog(guilds)
            return {'servers': len(guilds)}
        elif path == '/api/enqueue':
            if not connection.account or not connection.token:
                raise ValueError('Connect to Discord before creating a live export task.')
            chosen = data.get('channels')
            if not isinstance(chosen, list) or not chosen:
                raise ValueError('Select at least one channel.')
            opts = options(data.get('options'))
            ids = store.enqueue(chosen, connection.account['id'], opts)
            worker.signal()
            return {'tasks': len(ids)}
        elif path == '/api/media/select':
            result = store.enqueue_media(data.get('selections'),data.get('cap_mb',10))
            worker.signal()
            return result
        elif path == '/api/media/cancel':
            store.update_media(valid_id(data['id']),status='cancelled',detail='Cancelled manually; existing cached files retained.')
            worker.signal()
        elif path == '/api/control':
            if data['action'] == 'apply':
                store.configure_job(str(data['id']), options(data.get('options')))
            else:
                if data['action']=='resume' and connection.account and store.job(str(data['id']))['owner_id']!=connection.account['id']:
                    raise ValueError('This task belongs to another Discord account. Switch back to its original account first.')
                store.control(str(data['id']), str(data['action']))
            worker.signal()
        elif path == '/api/schedule':
            if not connection.account:
                raise ValueError('Connect before configuring a live schedule.')
            scope = str(data['scope'])
            opts = options(data.get('options'))
            enabled = bool(data.get('enabled'))
            store.schedule(scope, connection.account['id'], enabled, data.get('mode', 'fixed'), data.get('minutes', 1440), opts)
            if scope.startswith('server:'):
                # Update inherited children while retaining every explicit per-channel override.
                sid = scope.split(':', 1)[1]
                for entry in store.schedules():
                    if entry['scope'].startswith('channel:') and entry['options'].get('inherited') and any(c['id']==entry['scope'].split(':',1)[1] for c in store.channels(sid)):
                        store.schedule(entry['scope'], connection.account['id'], enabled, data.get('mode', 'fixed'), data.get('minutes', 1440), dict(opts, inherited=True))
            worker.signal()
        elif path == '/api/recommend':
            return store.interval(valid_id(data['channel']))
        elif path == '/api/settings':
            if 'destination' in data:
                destination = Path(str(data['destination'])).expanduser()
                if not destination.is_absolute():
                    raise ValueError('Destination must be an absolute folder path.')
                destination.mkdir(parents=True, exist_ok=True)
                store.set_setting('destination', str(destination))
            if 'auto_connect' in data:
                store.set_setting('auto_connect', bool(data['auto_connect']))
        elif path == '/api/alias':
            store.alias(data['user_id'], data.get('person_id'))
        elif path == '/api/preset':
            name = str(data.get('name', '')).strip()[:80]
            if not name:
                raise ValueError('Preset name is required.')
            with store.db() as db:
                if data.get('remove'):
                    db.execute('DELETE FROM presets WHERE name=?', (name,))
                else:
                    db.execute('INSERT OR REPLACE INTO presets VALUES(?,?)', (name, packed(options(data.get('options')))))
        elif path == '/api/publish':
            sid = valid_id(data['server'])
            with self.server.mutation_lock:
                if any(j['status']=='running' for j in store.jobs()):
                    raise ValueError('A batch is running; wait for its checkpoint before rebuilding the ZIP.')
                return worker.exporter.publish(sid, options(data.get('options')), worker.destination(), selected_channels=data.get('channels'))
        elif path == '/api/folder':
            if os.name != 'nt':
                raise ValueError('Folder picker requires Windows.')
            script = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); Add-Type -AssemblyName System.Windows.Forms; $picker = New-Object System.Windows.Forms.FolderBrowserDialog; $picker.Description = 'Choose Discord archive destination'; if ($picker.ShowDialog() -eq 'OK') { [Console]::Write($picker.SelectedPath) }"
            result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-Command', script], capture_output=True, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW, timeout=180)
            if result.returncode:
                raise RuntimeError('Folder picker failed: '+result.stderr.strip())
            return {'path': result.stdout.strip()}
        elif path == '/api/open-folder':
            path = Path(worker.destination())
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        elif path == '/api/shutdown':
            with store.db() as db:
                db.execute("UPDATE jobs SET status='paused',detail='Paused on app shutdown.' WHERE status IN ('running','waiting')")
            worker.stop.set()
            worker.signal()
            connection.stop.set()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            raise ValueError('Unknown local action.')
