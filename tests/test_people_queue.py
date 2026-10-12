from pathlib import Path
import tempfile
import unittest
from studio.store import Store
from studio.people import People
from studio.exporting import options
from studio.discord import PermissionError
from test_studio import message,UID,CID

OWNER='800000000000000099'
BOB='800000000000000004'
CAROL='800000000000000005'
DM2='800000000000000012'
GROUP='800000000000000013'


class ContactAPI:
    def __init__(self):
        self.calls=[];self.denied=False
        self.channels=[{'id':CID,'type':1,'recipients':[{'id':UID,'username':'Alice'}]},
                       {'id':DM2,'type':1,'recipients':[{'id':BOB,'username':'Bob'}]},
                       {'id':GROUP,'type':3,'recipients':[{'id':UID,'username':'Alice'},{'id':BOB,'username':'Bob'}]}]
        self.friends=[{'id':UID,'type':1,'user':{'id':UID,'username':'Alice'}},
                      {'id':CAROL,'type':1,'user':{'id':CAROL,'username':'Carol'}},
                      {'id':BOB,'type':2,'user':{'id':BOB,'username':'Bob'}}]
    def get(self,path):
        self.calls.append(path)
        if path=='users/@me/channels':return self.channels
        if path=='users/@me/relationships':
            if self.denied:raise PermissionError('Friends inventory denied.')
            return self.friends
        raise AssertionError('No channel/message/user existence probes: '+path)


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name));self.people=People(self.store);self.api=ContactAPI();self.opts=options({})
    def tearDown(self):self.temp.cleanup()
    def test_local_metadata_cache_is_account_scoped_and_names_follow_ids(self):
        value=self.people.refresh(self.api,OWNER,True)
        self.assertEqual(len(value['contacts']),3)
        self.people.refresh(self.api,OWNER,True);self.assertEqual(len(self.api.calls),2)
        self.assertEqual(self.people.cached(BOB)['contacts'],[])
        self.api.channels[0]['recipients'][0]['username']='Renamed Alice'
        value=self.people.refresh(self.api,OWNER,force=True)
        alice=next(p for p in value['contacts'] if p['id']==UID)
        self.assertEqual(alice['name'],'Renamed Alice');self.assertTrue(alice['friend'])
    def test_future_defaults_apply_to_people_without_leaking_server_person_filter(self):
        self.store.configure_queue(OWNER,'future',{'cooldown_minutes':30,'people':[CAROL]})
        self.people.queue(self.api,OWNER,[UID],self.opts)
        job=self.store.jobs()[0];self.assertEqual(job['options']['cooldown_minutes'],30);self.assertEqual(job['options']['people'],[])

    def test_bulk_queue_deduplicates_shared_dm_and_repeated_actions(self):
        result=self.people.queue(self.api,OWNER,[UID,BOB,UID],self.opts,groups=True,adaptive=True)
        self.assertEqual(result['chats'],3);self.assertEqual(len(self.store.jobs()),3)
        self.people.queue(self.api,OWNER,[UID,BOB],dict(self.opts,full_rescan=True,people=[CAROL]),groups=True,adaptive=True)
        self.assertEqual(len(self.store.jobs()),3)
        for job in self.store.jobs():self.assertFalse(job['options']['full_rescan']);self.assertEqual(job['options']['people'],[])
        self.assertEqual(len(self.store.schedules()),3)
        self.assertTrue(all(s['mode']=='adaptive' for s in self.store.schedules()))
        self.assertTrue(all('messages' not in p for p in self.api.calls))
    def test_friends_only_queues_current_friend_dms_and_skips_absent_chats(self):
        value=self.people.refresh(self.api,OWNER,True)
        self.assertTrue(next(p for p in value['contacts'] if p['id']==CAROL)['friend'])
        result=self.people.queue(self.api,OWNER,[UID,BOB,CAROL],self.opts,friends=True)
        self.assertEqual((result['chats'],result['skipped']),(1,2));self.assertEqual(self.store.jobs()[0]['channel_id'],CID)
    def test_denied_friends_inventory_is_visible_and_never_inferred_or_retried(self):
        self.api.denied=True
        value=self.people.refresh(self.api,OWNER,True);self.assertFalse(value['friends_available']);self.assertIn('denied',value['friends_note'])
        self.people.refresh(self.api,OWNER,True);self.assertEqual(self.api.calls.count('users/@me/relationships'),1)
        self.assertFalse(any(p['friend'] for p in value['contacts']))
        with self.assertRaises(ValueError):self.people.queue(self.api,OWNER,[UID],self.opts,friends=True)
        self.assertEqual(self.store.jobs(),[])
    def test_closed_dm_is_skipped_without_old_channel_probe_and_schedules_survive(self):
        self.people.refresh(self.api,OWNER)
        self.store.schedule('channel:'+DM2,OWNER,False,'fixed',10080,self.opts)
        self.api.channels=[self.api.channels[1]]
        result=self.people.queue(self.api,OWNER,[UID,BOB],self.opts,adaptive=True)
        self.assertEqual((result['chats'],result['skipped']),(1,1))
        schedule=self.store.schedules()[0];self.assertFalse(schedule['enabled']);self.assertEqual(schedule['mode'],'fixed')
        self.assertTrue(all(p=='users/@me/channels' for p in self.api.calls))
    def test_queue_does_not_change_existing_message_checkpoint(self):
        self.people.refresh(self.api,OWNER);self.store.upsert(CID,[message('9001')])
        self.people.queue(self.api,OWNER,[UID],self.opts)
        self.assertEqual(self.store.newest_saved(CID),'9001');self.assertEqual(self.store.stats()['messages'],1)
    def test_repeated_people_enqueue_preserves_resumed_forward_sweep(self):
        self.people.queue(self.api,OWNER,[UID],self.opts)
        jid=self.store.jobs()[0]['id'];internal=dict(self.opts,_lower='9000',_initial=False,_forward=True)
        with self.store.db() as db:
            from studio.store import packed
            db.execute('UPDATE jobs SET options=?,cursor=?,boundary=?,progress=? WHERE id=?',(packed(internal),'9100','9200',100,jid))
        self.people.queue(self.api,OWNER,[UID],dict(self.opts,formats=['md']))
        job=self.store.job(jid)
        self.assertEqual((job['cursor'],job['boundary'],job['progress']),('9100','9200',100))
        self.assertEqual(job['options']['_lower'],'9000');self.assertTrue(job['options']['_forward']);self.assertFalse(job['options']['_initial'])


class QueuePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=Store(self.root)
        self.channels=[CID,DM2,GROUP,'800000000000000014']
        self.store.catalog([{'id':'0','name':'DMs'}],[{'id':cid,'type':1,'name':'Chat '+str(n)} for n,cid in enumerate(self.channels)],'0')
        self.opts=options({});self.jobs=self.store.enqueue(self.channels,OWNER,self.opts)
    def tearDown(self):self.temp.cleanup()
    def test_drag_reorder_preserves_running_position_cursors_and_cooldown(self):
        a,b,c,d=self.jobs;self.store.update_job(a,status='running');self.store.update_job(b,status='waiting',cursor='9100',boundary='9200',progress=100)
        self.store.update_job(c,status='paused');self.store.update_job(d,status='blocked')
        self.store.set_setting('cooldown_until',9999999999);old=self.store.job(b)
        self.store.reorder(d,b)
        self.assertEqual([j['id'] for j in self.store.jobs()],[a,d,b,c]);self.assertEqual(self.store.job(a)['position'],1)
        new=self.store.job(b);self.assertEqual({k:v for k,v in old.items() if k!='position'},{k:v for k,v in new.items() if k!='position'})
        self.assertEqual(self.store.setting('cooldown_until'),9999999999)
        reopened=Store(self.root);self.assertEqual([j['id'] for j in reopened.jobs()],[a,d,b,c]);self.assertEqual(reopened.job(b)['cursor'],'9100')
    def test_running_or_stale_drop_is_rejected_and_waiting_arrows_work(self):
        a,b,c,d=self.jobs;self.store.update_job(a,status='running');self.store.update_job(b,status='waiting')
        with self.assertRaises(ValueError):self.store.reorder(a,b)
        with self.assertRaises(ValueError):self.store.reorder(b,a)
        self.store.control(b,'down');self.assertEqual([j['id'] for j in self.store.jobs()],[a,c,b,d])
        self.store.update_job(d,status='running')
        with self.assertRaises(ValueError):self.store.reorder(d,b)
    def test_preview_keyset_has_no_gaps_when_new_messages_arrive(self):
        stamp='2026-10-12T12:00:00+00:00'
        messages=[dict(message(mid),timestamp=stamp) for mid in ('99','100','101','102')];self.store.upsert(CID,messages)
        first=self.store.preview(CID,limit=2);self.assertEqual([m['id'] for m in first['messages']],['102','101']);self.assertTrue(first['has_more'])
        self.store.upsert(CID,[dict(message('103'),timestamp=stamp)])
        older=self.store.preview(CID,first['next_cursor'],2);self.assertEqual([m['id'] for m in older['messages']],['100','99']);self.assertFalse(older['has_more'])
        self.store.upsert(DM2,[dict(message('200'),channel_id=DM2,timestamp=stamp)])
        with self.assertRaises(ValueError):self.store.preview(CID,'200')
