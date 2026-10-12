import tempfile
import unittest
from studio.store import Store
from studio.runtime import Connection,Worker
from studio.exporting import DEFAULT_OPTIONS

class ScheduleManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.owner='7';self.server='server:10';self.inherited='channel:11';self.explicit='channel:12'
        self.store.catalog([{'id':'10','name':'Server'}],[{'id':'11','name':'One','type':0},{'id':'12','name':'Two','type':0},{'id':'13','name':'Other','type':0}],'10')
        self.opts=dict(DEFAULT_OPTIONS,formats=['json'],cooldown_minutes=15)
        self.store.schedule(self.server,self.owner,True,'fixed',1440,self.opts)
        self.store.schedule(self.inherited,self.owner,True,'fixed',1440,dict(self.opts,inherited=True))
        self.store.schedule(self.explicit,self.owner,True,'fixed',10080,self.opts)
        self.store.schedule('channel:13','8',True,'fixed',1440,self.opts)
        self.job=self.store.enqueue(['11'],self.owner,self.opts)[0]
        self.store.update_job(self.job,cursor='99',boundary='200',progress=100,status='waiting')
        self.store.set_setting('cooldown_until',9999999999)
        self.before=self.store.job(self.job)
    def tearDown(self):self.temp.cleanup()
    def test_pause_default_propagates_only_to_inherited_and_retains_checkpoints(self):
        result=self.store.manage_schedules(self.owner,'pause',[self.server]);self.assertEqual(result['changed'],2)
        rows={s['scope']:s for s in self.store.schedules()}
        self.assertFalse(rows[self.server]['enabled']);self.assertFalse(rows[self.inherited]['enabled'])
        self.assertTrue(rows[self.explicit]['enabled']);self.assertTrue(rows['channel:13']['enabled'])
        self.assertEqual(self.before,self.store.job(self.job));self.assertEqual(self.store.setting('cooldown_until'),9999999999)
    def test_selected_channel_pause_is_an_independent_override(self):
        self.store.manage_schedules(self.owner,'pause',[self.inherited])
        row=next(s for s in self.store.schedules() if s['scope']==self.inherited)
        self.assertFalse(row['options']['inherited']);self.assertEqual(row['options']['formats'],['json'])
    def test_remove_channel_is_not_recreated_and_explicit_readd_clears_exclusion(self):
        self.store.manage_schedules(self.owner,'remove',[self.inherited])
        connection=Connection(self.store);connection.account={'id':self.owner}
        Worker(self.store,connection).tick_schedules()
        self.assertNotIn(self.inherited,[s['scope'] for s in self.store.schedules()])
        self.assertEqual(next(s for s in self.store.schedules() if s['scope']=='channel:13')['owner_id'],'8')
        self.store.schedule(self.inherited,self.owner,True,'fixed',1440,self.opts)
        self.assertNotIn(self.inherited,self.store.setting('schedule_exclusions:'+self.owner))
    def test_remove_default_cascades_and_repeat_preserves_undo(self):
        before={s['scope']:s for s in self.store.schedules()}
        self.assertEqual(self.store.manage_schedules(self.owner,'remove',[self.server])['changed'],2)
        self.assertEqual(self.store.manage_schedules(self.owner,'remove',[self.server])['changed'],0)
        self.assertEqual(self.store.manage_schedules(self.owner,'restore')['changed'],2)
        self.assertEqual(before,{s['scope']:s for s in self.store.schedules()})
    def test_clear_is_owner_scoped_and_undo_does_not_overwrite_new_edits(self):
        self.assertEqual(self.store.manage_schedules(self.owner,'clear')['changed'],3)
        self.assertEqual([s['scope'] for s in self.store.schedules()],['channel:13'])
        self.store.schedule(self.explicit,self.owner,False,'fixed',30,self.opts)
        self.assertEqual(self.store.manage_schedules(self.owner,'restore')['changed'],2)
        row=next(s for s in self.store.schedules() if s['scope']==self.explicit)
        self.assertEqual(row['minutes'],30);self.assertFalse(row['enabled'])
        self.assertEqual(self.before,self.store.job(self.job))
    def test_cross_account_selection_rolls_back_everything(self):
        before=self.store.schedules()
        with self.assertRaises(ValueError):self.store.manage_schedules(self.owner,'remove',[self.server,'channel:13'])
        self.assertEqual(before,self.store.schedules())
