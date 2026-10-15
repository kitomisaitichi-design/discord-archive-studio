"""Bounded public release checks and checkpoint-safe portable updates."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile

CURRENT_VERSION = '1.7.0'
REPOSITORY = 'kitomisaitichi-design/discord-archive-studio'
LATEST = 'https://api.github.com/repos/'+REPOSITORY+'/releases/latest'
MAX_DOWNLOAD = 150*1024*1024
ROOT_FILES = {'app.py','MANIFEST.json','README.txt','ARCHITECTURE.md','VALIDATION.md',
              'THIRD-PARTY-NOTICES.txt','OPEN-DISCORD-ARCHIVE.vbs','OPEN-DISCORD-ARCHIVE.bat','CLOSE-ARCHIVE-SERVICE.bat'}
ROOT_DIRS = {'studio','web','runtime','tools','browser-connector','licenses'}


def version(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(value))
    if not match: raise ValueError('Unrecognized stable release version.')
    return tuple(map(int, match.groups()))


def safe_name(value):
    name = str(value)
    path = PurePosixPath(name)
    if not name or '\\' in name or path.is_absolute() or name != path.as_posix():
        raise ValueError('Unsafe update path.')
    for part in path.parts:
        if part in ('.','..') or part.endswith((' ','.')) or re.search(r'[<>:"|?*\x00-\x1f]',part) or re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',part):
            raise ValueError('Unsafe update path.')
    if (len(path.parts)==1 and name not in ROOT_FILES) or (len(path.parts)>1 and path.parts[0] not in ROOT_DIRS):
        raise ValueError('An update attempted to replace user data.')
    return path


def validate_package(archive, expected_version, digest):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',str(digest)):
        raise ValueError('The release has no verifiable SHA-256 digest.')
    with Path(archive).open('rb') as stream:
        if 'sha256:'+hashlib.file_digest(stream,'sha256').hexdigest()!=digest:
            raise ValueError('The downloaded update checksum did not match.')
    with zipfile.ZipFile(archive) as package:
        entries=[i for i in package.infolist() if not i.is_dir()]
        if not entries or len(entries)>5000 or sum(i.file_size for i in entries)>500*1024*1024:
            raise ValueError('Update package exceeds its size limit.')
        prefix=entries[0].filename.split('/')[0]
        if not re.fullmatch(r'Discord-Archive-Studio-v\d+\.\d+\.\d+-Portable',prefix):
            raise ValueError('Not a portable application package.')
        names={};seen=set()
        for info in entries:
            if not info.filename.startswith(prefix+'/') or stat.S_ISLNK(info.external_attr>>16) or info.file_size>80*1024*1024:
                raise ValueError('Invalid update entry.')
            relative=info.filename[len(prefix)+1:];safe_name(relative)
            if relative.casefold() in seen: raise ValueError('Duplicate update entry.')
            seen.add(relative.casefold());names[relative]=info
        if 'MANIFEST.json' not in names or names['MANIFEST.json'].file_size>2*1024*1024:
            raise ValueError('Update manifest is missing or too large.')
        manifest=json.loads(package.read(names['MANIFEST.json']))
        if manifest.get('app')!='Discord Archive Studio' or manifest.get('version')!=expected_version:
            raise ValueError('Update manifest does not match the release.')
        records=manifest.get('files',{})
        if not isinstance(records,dict) or set(records)!=(set(names)-{'MANIFEST.json'}):
            raise ValueError('Update manifest has missing or extra files.')
        if not {'app.py','studio/server.py','studio/update_installer.py','runtime/python.exe','runtime/pythonw.exe'}<=set(records):
            raise ValueError('Update is missing required application files.')
        for relative,record in records.items():
            safe_name(relative)
            raw=package.read(names[relative])
            if len(raw)!=record.get('bytes') or hashlib.sha256(raw).hexdigest()!=record.get('sha256'):
                raise ValueError('Update file failed verification: '+relative)
        return manifest,prefix


class Updater:
    def __init__(self, store, root, worker, server):
        self.store,self.root,self.worker,self.server=store,Path(root).resolve(),worker,server
        self.stop=threading.Event();self.wake=threading.Event();self.lock=threading.RLock()
        self.busy=False;self.installing=False;self.restart_no_connect=False
        self.portable=(self.root/'MANIFEST.json').is_file() and (self.root/'runtime/pythonw.exe').is_file()
        previous=self.store.setting('application_update_state',{})
        if previous.get('install_job'):
            try:
                job=(self.root/previous['install_job']).resolve();job.relative_to(self.root/'.updates')
                result=json.loads(job.with_suffix('.result.json').read_text(encoding='utf-8'))
                if result.get('status')=='rolled-back':
                    self.save(status='error',error='Update rolled back: '+result.get('error','startup failed'),
                              rejected_version=previous.get('available',''),payload='',available='',
                              next_check=time.time()+self.settings()['minutes']*60,install_job='')
                elif result.get('status')=='complete' and result.get('version')==CURRENT_VERSION:
                    self.save(status='current',available='',payload='',error='',install_job='')
            except (OSError,ValueError):pass

    def settings(self):
        return dict({'enabled':True,'minutes':1440},**self.store.setting('application_updates',{}))

    def status(self):
        saved=self.store.setting('application_update_state',{})
        return {**{k:v for k,v in saved.items() if k not in ('release','etag','payload')},
                **self.settings(),'current':CURRENT_VERSION,'portable':self.portable,'busy':self.busy}

    def save(self, **values):
        state=self.store.setting('application_update_state',{});state.update(values)
        self.store.set_setting('application_update_state',state)

    def configure(self, data):
        with self.lock:
            if self.installing: raise ValueError('The update is already restarting the app.')
            prefs=self.settings()
            if 'enabled' in data:
                if not isinstance(data['enabled'],bool): raise ValueError('Update toggle must be true or false.')
                prefs['enabled']=data['enabled']
            if 'minutes' in data:
                minutes=int(data['minutes'])
                if not 15<=minutes<=10080: raise ValueError('Choose 15 minutes to 7 days.')
                prefs['minutes']=minutes
            self.store.set_setting('application_updates',prefs)
            last=self.store.setting('application_update_state',{}).get('last_check',0)
            self.save(next_check=max(time.time(),last+prefs['minutes']*60))
            self.wake.set()
        return self.status()

    def start(self):
        threading.Thread(target=self.run,daemon=True,name='application-updates').start()

    def request_check(self):
        with self.lock:
            if self.busy or self.installing: return self.status()
            self.busy=True
        threading.Thread(target=self.check,daemon=True,name='release-check').start()
        return self.status()

    def check(self):
        try:
            saved=self.store.setting('application_update_state',{})
            self.save(status='checking',error='')
            headers={'Accept':'application/vnd.github+json','User-Agent':'Discord-Archive-Studio/'+CURRENT_VERSION}
            if saved.get('etag'):headers['If-None-Match']=saved['etag']
            try:
                with urllib.request.urlopen(urllib.request.Request(LATEST,headers=headers),timeout=20) as response:
                    raw=response.read(2*1024*1024+1)
                    if len(raw)>2*1024*1024:raise ValueError('Release metadata is too large.')
                    release=json.loads(raw);etag=response.headers.get('ETag','')
            except urllib.error.HTTPError as error:
                if error.code!=304:raise
                release=saved.get('release',{});etag=saved.get('etag','')
            tag=release.get('tag_name','');parsed=version(tag)
            if release.get('draft') or release.get('prerelease'):raise ValueError('Only published stable releases are installed.')
            now=time.time();self.save(last_check=now,next_check=now+self.settings()['minutes']*60,failures=0,error='',etag=etag,release=release)
            if parsed<=version(CURRENT_VERSION):
                self.save(status='current',available='',payload='');return
            target='.'.join(map(str,parsed));name='Discord-Archive-Studio-v'+target+'-Portable.zip'
            if saved.get('rejected_version')==target:raise ValueError('This release was rolled back. Waiting for a newer stable release.')
            asset=next((a for a in release.get('assets',[]) if a.get('name')==name and a.get('state')=='uploaded'),None)
            if not asset:raise ValueError('The stable release has no Windows portable package.')
            expected='https://github.com/'+REPOSITORY+'/releases/download/'+tag+'/'+name
            if asset.get('browser_download_url')!=expected or not 0<int(asset.get('size',0))<=MAX_DOWNLOAD:
                raise ValueError('Update asset is outside the configured repository or size limit.')
            self.save(available=target,status='available')
            if not self.portable:return
            existing=saved.get('payload','')
            if saved.get('available')==target and existing and (self.root/existing).is_dir():
                self.save(payload=existing,status='ready');return
            stage=self.root/'.updates'/target;stage.mkdir(parents=True,exist_ok=True)
            archive=stage/name;temporary=stage/(name+'.part');self.save(status='downloading')
            with urllib.request.urlopen(urllib.request.Request(expected,headers={'User-Agent':headers['User-Agent']}),timeout=30) as response,temporary.open('wb') as stream:
                length=0
                while True:
                    block=response.read(256*1024)
                    if not block:break
                    length+=len(block)
                    if length>int(asset['size']) or length>MAX_DOWNLOAD:raise ValueError('Update download exceeded its declared size.')
                    if self.stop.is_set():raise RuntimeError('Update check stopped.')
                    stream.write(block)
            if length!=int(asset['size']):raise ValueError('Update download was incomplete.')
            temporary.replace(archive)
            manifest,prefix=validate_package(archive,target,asset.get('digest'))
            payload=stage/'payload';payload.mkdir(exist_ok=True)
            with zipfile.ZipFile(archive) as package:
                for relative in [*manifest['files'],'MANIFEST.json']:
                    destination=payload/relative;destination.parent.mkdir(parents=True,exist_ok=True)
                    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in [destination,*destination.parents] if p!=self.root.parent):raise ValueError('Update staging path is linked.')
                    destination.write_bytes(package.read(prefix+'/'+relative))
            self.save(payload=payload.relative_to(self.root).as_posix(),status='ready')
        except Exception as error:
            failures=min(8,int(self.store.setting('application_update_state',{}).get('failures',0))+1)
            retry=max(900,min(86400,300*2**failures))
            if isinstance(error,urllib.error.HTTPError):
                try:retry=max(retry,min(86400,int(error.headers.get('Retry-After',0))))
                except (TypeError,ValueError):pass
            self.save(status='error',error=str(error)[:300],failures=failures,next_check=time.time()+max(retry,self.settings()['minutes']*60))
        finally:
            self.busy=False
            self.wake.set()

    def apply_ready(self):
        with self.lock:
            saved=self.store.setting('application_update_state',{})
            if self.installing or not self.settings()['enabled'] or saved.get('status')!='ready' or not self.portable:return False
            self.worker.maintenance.set()
            if not self.worker.cycle_lock.acquire(blocking=False):return False
            try:
                if self.store.processing_job or any(j['status']=='running' for j in self.store.jobs()):return False
                payload=(self.root/saved['payload']).resolve();payload.relative_to(self.root/'.updates')
                if version(saved['available'])<=version(CURRENT_VERSION):return False
                job=self.root/'.updates'/('install-'+saved['available']+'.json')
                config={'target':str(self.root),'payload':str(payload),'backup':str(self.root/'.updates/backups'/str(time.time_ns())),
                        'data':str(self.store.root.resolve()),'port':self.server.server_port,'parent_pid':os.getpid(),
                        'version':saved['available'],'previous':CURRENT_VERSION,'no_connect':self.restart_no_connect}
                job.write_text(json.dumps(config),encoding='utf-8')
                self.save(status='installing',install_job=job.relative_to(self.root).as_posix());self.installing=True
                subprocess.Popen([str(payload/'runtime/pythonw.exe'),str(payload/'studio/update_installer.py'),str(job)],cwd=payload,
                                 creationflags=0x08000000 if os.name=='nt' else 0)
                self.worker.stop.set();self.worker.signal()
                self.server.connection.stop.set();self.server.connection.reconnect.set()
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return True
            except Exception as error:
                self.installing=False;self.save(status='error',error=str(error)[:300]);return False
            finally:
                self.worker.cycle_lock.release()
                if not self.installing:self.worker.maintenance.clear()

    def run(self):
        self.stop.wait(10)
        while not self.stop.is_set():
            settings=self.settings();saved=self.store.setting('application_update_state',{})
            if settings['enabled']:
                if saved.get('status')=='ready':self.apply_ready()
                elif not self.busy and time.time()>=saved.get('next_check',0):self.request_check()
            elif self.worker.maintenance.is_set() and not self.installing:self.worker.maintenance.clear()
            self.wake.wait(2 if saved.get('status')=='ready' else 60);self.wake.clear()
