import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from studio.store import Store
from studio.exporting import Exporter, options
from studio.zipreader import ZipReader
from studio.avatars import Avatars, avatar_key
from studio.runtime import Worker
from test_studio import SID, CID, UID, message


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.store = Store(self.root/'Data')
        self.store.catalog([{'id':SID,'name':'Fixture'}],[{'id':CID,'name':'general','type':0}],SID)
        self.exporter = Exporter(self.store); self.reader = ZipReader(self.store)
    def tearDown(self): self.temp.cleanup()
    def publish(self, opts=None):
        result = self.exporter.publish(SID,options(opts),self.root/'Exports')
        return result,self.reader.catalogue()[0]['id']
    def test_native_reader_retained_for_text_only_and_no_canonical_reimport(self):
        self.store.upsert(CID,[message(9001,'unique searchable phrase')]); result,key=self.publish({'formats':['txt']})
        with zipfile.ZipFile(result['path']) as z:
            self.assertIn('reader/'+CID+'/00001.json',z.namelist())
            self.assertNotIn('channels/'+CID+'/00001.json',z.namelist())
        with patch('studio.discord.Discord.get',side_effect=AssertionError('Reader must stay local')):
            overview=self.reader.query(key,'overview',{})
            page=self.reader.query(key,'messages',{'channel':CID,'q':'searchable'})
        self.assertEqual(overview['channels'][0]['messages'],1);self.assertEqual(len(page['messages']),1)
        self.assertEqual(self.store.stats()['messages'],1)
    def test_paged_date_hour_search_and_bidirectional_boundaries(self):
        rows=[]
        for i in range(350):
            m=message(10000+i,'needle' if i%2==0 else 'hay');m['timestamp']='2026-04-11T%02d:%02d:00+00:00'%(i//60,i%60);rows.append(m)
        self.store.upsert(CID,rows);_,key=self.publish({'split_count':100,'formats':['json','html','md','txt']})
        self.assertEqual(self.reader.query(key,'overview',{})['channels'][0]['messages'],350)
        cal=self.reader.query(key,'calendar',{'channel':CID,'month':'2026-04','day':'2026-04-11'})
        self.assertEqual(cal['days'][0]['messages'],350);self.assertEqual(cal['hours'][0]['messages'],60)
        first=self.reader.query(key,'messages',{'channel':CID,'day':'2026-04-11','hour':2})
        self.assertEqual((first['first'],first['last']),(121,200));self.assertTrue(first['before']);self.assertTrue(first['after'])
        prev=self.reader.query(key,'messages',{'channel':CID,'before':first['first']})
        self.assertEqual(prev['last'],120)
        after=self.reader.query(key,'messages',{'channel':CID,'after':first['last']})
        self.assertEqual(after['first'],201)
        search=self.reader.query(key,'messages',{'channel':CID,'q':'needle'})
        self.assertEqual(search['total'],175);self.assertEqual(len(search['messages']),80)
        self.assertEqual(self.reader.query(key,'messages',{'channel':CID,'q':'absent'})['messages'],[])
    def test_unchanged_index_reuse_and_replacement_closes_zip_handle(self):
        self.store.upsert(CID,[message(9001)]);result,key=self.publish()
        original=self.reader.query(key,'overview',{})
        with patch.object(self.reader,'build',side_effect=AssertionError('Unchanged ZIP rebuilt')):
            self.reader.query(key,'overview',{})
        self.store.upsert(CID,[message(9002)]);self.publish()
        updated=self.reader.query(key,'overview',{})
        self.assertNotEqual(original['generation'],updated['generation']);self.assertEqual(updated['channels'][0]['messages'],2)
        # Windows cannot replace an open ZIP without file sharing; this exercises a closed reader handle.
        moved=Path(result['path']).with_suffix('.moved');os.replace(result['path'],moved);os.replace(moved,result['path'])
    def zipped(self, entries):
        content=io.BytesIO()
        with zipfile.ZipFile(content,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in entries:
                info=zipfile.ZipInfo('placeholder');info.filename=name;info.orig_filename=name
                archive.writestr(info,data)
        return content.getvalue()
    def test_upload_dedup_isolation_and_original_library_preserved(self):
        def payload(cid,text):return json.dumps({'guild':{'id':SID,'name':'S'},'channel':{'id':cid,'name':cid},'messages':[message(9001,text)]})
        raw=self.zipped([('a.json',payload(CID,'archive one'))]);a=self.reader.upload(raw,'one.zip');b=self.reader.upload(raw,'same.zip')
        c=self.reader.upload(self.zipped([('b.json',payload(CID,'archive two'))]),'two.zip')
        self.assertEqual(a['id'],b['id']);self.assertEqual(len(self.reader.catalogue()),2)
        self.assertEqual(self.reader.query(a['id'],'messages',{'channel':CID})['messages'][0]['content'],'archive one')
        self.assertEqual(self.reader.query(c['id'],'messages',{'channel':CID})['messages'][0]['content'],'archive two')
        self.assertEqual(self.store.stats()['messages'],0)
    def test_unsafe_zip_and_missing_export_rejected(self):
        for name in ('../escape.json','/absolute.json','C:/drive.json','a\\b.json'):
            with self.assertRaises(ValueError):self.reader.upload(self.zipped([(name,'{}')]),'bad.zip')
        a=self.reader.upload(self.zipped([('note.txt','Hello')]),'notes.zip')
        with self.assertRaises(ValueError):self.reader.query(a['id'],'overview',{})
        with self.assertRaises(ValueError):self.reader.query('..','overview',{})
    def test_old_studio_html_and_markdown_fallback(self):
        m=message(9001,'literal <script>alert(1)</script>');m['timestamp']='2026-04-11T03:00:00Z'
        from studio.exporting import render
        for fmt in ('html','md','txt'):
            raw=render([m],fmt,{'id':CID,'name':'general','server_id':SID},options(None))
            a=self.reader.upload(self.zipped([('general.'+fmt,raw)]),fmt+'.zip')
            overview=self.reader.query(a['id'],'overview',{});cid=overview['channels'][0]['id']
            self.assertEqual(self.reader.query(a['id'],'messages',{'channel':cid})['messages'][0]['content'],m['content'])
    def test_empty_channel_and_invalid_calendar_are_explicit(self):
        raw=json.dumps({'channel':{'id':CID,'name':'empty'},'messages':[]})
        a=self.reader.upload(self.zipped([('empty.json',raw)]),'empty.zip')
        self.assertEqual(self.reader.query(a['id'],'overview',{})['channels'][0]['messages'],0)
        self.assertEqual(self.reader.query(a['id'],'messages',{'channel':CID})['messages'],[])
        with self.assertRaises(ValueError):self.reader.query(a['id'],'calendar',{'channel':CID,'month':'bad'})
    def test_profile_cache_and_zip_asset_are_offline_and_hash_specific(self):
        m=message(9001);m['author']['avatar']='a'*32;self.store.upsert(CID,[m]);avatars=self.exporter.avatars
        self.assertEqual(avatars.queue([CID])['queued'],1);self.assertEqual(avatars.queue([CID])['queued'],0)
        fake=b'RIFF\x10\x00\x00\x00WEBPfixture'
        def save(url,path,cap,control):path.write_bytes(fake);self.assertEqual(cap,1_000_000);return len(fake)
        with patch('studio.avatars.download',side_effect=save) as download:
            task=avatars.tasks()[0];avatars.fetch(task,lambda:True);avatars.fetch(task,lambda:True);self.assertEqual(download.call_count,1)
        result,key=self.publish({'include_avatars':True});page=self.reader.query(key,'messages',{'channel':CID});asset=page['messages'][0]['_avatar']
        self.assertEqual(self.reader.asset(key,asset),('image/webp',fake))
        with zipfile.ZipFile(result['path']) as z:self.assertEqual(len([n for n in z.namelist() if n.startswith('avatars/')]),1)
        m['author']['avatar']='b'*32;self.store.upsert(CID,[m]);self.assertEqual(avatars.queue([CID])['queued'],1)
    def test_picture_opt_in_shared_caps_failed_retry_and_priority(self):
        rows=[]
        for i in range(55):
            m=message(9000+i,author=str(8000+i));m['author']['avatar']='a'*32;rows.append(m)
        self.store.upsert(CID,rows);self.publish();avatars=self.exporter.avatars
        self.assertEqual(avatars.tasks(),[])
        result=avatars.queue([CID]);self.assertEqual((result['queued'],result['deferred']),(50,5))
        task=avatars.tasks()[0];avatars.update(task['key'],'failed','Failure')
        self.assertEqual(avatars.queue([CID])['queued'],1) # One previously deferred author; failure is not retried automatically.
        avatars.update(task['key'],'failed','Failure')
        with self.store.db() as db:db.execute("UPDATE avatar_tasks SET status='completed' WHERE status='queued'")
        self.assertGreater(avatars.queue([CID],retry=True)['queued'],0)
        connection=type('Offline',(),{'account':None,'token':None})()
        worker=Worker(self.store,connection);self.store.enqueue([CID],UID,options(None))
        with patch.object(worker.exporter.avatars,'fetch',side_effect=AssertionError('Pictures must wait for text')):worker.process_avatar()
    def test_avatar_download_rejects_active_document_and_keeps_default_off(self):
        self.assertFalse(options(None)['include_avatars']);self.assertIsNone(avatar_key({'id':UID,'avatarUrl':'https://evil.test/a.png'}))
        m=message(9001);m['author']['avatar']='a'*32;self.store.upsert(CID,[m]);a=self.exporter.avatars;a.queue([CID])
        def save(url,path,*args):path.write_bytes(b'<script>alert(1)</script>');return 25
        with patch('studio.avatars.download',side_effect=save),self.assertRaises(ValueError):a.fetch(a.tasks()[0],lambda:True)
        self.assertEqual(a.cached(),{})


if __name__=='__main__':unittest.main()
