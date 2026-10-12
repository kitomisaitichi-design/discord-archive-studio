from datetime import datetime,timezone,timedelta
from test_studio import Base,FakeAPI,FakeConnection,message,SID,CID,UID
from studio.runtime import Worker
from studio.exporting import options


class IncrementalTests(Base):
    def test_large_old_history_is_never_requested_again_and_new_tail_resumes(self):
        old=message('949349','Saved three-year checkpoint')
        old['timestamp']=(datetime.now(timezone.utc)-timedelta(days=1095)).isoformat()
        self.store.upsert(CID,[old])
        class TailOnly(FakeAPI):
            def __init__(self):
                super().__init__([message(str(949350+n)) for n in range(350)])
                self.pages=[]
            def get(self,route,**params):
                if route.endswith('/messages') and params.get('limit')==100:
                    if 'before' in params:
                        raise AssertionError('Cached history must not be requested on a normal scan.')
                    self.pages.append(dict(params))
                return super().get(route,**params)
        api=TailOnly();worker=Worker(self.store,FakeConnection(api));self.store.set_setting('destination',str(self.root/'Exports'))
        jid=self.store.enqueue([CID],UID,self.opts)[0]
        for _ in range(4):
            self.store.update_job(jid,status='running');worker.process(self.store.job(jid))
        self.assertEqual(self.store.job(jid)['status'],'completed')
        self.assertEqual(self.store.job(jid)['progress'],350)
        self.assertEqual([p['after'] for p in api.pages],['949349','949449','949549','949649'])
        self.assertEqual(self.store.stats()['messages'],351)
        # Partial imported/cancelled history does not silently turn into a full backfill.
        self.assertFalse(self.store.channels()[0]['history_done'])
        count=len(api.pages)
        second=self.store.enqueue([CID],UID,self.opts)[0]
        self.store.update_job(second,status='running');worker.process(self.store.job(second))
        self.assertEqual(len(api.pages),count)
        self.assertEqual(self.store.job(second)['progress'],0)

    def test_schedules_never_repeat_full_history_or_backfill_unseen_old_channels(self):
        opts=options({'full_rescan':True})
        self.store.schedule('channel:'+CID,UID,True,'fixed',10,opts)
        self.assertFalse(self.store.schedules()[0]['options']['full_rescan'])
        api=FakeAPI([message(str(10000+n)) for n in range(1000)])
        worker=Worker(self.store,FakeConnection(api));self.store.set_setting('destination',str(self.root/'Exports'))
        jid=self.store.enqueue([CID],UID,opts,scheduled=True)[0]
        self.assertFalse(self.store.job(jid)['options']['full_rescan'])
        self.store.update_job(jid,status='running');worker.process(self.store.job(jid))
        self.assertEqual(self.store.stats()['messages'],0)
        self.assertEqual(self.store.job(jid)['progress'],0)
        self.assertEqual(self.store.channels()[0]['last_id'],'10999')

    def test_recent_edit_recheck_is_explicit_and_bounded(self):
        self.store.upsert(CID,[message('9999','Cached text')])
        api=FakeAPI([message(str(9000+n),'Updated' if 9000+n==9999 else 'Old') for n in range(1000)])
        worker=Worker(self.store,FakeConnection(api));self.store.set_setting('destination',str(self.root/'Exports'))
        jid=self.store.enqueue([CID],UID,options({'recheck_edits':True,'batch_messages':1000}))[0]
        self.store.update_job(jid,status='running');worker.process(self.store.job(jid))
        self.assertEqual(self.store.job(jid)['progress'],500)
        self.assertEqual(self.store.search('9999')['messages'][0]['content'],'Updated')

    def test_explicit_full_history_catchup_returns_to_new_only(self):
        api=FakeAPI([message(str(10000+n)) for n in range(3)])
        worker=Worker(self.store,FakeConnection(api));self.store.set_setting('destination',str(self.root/'Exports'))
        jid=self.store.enqueue([CID],UID,options({'full_rescan':True}))[0]
        self.store.update_job(jid,status='running',dirty=1);worker.process(self.store.job(jid))
        catchup=self.store.jobs()[0]
        self.assertFalse(catchup['options']['full_rescan'])
        self.store.update_job(catchup['id'],status='running');worker.process(self.store.job(catchup['id']))
        self.assertEqual(self.store.job(catchup['id'])['progress'],0)
