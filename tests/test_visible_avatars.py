import io
import json
import time
import zipfile
from unittest.mock import patch
from test_studio import Base, SID, CID, UID, message
from studio.exporting import Exporter, options
from studio.zipreader import ZipReader
from studio.reader_library import library_id
from studio.runtime import Worker


class VisibleAvatarTests(Base):
    def setUp(self):
        super().setUp()
        self.exporter=Exporter(self.store)
        self.reader=ZipReader(self.store,scan_parent=False)

    def captured(self,mid=9001,uid=UID,version='a'):
        m=message(mid,author=uid);m['author']['avatar']=version*32
        return m

    def test_visible_saved_sources_dedup_and_failed_retry_suppression(self):
        self.store.upsert(CID,[self.captured(),self.captured(9002)])
        authors=self.reader.saved_authors(library_id(SID),CID,['9001','9002','9999'])
        self.assertEqual(set(authors),{'9001','9002'})
        self.assertEqual(self.reader.saved_authors(library_id(SID),'999',['9001']),{})
        a=self.exporter.avatars
        self.assertEqual(a.visible(authors)['queued'],1)
        self.assertEqual(a.visible(authors)['queued'],0)
        a.update(a.tasks()[0]['key'],'failed','Not available')
        self.assertEqual(a.visible(authors)['pictures']['9001']['status'],'failed')
        self.assertEqual(a.visible(authors)['queued'],0)

    def test_zip_without_canonical_import_uses_captured_versions(self):
        m=self.captured()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:z.writestr('chat.json',json.dumps({'channel':{'id':CID,'name':'chat'},'messages':[m]}))
        entry=self.reader.upload(stream.getvalue(),'chat.zip')
        with patch('studio.discord.Discord.get',side_effect=AssertionError('No member or history lookup')):
            authors=self.reader.saved_authors(entry['id'],CID,['9001'])
            self.assertEqual(self.exporter.avatars.visible(authors)['queued'],1)
        self.assertEqual(self.store.stats()['messages'],0)

    def test_visible_cap_and_cached_response_without_generation_change(self):
        authors={str(i):self.captured(i,str(8000+i))['author'] for i in range(60)}
        a=self.exporter.avatars
        self.assertEqual(a.visible(authors)['queued'],50)
        self.assertEqual(sum(v['status']=='deferred' for v in a.visible(authors)['pictures'].values()),10)
        m=self.captured(9001,'8000');self.store.upsert(CID,[m])
        before=self.reader.query(library_id(SID),'overview',{})['generation']
        def save(url,path,*args):path.write_bytes(b'GIF89apicture');return 13
        task=next(t for t in a.tasks() if t['key'].startswith('8000:'))
        with patch('studio.avatars.download',side_effect=save):a.fetch(task,lambda:True)
        self.assertEqual(a.visible({'9001':m['author']})['pictures']['9001']['status'],'cached')
        self.assertEqual(before,self.reader.query(library_id(SID),'overview',{})['generation'])

    def test_worker_uses_rest_but_yields_to_running_or_ready_text(self):
        m=self.captured();self.store.upsert(CID,[m])
        connection=type('Offline',(),{'account':None,'token':None})()
        worker=Worker(self.store,connection);a=worker.exporter.avatars;a.visible({'9001':m['author']})
        job=self.store.enqueue([CID],UID,options(None))[0]
        self.assertFalse(worker.avatar_window())
        self.store.set_setting('cooldown_until',time.time()+60)
        self.assertTrue(worker.avatar_window())
        with patch.object(a,'fetch',return_value=13) as fetch:worker.process_avatar();self.assertEqual(fetch.call_count,1)
        self.store.update_job(job,status='running')
        self.assertFalse(worker.avatar_window())
        self.store.update_job(job,status='waiting');self.store.set_setting('cooldown_until',0)
        self.assertFalse(worker.avatar_window())

    def test_cached_picture_invalidates_only_local_zip_presentation(self):
        m=self.captured();self.store.upsert(CID,[m])
        first=self.exporter.publish(SID,options({'include_avatars':True}),self.root/'Exports')
        a=self.exporter.avatars
        def save(url,path,*args):path.write_bytes(b'GIF89apicture');return 13
        with patch('studio.avatars.download',side_effect=save):a.fetch(a.tasks()[0],lambda:True)
        second=self.exporter.publish(SID,options(None),self.root/'Exports',selected_channels=[])
        self.assertFalse(second['unchanged']);self.assertEqual(first['path'],second['path'])
        with zipfile.ZipFile(second['path']) as z:self.assertTrue(any(n.startswith('avatars/') for n in z.namelist()))
