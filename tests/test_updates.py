import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
import urllib.error
import zipfile

from studio.store import Store
from studio.updates import Updater,validate_package,safe_name,version,REPOSITORY
from studio.update_installer import install,replace_payload,rollback


def package(root,extra=None,release_version="1.7.0"):
    files={'app.py':b'new app','studio/server.py':b'new server','studio/update_installer.py':b'helper',
           'runtime/python.exe':b'runtime','runtime/pythonw.exe':b'windowless'}
    files.update(extra or {})
    manifest={'app':'Discord Archive Studio','version':release_version,'files':{name:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for name,raw in files.items()}}
    archive=root/'package.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for name,raw in files.items():z.writestr('Discord-Archive-Studio-v'+release_version+'-Portable/'+name,raw)
        z.writestr('Discord-Archive-Studio-v'+release_version+'-Portable/MANIFEST.json',json.dumps(manifest))
    return archive,'sha256:'+hashlib.sha256(archive.read_bytes()).hexdigest(),manifest,files


class UpdatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'Data')
        self.worker=Mock();self.worker.maintenance=threading.Event();self.worker.cycle_lock=threading.Lock();self.worker.stop=threading.Event()
        self.server=Mock();self.server.server_port=54321
        self.updater=Updater(self.store,self.root,self.worker,self.server)

    def tearDown(self):self.tmp.cleanup()

    def test_defaults_and_saved_controls(self):
        self.assertEqual(self.updater.settings(),{'enabled':True,'minutes':1440})
        self.updater.configure({'enabled':False,'minutes':360})
        self.assertEqual(Updater(self.store,self.root,self.worker,self.server).settings(),{'enabled':False,'minutes':360})
        with self.assertRaises(ValueError):self.updater.configure({'minutes':1})
        with self.assertRaises(ValueError):self.updater.configure({'enabled':'false'})

    def test_package_digest_paths_and_manifest(self):
        archive,digest,manifest,_=package(self.root)
        self.assertEqual(validate_package(archive,'1.7.0',digest)[0],manifest)
        with self.assertRaises(ValueError):validate_package(archive,'1.7.0','sha256:'+'0'*64)
        with self.assertRaises(ValueError):validate_package(archive,'1.6.0',digest)
        for name in ('../app.py','Data/archive.sqlite3','runtime/../Data/x','runtime/C:x','runtime/CON.txt','runtime/a.','web\\x.js','/app.py'):
            with self.subTest(name=name),self.assertRaises(ValueError):safe_name(name)
        archive,digest,_,_=package(self.root,{'Data/secrets':b'bad'})
        with self.assertRaises(ValueError):validate_package(archive,'1.7.0',digest)

    def test_checked_download_and_public_asset_scope(self):
        # The fixture must be newer than CURRENT_VERSION to exercise staging.
        archive,digest,_,_=package(self.root,release_version='1.7.2');raw=archive.read_bytes()
        (self.root/'MANIFEST.json').write_text('{}');(self.root/'runtime').mkdir();(self.root/'runtime/pythonw.exe').write_bytes(b'old')
        self.updater.portable=True
        asset={'name':'Discord-Archive-Studio-v1.7.2-Portable.zip','state':'uploaded','size':len(raw),'digest':digest,
               'browser_download_url':'https://github.com/'+REPOSITORY+'/releases/download/v1.7.2/Discord-Archive-Studio-v1.7.2-Portable.zip'}
        release={'tag_name':'v1.7.2','assets':[asset]}
        class Response(io.BytesIO):
            headers={'ETag':'"fixture"'}
        with patch('urllib.request.urlopen',side_effect=[Response(json.dumps(release).encode()),Response(raw)]) as network:
            self.updater.check()
        state=self.updater.status();self.assertEqual(state['status'],'ready');self.assertEqual(network.call_count,2)
        self.assertTrue((self.root/self.store.setting('application_update_state')['payload']/'app.py').is_file())
        not_modified=urllib.error.HTTPError('fixture',304,'unchanged',{},None)
        with patch('urllib.request.urlopen',side_effect=not_modified) as network:self.updater.check()
        self.assertEqual(self.updater.status()['status'],'ready');self.assertEqual(network.call_count,1)
        asset['browser_download_url']='https://example.invalid/evil.zip'
        with patch('urllib.request.urlopen',return_value=Response(json.dumps(release).encode())):self.updater.check()
        self.assertEqual(self.updater.status()['status'],'error')

    def test_check_failure_backs_off_and_remains_visible(self):
        with patch('urllib.request.urlopen',side_effect=OSError('Fixture offline')):self.updater.check()
        state=self.updater.status();self.assertEqual(state['status'],'error');self.assertIn('Fixture offline',state['error']);self.assertGreater(state['next_check'],0)

    def test_worker_boundary_defers_and_disabled_never_installs(self):
        self.updater.portable=True;self.updater.save(status='ready',available='1.7.0',payload=str(self.root/'.updates/1.7.0/payload'))
        with patch('subprocess.Popen') as launch:
            self.worker.cycle_lock.acquire()
            try:self.assertFalse(self.updater.apply_ready())
            finally:self.worker.cycle_lock.release()
            self.assertTrue(self.worker.maintenance.is_set());self.assertFalse(self.worker.stop.is_set());launch.assert_not_called()
            self.worker.maintenance.clear();self.updater.configure({'enabled':False});self.assertFalse(self.updater.apply_ready());launch.assert_not_called()

    def test_replace_and_rollback_preserve_user_data(self):
        _,_,manifest,files=package(self.root);payload=self.root/'.updates/payload';payload.mkdir(parents=True)
        for name,raw in files.items():p=payload/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        (payload/'MANIFEST.json').write_text(json.dumps(manifest));(self.root/'app.py').write_bytes(b'old app')
        (self.root/'Exports').mkdir();(self.root/'Exports/saved.zip').write_bytes(b'private export')
        before=(self.root/'Data/archive.sqlite3').read_bytes();backup=self.root/'.updates/backups/test'
        journal=replace_payload(self.root,payload,backup)
        self.assertEqual((self.root/'app.py').read_bytes(),b'new app')
        rollback(self.root,backup,journal)
        self.assertEqual((self.root/'app.py').read_bytes(),b'old app');self.assertFalse((self.root/'runtime/python.exe').exists())
        self.assertEqual((self.root/'Exports/saved.zip').read_bytes(),b'private export');self.assertEqual((self.root/'Data/archive.sqlite3').read_bytes(),before)

    def test_failed_startup_restores_previous_payload(self):
        _,_,manifest,files=package(self.root);payload=self.root/'.updates/payload';payload.mkdir(parents=True)
        for name,raw in files.items():p=payload/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        (payload/'MANIFEST.json').write_text(json.dumps(manifest));(self.root/'app.py').write_bytes(b'old app')
        job=self.root/'.updates/install.json';job.write_text(json.dumps({'target':str(self.root),'payload':str(payload),'backup':str(self.root/'.updates/backups/failure'),'parent_pid':123,'data':str(self.root/'Data'),'port':54321,'version':'1.7.0'}))
        process=Mock();process.poll.return_value=1
        with patch('studio.update_installer.wait_parent'),patch('studio.update_installer.launch',return_value=process) as launch,patch('studio.update_installer.healthy',return_value=False):
            self.assertFalse(install(job));self.assertEqual(launch.call_count,2)
        self.assertEqual((self.root/'app.py').read_bytes(),b'old app');self.assertEqual(json.loads(job.with_suffix('.result.json').read_text())['status'],'rolled-back')

    def test_newer_cursor_returns_adjacent_messages_without_duplicates(self):
        self.store.catalog([{'id':'10','name':'Fixture'}],[{'id':'11','name':'chat','type':0}],'10')
        self.store.upsert('11',[{'id':str(i),'channel_id':'11','author':{'id':'7','username':'Fixture'},'timestamp':'2026-10-15T00:00:00Z','content':str(i)} for i in range(1,21)])
        head=self.store.search(channel='11',limit=5)['messages'];older=self.store.search(channel='11',limit=5,cursor=head[-1]['_cursor'])['messages']
        newer=self.store.search(channel='11',limit=5,cursor=older[0]['_cursor'],newer=True)['messages']
        self.assertEqual([m['id'] for m in newer],[m['id'] for m in head]);self.assertFalse(set(m['id'] for m in older)&set(m['id'] for m in newer))

    def test_failed_receipt_is_visible_after_restart(self):
        job=self.root/'.updates/install.json';job.parent.mkdir();job.write_text('{}')
        job.with_suffix('.result.json').write_text(json.dumps({'status':'rolled-back','error':'Fixture startup failed'}))
        self.updater.save(status='installing',available='1.7.0',install_job=str(job))
        restored=Updater(self.store,self.root,self.worker,self.server)
        self.assertEqual(restored.status()['status'],'error');self.assertIn('rolled back',restored.status()['error'])
        self.assertEqual(self.store.setting('application_update_state')['rejected_version'],'1.7.0')


if __name__=='__main__':unittest.main()
