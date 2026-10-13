import io
import json
import time
import zipfile
from unittest.mock import patch
from test_studio import Base,SID,CID,UID,message
from studio.emojis import references,content_html
from studio.exporting import Exporter,options
from studio.runtime import Worker
from studio.zipreader import ZipReader


class EmojiTests(Base):
    def setUp(self):
        super().setUp();self.exporter=Exporter(self.store);self.emojis=self.exporter.emojis

    def save(self,text='<:Clueless:123>',mid=9001):
        m=message(mid,text);self.store.upsert(CID,[m]);return m

    def fake(self,url,path,cap,control):
        self.assertEqual(cap,1_000_000);self.assertTrue(control());path.write_bytes(b'GIF89aemoji');return 11

    def test_captured_ids_global_across_names_servers_and_reactions(self):
        m=self.save();m2=message(9002,'<:Renamed:123>');m2['reactions']=[{'emoji':{'id':'123','name':'Clueless'},'count':4}]
        m2['channel_id']='21'
        self.store.catalog([{'id':'20','name':'Other'}],[{'id':'21','name':'other'}],'20');self.store.upsert('21',[m2])
        task=self.emojis.task();self.assertEqual(task['id'],'123')
        with patch('studio.emojis.download',side_effect=self.fake) as download:
            self.emojis.fetch(task,lambda:True);self.emojis.fetch(task,lambda:True)
            self.emojis.capture([m,m2]);self.assertEqual(download.call_count,1)
        self.assertEqual(set(self.emojis.servers('123')),{SID,'20'})
        self.assertEqual(len(self.emojis.library()['emojis']),1)
        self.assertEqual(len(self.emojis.library('Clueless')['emojis']),1)

    def test_code_preserved_and_untrusted_html_escaped(self):
        m=message(9001,'<script>bad</script> <:Smile:123> `<:Literal:456>`\n```<a:Code:789>``` 😀')
        m['reactions']=[{'emoji':{'id':'999','name':'Animated','animated':True},'count':1}]
        self.assertEqual(set(references(m)),{'123','999'})
        self.assertTrue(references(m)['999']['animated'])
        output=content_html(m['content'])
        self.assertNotIn('<script>',output);self.assertIn(':Smile:',output);self.assertIn('&lt;:Literal:456&gt;',output);self.assertIn('😀',output)
        self.assertNotIn('<img',content_html('<:Smile:123>',{'123':'javascript:evil'}))

    def test_shared_caps_deferred_refs_are_durable_and_promote_without_history(self):
        self.save(' '.join('<:E%s:%s>'%(i,1000+i) for i in range(60)))
        self.emojis.promote()
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM emojis WHERE status='queued'").fetchone()[0],50)
            self.assertEqual(db.execute("SELECT count(*) FROM emojis WHERE status='deferred'").fetchone()[0],10)
        self.assertEqual(self.exporter.avatars.visible({'9001':{'id':UID,'avatar':'a'*32}})['pictures']['9001']['status'],'deferred')
        self.emojis.update('1000','failed','Missing')
        self.emojis.capture([message(9001,'<:E0:1000>')]);self.assertEqual(self.emojis.library('1000')['emojis'][0]['status'],'failed')
        with self.store.db() as db:db.execute("UPDATE emojis SET status='completed' WHERE status='queued'")
        self.emojis.promote()
        with self.store.db() as db:self.assertEqual(db.execute("SELECT count(*) FROM emojis WHERE status='queued'").fetchone()[0],9)

    def test_visible_refs_take_priority_without_expanding_shared_cap(self):
        self.save(' '.join('<:E%s:%s>'%(i,1000+i) for i in range(60)))
        self.emojis.promote()
        self.emojis.capture([message(9002,'<:E59:1059>')])
        self.assertEqual(self.emojis.task()['id'],'1059')
        with self.store.db() as db:self.assertEqual(db.execute("SELECT count(*) FROM emojis WHERE status IN ('queued','running')").fetchone()[0],50)

    def test_animation_format_and_content_hash_dedup(self):
        self.save('<a:Dance:123> <:Smile:456>')
        self.emojis.promote()
        with patch('studio.emojis.download',side_effect=self.fake) as download:
            for row in self.emojis.library()['emojis']:self.emojis.fetch(row,lambda:True)
        urls=[c.args[0] for c in download.call_args_list]
        self.assertTrue(any('/123.gif?' in u for u in urls));self.assertTrue(any('/456.png?' in u for u in urls))
        self.assertEqual(len(list((self.store.root/'emojis').iterdir())),1)

    def test_offline_zip_graphic_render_raw_json_and_reuse(self):
        m=self.save();self.emojis.promote()
        first=self.exporter.publish(SID,options(None),self.root/'Exports')
        with patch('studio.emojis.download',side_effect=self.fake):self.emojis.fetch(self.emojis.task(),lambda:True)
        second=self.exporter.publish(SID,options(None),self.root/'Exports',selected_channels=[])
        self.assertFalse(second['unchanged']);self.assertEqual(first['path'],second['path'])
        self.assertTrue(self.exporter.publish(SID,options(None),self.root/'Exports',selected_channels=[])['unchanged'])
        with zipfile.ZipFile(second['path']) as z:
            self.assertEqual(len([n for n in z.namelist() if n.startswith('emojis/')]),1)
            html=z.read('channels/'+CID+'/00001.html').decode();self.assertIn('class="custom-emoji"',html)
            self.assertEqual(json.loads(z.read('channels/'+CID+'/00001.json'))['messages'][0]['content'],m['content'])
        reader=ZipReader(self.store,scan_parent=False);key=next(e['id'] for e in reader.catalogue() if e['source']=='export')
        with patch('studio.discord.Discord.get',side_effect=AssertionError('No Discord history or member lookup')):
            page=reader.query(key,'messages',{'channel':CID});asset=page['messages'][0]['_emoji_assets']['123']
            self.assertEqual(reader.asset(key,asset),('image/gif',b'GIF89aemoji'))

    def test_worker_uses_rest_and_groups_zip_publication(self):
        self.save('<:One:123> <:Two:456>')
        self.exporter.publish(SID,options(None),self.root/'Exports')
        worker=Worker(self.store,type('Offline',(),{'account':None,'token':None})())
        self.store.enqueue([CID],UID,options(None))
        with patch('studio.emojis.download',side_effect=self.fake) as download,patch.object(worker.exporter,'publish') as publish:
            worker.process_emoji();self.assertEqual(download.call_count,0)
            self.store.set_setting('cooldown_until',time.time()+300)
            worker.process_emoji();self.assertEqual(download.call_count,1);self.assertEqual(publish.call_count,0)
            self.store.set_setting('media_next',0);worker.process_emoji();self.assertEqual(download.call_count,2);self.assertEqual(publish.call_count,0)
            # Only already published servers get rebuilt; no unsolicited full-library export.
            self.assertEqual(set(self.store.setting('emoji_zip_dirty')), {SID})
            worker.process_emoji();self.assertEqual(publish.call_count,1)
            self.assertEqual(self.store.setting('emoji_zip_dirty'),[])

    def test_existing_local_graphic_becomes_shared_reference_without_download(self):
        with patch('studio.emojis.download',side_effect=AssertionError('Already local')):
            self.emojis.import_asset('123',b'GIF89alocal','Clueless')
            result=self.emojis.capture([message(9001,'<:Clueless:123>')]);self.assertIn('/emoji/',result['emojis']['123']['url'])
            self.assertIsNone(self.emojis.task())
        self.assertIn(':Clueless:',__import__('studio.emojis',fromlist=['content_text']).content_text('<:Clueless:123>'))

    def test_bad_raster_rejected_failure_never_retries_automatically(self):
        self.save();task=self.emojis.task()
        def malicious(url,path,*args):path.write_bytes(b'<svg onload="evil"/>');return 20
        with patch('studio.emojis.download',side_effect=malicious),self.assertRaises(ValueError):self.emojis.fetch(task,lambda:True)
        self.emojis.update('123','failed','Unavailable')
        self.emojis.capture([message(9001,'<:Clueless:123>')]);self.assertIsNone(self.emojis.task())
        self.emojis.retry(['123']);self.assertEqual(self.emojis.task()['id'],'123')
