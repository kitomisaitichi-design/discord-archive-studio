import concurrent.futures
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
from studio.store import Store
from studio.exporting import Exporter, options, render, safe_name
from studio.importing import import_data, DceHTML
from studio.access import Access, Inaccessible, permissions, VIEW, HISTORY, CONNECT
from studio.discord import Discord, AuthError, PermissionError, media_url
from studio.runtime import Worker
from studio.credentials import dpapi, aes_gcm_decrypt

SID, CID, UID = '800000000000000001', '800000000000000002', '800000000000000003'


def message(mid, content='Hello world', author=UID):
    return {'id': str(mid), 'channel_id': CID, 'author': {'id': author, 'username': 'Alice'},
            'timestamp': datetime.now(timezone.utc).isoformat(), 'content': content, 'attachments': []}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'Data')
        self.store.catalog([{'id': SID, 'name': 'Test server'}], [{'id': CID, 'name': 'general', 'type': 0}], SID)
        self.opts = options({'download_media': False, 'batch_messages': 100, 'cooldown_minutes': 1})

    def tearDown(self):
        self.temp.cleanup()


class StoreTests(Base):
    def test_queued_setting_changes_preserve_committed_checkpoint(self):
        jid=self.store.enqueue([CID],UID,dict(self.opts,_lower='9000',_initial=False))[0]
        self.store.update_job(jid,status='paused',cursor='9100',boundary='9200',progress=100)
        self.store.configure_job(jid,options({'formats':['md'],'batch_messages':500}))
        job=self.store.job(jid)
        self.assertEqual((job['cursor'],job['boundary'],job['progress']),('9100','9200',100))
        self.assertEqual(job['options']['_lower'],'9000')
        self.assertEqual(job['options']['batch_messages'],500)

    def test_repeat_preserves_distinct_identical_messages(self):
        msgs = [message('9001'), message('9002')]
        self.assertEqual(self.store.upsert(CID, msgs)['added'], 2)
        self.assertEqual(self.store.upsert(CID, msgs), {'added': 0, 'edited': 0})
        self.assertEqual(self.store.stats()['messages'], 2)

    def test_edit_updates_index_and_keeps_old_revision(self):
        m = message('9001', 'oldword')
        self.store.upsert(CID, [m])
        m['content'] = 'newword'
        self.assertEqual(self.store.upsert(CID, [m])['edited'], 1)
        self.assertEqual(self.store.search('oldword')['total'], 0)
        self.assertEqual(self.store.search('newword')['total'], 1)
        self.assertEqual(self.store.stats()['revisions'], 1)

    def test_expiring_cdn_url_does_not_count_as_edit(self):
        m = message('9001')
        m['attachments'] = [{'id': '999', 'url': 'https://cdn.discordapp.com/a.png?ex=1'}]
        self.store.upsert(CID, [m])
        gen = self.store.channels()[0]['generation']
        m['attachments'][0]['url'] = 'https://cdn.discordapp.com/a.png?ex=2'
        self.assertEqual(self.store.upsert(CID, [m])['edited'], 0)
        self.assertEqual(self.store.channels()[0]['generation'], gen)

    def test_bad_page_rolls_back(self):
        good, bad = message('9001'), message('bad-id')
        with self.assertRaises(ValueError):
            self.store.upsert(CID, [good, bad])
        self.assertEqual(self.store.stats()['messages'], 0)

    def test_alias_link_undo_and_names_do_not_merge_ids(self):
        self.store.upsert(CID, [message('9001'), message('9002', author='800000000000000004')])
        self.assertEqual(self.store.search(person=UID)['total'], 1)
        self.store.alias('800000000000000004', UID)
        self.assertEqual(self.store.search(person=UID)['total'], 2)
        self.store.alias('800000000000000004')
        self.assertEqual(self.store.search(person=UID)['total'], 1)

    def test_fts_empty_operators_and_punctuation(self):
        self.store.upsert(CID, [message('9001', 'Hello world!')])
        self.assertEqual(self.store.search('')['total'], 1)
        for query in ['"', 'OR', 'NEAR(foo)', '***', 'hello!']:
            self.store.search(query)

    def test_concurrent_double_enqueue_coalesces(self):
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda _: self.store.enqueue([CID], UID, self.opts), range(20)))
        self.assertEqual(len(self.store.jobs()), 1)
        self.assertEqual(len({r[0] for r in results}), 1)

    def test_restart_preserves_cursor_and_pauses_active_work(self):
        jid = self.store.enqueue([CID], UID, self.opts)[0]
        self.store.update_job(jid, status='running', cursor='9100', progress=100)
        reopened = Store(self.root / 'Data')
        self.assertEqual(reopened.job(jid)['cursor'], '9100')
        self.assertEqual(reopened.job(jid)['status'], 'paused')

    def test_running_schedule_updates_only_dirty_flag(self):
        jid = self.store.enqueue([CID], UID, self.opts)[0]
        self.store.update_job(jid, status='running')
        self.store.enqueue([CID], UID, self.opts, scheduled=True)
        self.assertEqual(len(self.store.jobs()), 1)
        self.assertTrue(self.store.job(jid)['dirty'])

    def test_seven_day_schedule_and_adaptive_empty_sample(self):
        self.store.schedule('channel:'+CID, UID, True, 'fixed', 10080, self.opts)
        self.assertEqual(self.store.schedules()[0]['minutes'], 10080)
        self.assertEqual(self.store.interval(CID)['minutes'], 10080)


class ExportTests(Base):
    def test_all_formats_split_and_zip_crc(self):
        self.store.upsert(CID, [message('9001', '<script>alert(1)</script>'), message('9002'), message('9003')])
        opts = options(dict(self.opts, formats=['html','json','md','txt'], split_count=2))
        result = Exporter(self.store).publish(SID, opts, self.root / 'Exports')
        with zipfile.ZipFile(result['path']) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(len([n for n in archive.namelist() if n.endswith('.json') and n!='manifest.json']), 2)
            page = archive.read('channels/'+CID+'/00001.html').decode()
            self.assertNotIn('<script>', page)
            self.assertIn('&lt;script&gt;', page)

    def test_same_server_zip_updates_and_noop_retains_mtime(self):
        self.store.upsert(CID, [message('9001')])
        exporter = Exporter(self.store)
        first = exporter.publish(SID, self.opts, self.root / 'Exports')
        timestamp = Path(first['path']).stat().st_mtime_ns
        second = exporter.publish(SID, dict(self.opts, batch_messages=5000, _lower='9001'), self.root / 'Exports')
        self.assertTrue(second['unchanged'])
        self.assertEqual(Path(first['path']).stat().st_mtime_ns, timestamp)
        self.store.upsert(CID, [message('9002')])
        third = exporter.publish(SID, self.opts, self.root / 'Exports')
        self.assertEqual(first['path'], third['path'])
        self.assertEqual(len(list((self.root/'Exports').glob('*.zip'))), 1)

    def test_cancelled_publication_preserves_previous_zip(self):
        self.store.upsert(CID, [message('9001')])
        exporter = Exporter(self.store)
        first = exporter.publish(SID, self.opts, self.root / 'Exports')
        old = Path(first['path']).read_bytes()
        self.store.upsert(CID, [message('9002')])
        from studio.discord import Interrupted
        with self.assertRaises(Interrupted):
            exporter.publish(SID, self.opts, self.root / 'Exports', lambda: False)
        self.assertEqual(Path(first['path']).read_bytes(), old)
        self.assertEqual(len(list((self.root/'Exports').glob('*.tmp'))), 0)

    def test_second_channel_merges_into_existing_server_zip(self):
        self.store.upsert(CID, [message('9001')])
        exporter = Exporter(self.store)
        path = exporter.publish(SID, self.opts, self.root/'Exports')['path']
        other = '800000000000000099'
        self.store.catalog([], [{'id':other,'name':'development','type':0}], SID)
        m = message('9002');m['channel_id']=other
        self.store.upsert(other, [m])
        exporter.publish(SID, self.opts, self.root/'Exports')
        with zipfile.ZipFile(path) as archive:
            self.assertTrue(any(other in n for n in archive.namelist()))
            self.assertTrue(any(CID in n for n in archive.namelist()))

    def test_filter_and_safe_names(self):
        for name in ['../../file','CON','a:b/thing','x\\y','']:
            self.assertNotIn('/',safe_name(name));self.assertNotIn('\\',safe_name(name))
        with self.assertRaises(ValueError):
            options({'start':'2026-10-12','end':'2026-01-01'})
        with self.assertRaises(ValueError):
            media_url('https://127.0.0.1/secret')
        with self.assertRaises(ValueError):
            media_url('file:///C:/secret')


class FakeAPI:
    def __init__(self, messages=None):
        self.messages=messages or []
        self.member=True
        self.visible=True
        self.calls=[]
        self.control=lambda:True

    def guilds(self):
        self.calls.append('membership')
        return [{'id':'0','name':'Direct messages'}]+([{'id':SID,'name':'Test server'}] if self.member else [])

    def get(self, route, **params):
        self.calls.append(route)
        if route.endswith('/roles'):
            return [{'id':SID,'permissions':str(VIEW|HISTORY)}]
        if '/members/' in route:
            return {'roles':[]}
        if route.endswith('/threads/active'):
            return {'threads':[]}
        if route.endswith('/channels'):
            return [{'id':CID,'name':'general','type':0,'permission_overwrites':[]}] if self.visible else []
        if route.endswith('/messages'):
            msgs=sorted(self.messages,key=lambda m:int(m['id']),reverse=True)
            if params.get('after') is not None:
                newer=[m for m in reversed(msgs) if int(m['id'])>int(params['after'])]
                return list(reversed(newer[:params.get('limit',100)]))
            if params.get('before'):
                msgs=[m for m in msgs if int(m['id'])<int(params['before'])]
            return msgs[:params.get('limit',100)]
        raise AssertionError('Unexpected endpoint: '+route)


class FakeConnection:
    token='not-a-live-token'
    account={'id':UID,'name':'Test user'}
    def __init__(self,api):self.client=api
    def api(self,control=None,status=None,delay=2.5):self.client.control=control or (lambda:True);return self.client


class AccessAndWorkerTests(Base):
    def test_left_server_never_probes_saved_guild_or_channel(self):
        api=FakeAPI();api.member=False
        with self.assertRaises(Inaccessible):Access(self.store).inventory(api,UID,SID,required_channel=CID)
        self.assertEqual(api.calls,['membership'])

    def test_removed_channel_never_reads_its_messages(self):
        api=FakeAPI();api.visible=False
        with self.assertRaises(Inaccessible):Access(self.store).inventory(api,UID,SID,required_channel=CID)
        self.assertFalse(any('/messages' in c for c in api.calls))

    def test_channel_permission_overwrites_and_thread_parent_gate(self):
        roles=[{'id':SID,'permissions':str(VIEW|HISTORY)}]
        channel={'permission_overwrites':[{'id':UID,'type':1,'deny':str(HISTORY),'allow':'0'}]}
        self.assertFalse(permissions(SID,UID,roles,{'roles':[]},channel)&HISTORY)

    def test_quarantine_disables_schedules_without_deleting_messages(self):
        self.store.upsert(CID,[message('9001')])
        self.store.schedule('server:'+SID,UID,True,'fixed',10,self.opts)
        self.store.enqueue([CID],UID,self.opts)
        Access(self.store).quarantine(SID,'Access removed')
        self.assertEqual(self.store.jobs()[0]['status'],'blocked')
        self.assertFalse(self.store.schedules()[0]['enabled'])
        self.assertEqual(self.store.stats()['messages'],1)
        self.store.enqueue([CID],UID,self.opts,True)
        self.assertEqual(len(self.store.jobs()),1)

    def test_batches_restart_resume_and_messages_arriving_during_export(self):
        api=FakeAPI([message(str(10000+i)) for i in range(230)])
        worker=Worker(self.store,FakeConnection(api));self.store.set_setting('destination',str(self.root/'Exports'))
        jid=self.store.enqueue([CID],UID,self.opts)[0]
        self.store.update_job(jid,status='running')
        worker.process(self.store.job(jid))
        self.assertEqual(self.store.job(jid)['status'],'waiting')
        self.assertEqual(self.store.stats()['messages'],100)
        cursor=self.store.job(jid)['cursor']
        reopened=Store(self.root/'Data')
        self.assertEqual(reopened.job(jid)['cursor'],cursor)
        worker.store=reopened;worker.access=Access(reopened);worker.exporter=Exporter(reopened)
        api.messages.append(message('10230','Arrived after the snapshot'))
        for _ in range(3):
            reopened.update_job(jid,status='running')
            worker.process(reopened.job(jid))
            if reopened.job(jid)['status']=='completed':break
        self.assertEqual(reopened.job(jid)['status'],'completed')
        self.assertEqual(reopened.stats()['messages'],230)
        self.assertEqual(len(reopened.jobs()),1)
        followup=reopened.jobs()[0]
        reopened.update_job(followup['id'],status='running');worker.process(reopened.job(followup['id']))
        self.assertEqual(reopened.stats()['messages'],231)
        self.assertEqual(len(list((self.root/'Exports').glob('*.zip'))),1)

    def test_channel_overrides_stay_independent(self):
        api=FakeAPI();worker=Worker(self.store,FakeConnection(api))
        self.store.schedule('server:'+SID,UID,True,'adaptive',1440,self.opts)
        self.store.schedule('channel:'+CID,UID,True,'fixed',10080,self.opts)
        worker.tick_schedules()
        channel=next(s for s in self.store.schedules() if s['scope']=='channel:'+CID)
        self.assertEqual(channel['minutes'],10080);self.assertEqual(channel['mode'],'fixed')


class ImportTests(Base):
    def test_lower_quality_import_cannot_replace_live_captured_content(self):
        m=message('9001','Current complete message')
        self.store.upsert(CID,[m])
        old=dict(m,content='Old partial export')
        data={'guild':{'id':SID},'channel':{'id':CID},'messages':[old]}
        import_data(self.store,json.dumps(data).encode(),'old.json')
        self.assertEqual(self.store.search()['messages'][0]['content'],'Current complete message')

    def test_message_id_search_and_known_channel_upgrade_keep_one_copy(self):
        other='900000000000000000001'
        self.store.catalog([{'id':'0','name':'Imported'}],[{'id':other,'name':'unknown'}],'0')
        m=message('1400000000000000001');m['channel_id']=other
        self.store.upsert(other,[m],quality=2)
        m['channel_id']=CID
        self.store.upsert(CID,[m],quality=3)
        result=self.store.search('1400000000000000001')
        self.assertEqual(result['total'],1)
        self.assertEqual(result['messages'][0]['channel_id'],CID)

    def test_json_and_zip_reimport_do_not_duplicate(self):
        data={'guild':{'id':SID,'name':'Test server'},'channel':{'id':CID,'name':'general'},'messages':[message('9001'),message('9002')]}
        raw=json.dumps(data).encode()
        self.assertEqual(import_data(self.store,raw,'export.json')['added'],2)
        self.assertTrue(import_data(self.store,raw,'renamed.json')['unchanged'])
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('../../export.json',raw)
        import_data(self.store,buf.getvalue(),'archive.zip')
        self.assertEqual(self.store.stats()['messages'],2)
        self.assertFalse((self.root.parent/'export.json').exists())

    def test_txt_repeated_identical_messages_preserved_and_reimport_coalesces(self):
        raw=b'Guild: Sample\nChannel: general\n[10/12/2026 1:00 PM] Alice\nhello\n[10/12/2026 1:00 PM] Alice\nhello\n'
        self.assertEqual(import_data(self.store,raw,'export.txt')['added'],2)
        self.assertTrue(import_data(self.store,raw,'export.txt')['unchanged'])

    def test_html_ids_and_text_without_running_script(self):
        raw=b'<div class="chatlog__message-group"><span class="chatlog__author" data-user-id="800000000000000003" title="Alice">Alice</span><div class="chatlog__message-container" data-message-id="1400000000000000001"><div class="chatlog__markdown-preserve">safe &lt;script&gt;literal&lt;/script&gt;</div></div></div>'
        result=import_data(self.store,raw,'export.html')
        self.assertEqual(result['added'],1)
        self.assertIn('literal',self.store.search()['messages'][0]['content'])

    def test_invalid_json_import_leaves_messages_unchanged(self):
        with self.assertRaises(ValueError):import_data(self.store,b'{"messages":null}','bad.json')
        self.assertEqual(self.store.stats()['messages'],0)


@unittest.skipUnless(os.name=='nt','Windows credential functions')
class CryptoTests(unittest.TestCase):
    def test_dpapi_and_nist_gcm_rejects_invalid_tag(self):
        secret=b'never-export-this-test-secret'
        protected=dpapi(secret,True)
        self.assertNotIn(secret,protected)
        self.assertEqual(dpapi(protected),secret)
        ct=bytes.fromhex('0388dace60b6a392f328c2b971b2fe78')
        tag=bytes.fromhex('ab6e47d42cec13bdf53a67b21257bddf')
        self.assertEqual(aes_gcm_decrypt(bytes(16),bytes(12),ct,tag),bytes(16))
        with self.assertRaises(ValueError):aes_gcm_decrypt(bytes(16),bytes(12),ct,bytes(16))


if __name__=='__main__':unittest.main()
