import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zipfile
from test_studio import Base, CID, SID, UID, message, FakeConnection, FakeAPI
from studio.store import Store
from studio.searching import expand, suggestions
from studio.linked_images import public_target, download_image
from studio.reader_library import library_id
from studio.zipreader import ZipReader
from studio.exporting import Exporter, options
from studio.runtime import Worker
from studio.attention import inventory, retry

PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082')
URL = 'https://images.example.com/one.png'


class WorkflowTests(Base):
    def setUp(self):
        super().setUp()
        self.reader = ZipReader(self.store, app_root=self.root)
        rows = []
        for i in range(12):
            m = message(9000+i, 'needle '+URL)
            m['timestamp'] = '2026-04-11T00:00:%02dZ' % i
            rows.append(m)
        self.store.upsert(CID, rows)
        self.key = library_id(SID)

    def mark(self, mid, archive=''):
        return self.store.reading.mark([dict(message=str(mid), channel=CID, archive=archive)], self.reader)

    def select(self, url=URL, mid='9001'):
        return self.store.images.select([dict(message=mid, channel=CID, url=url)], self.reader)

    def test_watermark_is_monotone_durable_and_ignores_old_backfill(self):
        self.assertEqual(self.store.reading.summary()['total'], 12)
        self.mark(9007, self.key)
        self.mark(9002)
        self.assertEqual(self.store.reading.summary(CID)['channels'][0]['first'], '9008')
        old = message(8500); old['timestamp'] = '2020-01-01T00:00:00Z'
        self.store.upsert(CID, [old])
        reopened = Store(self.store.root)
        self.assertEqual(reopened.reading.summary()['total'], 4)
        with self.assertRaises(ValueError): self.mark(9999)

    def test_unread_snapshot_survives_marks_and_paging(self):
        self.mark(9007)
        snapshot = self.store.reading.snapshot()
        page = self.store.search(unread=snapshot, limit=2)
        self.mark(9011)
        older = self.store.search(unread=snapshot, cursor=page['messages'][-1]['_cursor'])
        self.assertEqual(page['total'], 4)
        self.assertEqual([m['id'] for m in older['messages']], ['9009','9008'])
        self.assertEqual(self.store.reading.summary()['total'], 0)
        with self.assertRaises(ValueError): self.store.search(unread='expired')

    def test_operators_preserve_quotes_urls_and_validate_dates(self):
        value = expand({'q':'"hello from:Alice" https://example.com/x from:"Alice Doe" in:general has:image after:2026-01-01'})
        self.assertEqual(value['q'], '"hello from:Alice" https://example.com/x')
        self.assertEqual(value['person'], 'Alice Doe')
        for query in ('before:2026-99-99','after:20260101','has:unknown','from:a from:b'):
            with self.assertRaises(ValueError): expand({'q':query})

    def test_search_operators_work_in_library_native_reader_and_zip(self):
        query='needle from:Alice in:general server:"Test server" has:image after:2026-01-01'
        self.assertEqual(self.store.search(query)['total'], 12)
        native=self.reader.query(self.key,'messages',{'channel':CID,'q':query,'day':'2027-01-01'})
        self.assertEqual(native['total'],12)
        self.assertEqual(self.store.search('in:missing')['total'],0)
        self.assertEqual(self.store.search('from:"x\" OR 1=1"')['total'],0)
        exported=Exporter(self.store).publish(SID,options({'formats':['json']}),self.root/'Exports')
        archive=self.reader.upload(__import__('pathlib').Path(exported['path']).read_bytes(),'fixture.zip')
        result=self.reader.query(archive['id'],'messages',{'channel':CID,'q':'from:Alice in:general has:image','day':'2027-01-01'})
        self.assertEqual(result['total'],12)

    def test_autocomplete_uses_saved_names_and_ids_only(self):
        self.assertEqual(suggestions(self.store,self.reader,{'operator':'from','value':'Alice'})['suggestions'][0]['value'],UID)
        self.assertEqual(suggestions(self.store,self.reader,{'operator':'in','value':'gen'})['suggestions'][0]['value'],CID)
        self.assertEqual(suggestions(self.store,self.reader,{'operator':'from','value':'unknown'})['suggestions'],[])

    def test_manual_links_validate_reference_and_coalesce(self):
        with patch('studio.linked_images.download_image') as download:
            self.select(); self.select()
            download.assert_not_called()
        self.assertEqual(len(self.store.images.tasks()),1)
        with self.assertRaises(ValueError): self.select('https://unreferenced.example.com/no.png')
        with self.assertRaises(ValueError): self.select(mid='99999')

    def test_same_bytes_share_cache_and_zip_reader_can_read_offline(self):
        second = 'https://images.example.com/two.gif'
        m=message(9500, second); m['timestamp']='2026-04-12T00:00:00Z';self.store.upsert(CID,[m])
        self.select(); self.select(second, '9500')
        def fetch(url,path,maximum,control): path.write_bytes(PNG); return len(PNG)
        with patch('studio.linked_images.download_image',side_effect=fetch) as download:
            for task in self.store.images.tasks():
                self.store.images.fetch(task,lambda:True)
                self.store.images.update(task['url_key'],'completed','Saved')
            self.assertEqual(download.call_count,2)
        self.assertEqual(len(list((self.store.root/'media').iterdir())),1)
        exported=Exporter(self.store).publish(SID,options({'formats':['json','html']}),self.root/'Exports')
        with zipfile.ZipFile(exported['path']) as archive:
            self.assertEqual(len([n for n in archive.namelist() if n.startswith('media/')]),1)
            self.assertIn('Saved linked image',archive.read('channels/'+CID+'/00001.html').decode())
        item=self.reader.upload(__import__('pathlib').Path(exported['path']).read_bytes(),'fixture.zip')
        result=self.reader.query(item['id'],'messages',{'channel':CID})
        self.assertTrue(result['messages'][0]['_linked_images'])
        asset=next(iter(result['messages'][0]['_linked_images'].values()))
        self.assertEqual(self.reader.asset(item['id'],asset)[1],PNG)
        with patch('studio.linked_images.download_image') as download:
            self.select()
            task=next(t for t in self.store.images.tasks() if t['url']==URL)
            self.store.images.fetch(task,lambda:True)
            download.assert_not_called()

    def test_private_targets_and_redirects_are_rejected_before_request(self):
        private=[(2,1,6,'',('127.0.0.1',80))]
        with patch('socket.getaddrinfo',return_value=private):
            with self.assertRaises(ValueError): public_target('http://example.com/one.png')
        public=[(2,1,6,'',('93.184.216.34',443))]
        response=SimpleNamespace(status=302,getheader=lambda name,default=None:'http://127.0.0.1/private.png' if name=='Location' else default)
        connection=SimpleNamespace(request=lambda *a,**k:None,getresponse=lambda:response,close=lambda:None)
        with patch('socket.getaddrinfo',side_effect=[public,private]),patch('http.client.HTTPSConnection',return_value=connection),patch('http.client.HTTPConnection') as private_connection:
            with self.assertRaises(ValueError): download_image(URL,self.root/'test.png',1000000,lambda:True)
            private_connection.assert_not_called()

    def test_worker_yields_to_text_and_image_selection_is_globally_capped(self):
        self.select()
        worker=Worker(self.store,FakeConnection(FakeAPI()))
        with patch.object(worker,'text_pending',return_value=True),patch.object(self.store.images,'fetch') as fetch:
            worker.process_images(); fetch.assert_not_called()
        with self.store.db() as db:
            db.execute("UPDATE linked_images SET status='failed'")
            for i in range(50):
                db.execute("INSERT INTO media_requests VALUES(?,?,?,?,?,0,'',0)",(str(500+i),'9001',CID,'queued',1000000))
        with self.assertRaises(ValueError): self.select()

    def test_attention_review_does_not_probe_and_blocked_retry_is_forbidden(self):
        worker=Worker(self.store,FakeConnection(FakeAPI()))
        server=SimpleNamespace(store=self.store,worker=worker,reader=self.reader,connection=worker.connection)
        jid=self.store.enqueue([CID],UID,self.opts)[0]
        self.store.update_job(jid,status='blocked',detail='Absent from accessible inventory.')
        updater=SimpleNamespace(status=lambda:{'status':'error','error':'Update rolled back'})
        with patch.object(worker.connection,'api',side_effect=AssertionError('Network probe')):
            result=inventory(self.store,updater)
            self.assertEqual({r['kind'] for r in result['items']},{'export','update'})
            with self.assertRaises(ValueError): retry(server,{'kind':'export','id':jid})
        self.assertEqual(self.store.job(jid)['status'],'blocked')

    def test_attention_detects_missing_cached_image_and_explicit_retry(self):
        self.select()
        task=self.store.images.tasks()[0]
        self.store.images.update(task['url_key'],'completed','Saved',hash='a'*64,received=100)
        result=inventory(self.store,SimpleNamespace(status=lambda:{}))
        self.assertEqual(result['items'][0]['status'],'missing')
        worker=Worker(self.store,FakeConnection(FakeAPI()))
        server=SimpleNamespace(store=self.store,worker=worker,reader=self.reader,connection=worker.connection)
        retry(server,{'kind':'image','id':task['url_key']})
        self.assertEqual(self.store.images.tasks()[0]['status'],'queued')


if __name__=='__main__': unittest.main()
