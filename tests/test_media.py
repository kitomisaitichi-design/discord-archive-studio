import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile
from test_studio import Base, message, SID, CID, UID, FakeAPI, FakeConnection
from studio.discord import download, MediaTooLarge
from studio.exporting import Exporter, options
from studio.importing import import_data
from studio.runtime import Worker
from studio.access import Access


def attached(mid='9001', aid='9901', size=3, name='image.png'):
    m=message(mid)
    m['attachments']=[{'id':aid,'filename':name,'size':size,'url':'https://cdn.discordapp.com/attachments/1/2/'+name}]
    return m


class ManualMediaTests(Base):
    def select(self,m,cap=10):
        self.store.upsert(CID,[m])
        return self.store.enqueue_media([{'message_id':m['id'],'attachment_id':m['attachments'][0]['id']}],cap)

    def test_text_export_never_downloads_attachments_even_with_saved_files_option(self):
        api=FakeAPI([attached()]);worker=Worker(self.store,FakeConnection(api))
        self.store.set_setting('destination',str(self.root/'Exports'))
        jid=self.store.enqueue([CID],UID,options({'download_media':True}))[0]
        self.store.update_job(jid,status='running')
        with patch('studio.exporting.download') as fetch:
            worker.process(self.store.job(jid))
            fetch.assert_not_called()
        self.assertEqual(self.store.job(jid)['status'],'completed')
        self.assertEqual(self.store.media_tasks(),[])

    def test_manual_queue_waits_for_text_and_duplicate_selection_coalesces(self):
        m=attached();self.select(m);self.select(m)
        self.store.enqueue([CID],UID,self.opts)
        worker=Worker(self.store,FakeConnection(FakeAPI()))
        with patch('studio.exporting.download') as fetch:
            worker.process_media();fetch.assert_not_called()
        self.assertEqual(len(self.store.media_tasks()),1)
        self.assertEqual(self.store.media_tasks()[0]['status'],'queued')

    def test_video_limit_and_pending_budget_are_enforced_before_network(self):
        self.assertEqual(self.select(attached(size=10000001,name='movie.MP4'),100)['skipped'],1)
        for n in range(10):
            self.select(attached(str(9100+n),str(9910+n),size=0))
        with self.assertRaises(ValueError):self.select(attached('9200','9999',size=0))
        self.assertEqual(sum(r['max_bytes'] for r in self.store.media_tasks() if r['status']=='queued'),100000000)

    def test_unknown_oversized_file_is_skipped_without_retry_and_partial_removed(self):
        self.select(attached(size=0,name='movie.webm'))
        worker=Worker(self.store,FakeConnection(FakeAPI()));self.store.set_setting('destination',str(self.root/'Exports'))
        def too_large(url,target,maximum,control,progress):
            target.write_bytes(b'partial');raise MediaTooLarge('Skipped: exceeds 10 MB cap.')
        with patch('studio.exporting.download',side_effect=too_large) as fetch:
            worker.process_media();worker.process_media();self.assertEqual(fetch.call_count,1)
        self.assertEqual(self.store.media_tasks()[0]['status'],'skipped')
        self.assertEqual(list(self.store.root.glob('*.partial')),[])
        self.assertEqual(self.store.stats()['messages'],1)

    def test_manual_download_hash_dedup_zip_roundtrip_and_channel_views(self):
        self.select(attached())
        opts=options({'formats':['json','html']})
        exporter=Exporter(self.store);self.store.set_setting('destination',str(self.root/'Exports'))
        path=exporter.publish(SID,opts,self.root/'Exports',channel_id=CID)['path']
        other='800000000000000099';self.store.catalog([], [{'id':other,'name':'development','type':0}],SID)
        m=message('9002');m['channel_id']=other;self.store.upsert(other,[m])
        exporter.publish(SID,options({'formats':['md']}),self.root/'Exports',channel_id=other)
        def small(url,target,maximum,control,progress):target.write_bytes(b'abc');return 3
        worker=Worker(self.store,FakeConnection(FakeAPI()))
        with patch('studio.exporting.download',side_effect=small) as fetch:
            worker.process_media()
            self.assertEqual(fetch.call_count,1)
        self.assertEqual(self.store.media_tasks()[0]['status'],'completed')
        with zipfile.ZipFile(path) as archive:
            self.assertIn('channels/'+CID+'/00001.json',archive.namelist())
            self.assertIn('channels/'+other+'/00001.md',archive.namelist())
            self.assertNotIn('channels/'+CID+'/00001.md',archive.namelist())
            self.assertEqual(archive.read('media/'+hashlib.sha256(b'abc').hexdigest()),b'abc')
        with tempfile.TemporaryDirectory() as temp:
            from studio.store import Store
            restored=Store(temp);import_data(restored,Path(path).read_bytes(),'archive.zip')
            self.assertEqual(restored.stats()['attachments'],1)

    def test_cached_oversized_video_is_excluded_without_deleting_original(self):
        m=attached(size=10000001,name='movie.mp4');self.store.upsert(CID,[m])
        digest=hashlib.sha256(b'abc').hexdigest();saved=self.store.root/'media'/digest;saved.write_bytes(b'abc')
        with self.store.db() as db:db.execute('INSERT INTO media VALUES(?,?,?,?,?)',('9901',digest,'movie.mp4',10000001,'media/'+digest))
        path=Exporter(self.store).publish(SID,options(None),self.root/'Exports')['path']
        with zipfile.ZipFile(path) as archive:
            self.assertFalse(any(n.startswith('media/') for n in archive.namelist()))
            a=json.loads(archive.read('channels/'+CID+'/00001.json'))['messages'][0]['attachments'][0]
            self.assertIn('Skipped',a['download_status']);self.assertNotIn('local_path',a)
        self.assertTrue(saved.exists())

    def test_restart_pauses_manual_selection_and_cancel_preserves_text(self):
        self.select(attached())
        from studio.store import Store
        restarted=Store(self.store.root)
        self.assertEqual(restarted.media_tasks()[0]['status'],'paused')
        restarted.update_media('9901',status='cancelled')
        self.assertEqual(restarted.stats()['messages'],1)


class DownloadBoundsTests(unittest.TestCase):
    def test_content_length_and_streamed_size_stop_at_cap(self):
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        for declared in ('11',None):
            response=Response(b'a'*100);response.headers={'Content-Length':declared} if declared else {}
            with tempfile.TemporaryDirectory() as temp, patch('studio.discord.build_opener') as opener:
                opener.return_value.open.return_value=response
                target=Path(temp)/'file'
                with self.assertRaises(MediaTooLarge):download('https://cdn.discordapp.com/a',target,10,lambda:True)
                self.assertLessEqual(target.stat().st_size if target.exists() else 0,10)


class ThreadRoutesTests(Base):
    def test_normal_preflight_skips_thread_search_and_thread_uses_current_parent(self):
        tid='800000000000000088'
        class ThreadAPI(FakeAPI):
            def get(self,route,**params):
                if route.endswith('/threads/search'):
                    self.calls.append(route)
                    return {'threads':[{'id':tid,'name':'thread','type':11,'parent_id':CID}],'has_more':False}
                result=super().get(route,**params)
                if route.endswith('/channels'):
                    result[0]['last_message_id']='9001'
                return result
        api=ThreadAPI();Access(self.store).inventory(api,UID,SID,required_channel=CID)
        self.assertFalse(any('threads' in r for r in api.calls))
        self.store.catalog([], [{'id':tid,'name':'thread','type':11,'parent_id':CID}],SID)
        api.calls.clear();allowed=Access(self.store).inventory(api,UID,SID,required_channel=tid)
        self.assertIn(tid,allowed)
        self.assertIn('channels/'+CID+'/threads/search',api.calls)
        self.assertFalse(any('/threads/active' in r or 'channels/'+tid+'/' in r for r in api.calls))
