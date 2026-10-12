import tempfile,threading,unittest
from studio.store import Store
from studio.exporting import DEFAULT_OPTIONS
from studio.runtime import Connection,Worker

class QueueSettingsTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.owner='7'
  self.store.catalog([{'id':'10','name':'Test'}],[{'id':str(i),'name':str(i),'type':0} for i in range(11,18)],'10')
  self.jobs=self.store.enqueue(['11','12','13'],self.owner,DEFAULT_OPTIONS)
  self.store.update_job(self.jobs[0],status='waiting',cursor='99',boundary='1000',progress=100)
  self.store.set_setting('cooldown_until',9999999999)
 def tearDown(self):self.temp.cleanup()
 def test_waiting_edit_preserves_cursor_internal_direction_other_fields_and_rest(self):
  with self.store.db() as db:
   import json
   opts=dict(DEFAULT_OPTIONS,_forward=True,_lower='90');db.execute('UPDATE jobs SET options=? WHERE id=?',(json.dumps(opts),self.jobs[0]))
  old=self.store.job(self.jobs[0]);self.store.configure_queue(self.owner,'items',{'page_delay':10},[self.jobs[0]])
  new=self.store.job(self.jobs[0]);self.assertEqual(new['options']['page_delay'],10)
  for key in ('status','cursor','boundary','phase','progress','position'):self.assertEqual(old[key],new[key])
  for key in ('_forward','_lower','formats','start','cooldown_minutes'):self.assertEqual(old['options'][key],new['options'][key])
  self.assertEqual(self.store.setting('cooldown_until'),9999999999)
 def test_all_skips_running_and_other_owner_without_altering_future_defaults(self):
  self.store.update_job(self.jobs[1],status='running');active=self.store.job(self.jobs[1])
  other=self.store.enqueue(['14'],'8',DEFAULT_OPTIONS)[0]
  result=self.store.configure_queue(self.owner,'all',{'batch_messages':500})
  self.assertEqual(result['changed'],2);self.assertEqual(active,self.store.job(self.jobs[1]))
  self.assertEqual(self.store.job(other)['options']['batch_messages'],1000);self.assertIsNone(self.store.setting('queue_defaults:7'))
 def test_stale_active_owner_and_invalid_merged_edits_are_atomic(self):
  old=self.store.job(self.jobs[0]);self.store.update_job(self.jobs[1],status='running')
  with self.assertRaises(ValueError):self.store.configure_queue(self.owner,'items',{'page_delay':10},self.jobs[:2],future=True)
  self.assertEqual(old,self.store.job(self.jobs[0]));self.assertIsNone(self.store.setting('queue_defaults:7'))
  with self.assertRaises(ValueError):self.store.configure_queue('8','items',{'page_delay':10},[self.jobs[0]])
  with self.assertRaises(ValueError):self.store.configure_queue(self.owner,'items',{'start':'2026-12-31','end':'2026-01-01'},[self.jobs[0]])
  with self.assertRaises(ValueError):self.store.configure_queue(self.owner,'items',{'full_rescan':True},[self.jobs[0]])
 def test_defaults_affect_only_future_manual_scheduled_and_opt_in_jobs(self):
  before=self.store.job(self.jobs[0]);self.store.configure_queue(self.owner,'future',{'cooldown_minutes':15,'formats':['json']})
  self.assertEqual(before,self.store.job(self.jobs[0]))
  for cid,scheduled in [('14',False),('15',True)]:
   jid=self.store.enqueue([cid],self.owner,DEFAULT_OPTIONS,scheduled=scheduled)[0]
   self.assertEqual(self.store.job(jid)['options']['cooldown_minutes'],15);self.assertEqual(self.store.job(jid)['options']['formats'],['json'])
  jid=self.store.enqueue(['16'],self.owner,dict(DEFAULT_OPTIONS,_use_queue_defaults=False))[0]
  self.assertEqual(self.store.job(jid)['options']['cooldown_minutes'],5)
  jid=self.store.enqueue(['17'],'8',DEFAULT_OPTIONS)[0];self.assertEqual(self.store.job(jid)['options']['cooldown_minutes'],5)
 def test_explicit_item_override_survives_repeat_enqueue_and_defaults_change(self):
  jid=self.jobs[2];self.store.configure_queue(self.owner,'items',{'cooldown_minutes':30},[jid])
  self.store.configure_queue(self.owner,'future',{'cooldown_minutes':15})
  self.store.enqueue(['13'],self.owner,DEFAULT_OPTIONS)
  self.assertEqual(self.store.job(jid)['options']['cooldown_minutes'],30)
 def test_preferences_and_defaults_survive_restart_without_saving_full_rescan(self):
  pref={'options':dict(DEFAULT_OPTIONS,cooldown_minutes=15,timing_variation=30,page_delay=10,formats=['json'],full_rescan=True),'scope':'channel','mode':'adaptive','minutes':10080,'advanced':True,'use_defaults':False,'updated':200}
  self.store.save_queue_preferences(self.owner,pref);self.store.configure_queue(self.owner,'future',{'cooldown_minutes':15})
  reopened=Store(self.temp.name);saved=reopened.setting('queue_preferences:7')
  self.assertEqual(saved['options']['cooldown_minutes'],15);self.assertEqual(saved['options']['formats'],['json']);self.assertFalse(saved['options']['full_rescan'])
  self.assertTrue(saved['advanced']);self.assertEqual(saved['minutes'],10080);self.assertEqual(reopened.setting('queue_defaults:7'),{'cooldown_minutes':15})
  self.assertIsNone(reopened.setting('queue_preferences:8'))
 def test_out_of_order_preference_save_cannot_overwrite_newer_settings(self):
  newer=self.store.save_queue_preferences(self.owner,{'options':dict(DEFAULT_OPTIONS,page_delay=10),'updated':200})
  self.assertEqual(self.store.save_queue_preferences(self.owner,{'options':DEFAULT_OPTIONS,'updated':100}),newer)
 def test_paused_request_stays_locked_until_worker_releases_it(self):
  jid=self.jobs[0];self.assertTrue(self.store.claim_job(jid,self.owner));self.store.control(jid,'pause');old=self.store.job(jid)
  with self.assertRaises(ValueError):self.store.configure_queue(self.owner,'items',{'page_delay':10},[jid])
  self.store.configure_queue(self.owner,'all',{'page_delay':10});self.assertEqual(old,self.store.job(jid))
  self.store.release_job(jid);self.store.configure_queue(self.owner,'items',{'page_delay':10},[jid]);self.assertEqual(self.store.job(jid)['options']['page_delay'],10)

 def test_actual_worker_claim_and_edit_observe_one_consistent_options_snapshot(self):
  self.store.set_setting('cooldown_until',0);self.store.update_job(self.jobs[0],status='queued')
  connection=Connection(self.store);connection.account={'id':self.owner};connection.token='fixture-no-network'
  captured=[];barrier=threading.Barrier(2);store=self.store
  class TestWorker(Worker):
   def process(self,job):captured.append(job);self.stop.set();self.signal()
   def process_media(self):pass
  worker=TestWorker(store,connection)
  def run():barrier.wait();worker.run()
  thread=threading.Thread(target=run);thread.start();barrier.wait()
  try:store.configure_queue(self.owner,'items',{'page_delay':10},[self.jobs[0]]);edited=True
  except ValueError:edited=False
  thread.join(5);self.assertFalse(thread.is_alive());self.assertEqual(len(captured),1)
  self.assertEqual(captured[0]['options']['page_delay'],10 if edited else DEFAULT_OPTIONS['page_delay'])
  self.assertEqual(captured[0]['cursor'],'99')
