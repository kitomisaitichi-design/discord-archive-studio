"""Run from the verified staged runtime, after the original service exits."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request


def atomic_json(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(path)


def wait_parent(pid,timeout=120):
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x100000,False,pid)
        if not handle:
            if ctypes.get_last_error()==87:return
            raise OSError('Cannot wait for the previous app process.')
        try:
            if kernel.WaitForSingleObject(handle,int(timeout*1000))!=0:raise TimeoutError('Previous app did not exit; files were left unchanged.')
        finally:kernel.CloseHandle(handle)
    else:
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:os.kill(pid,0)
            except ProcessLookupError:return
            time.sleep(.2)
        raise TimeoutError('Previous app did not exit.')


def replace_payload(target,payload,backup):
    # Import only the verified helper module from the staged package.
    sys.path.insert(0,str(payload));from studio.updates import safe_name
    manifest=json.loads((payload/'MANIFEST.json').read_text(encoding='utf-8'))
    names=[*manifest['files'],'MANIFEST.json'];journal=[];backup.mkdir(parents=True,exist_ok=True)
    for name,record in manifest['files'].items():
        safe_name(name);source=payload/name
        if source.stat().st_size!=record['bytes'] or hashlib.sha256(source.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Staged payload changed: '+name)
    for name in names:
        safe_name(name);destination=target/name
        for parent in [destination,*destination.parents]:
            if parent==target.parent:break
            if parent.is_symlink() or getattr(parent,'is_junction',lambda:False)():raise ValueError('Linked installation paths are not replaced.')
    try:
        for name in names:
            destination=target/name;old=backup/name;existed=destination.is_file()
            if existed:old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(destination,old)
            journal.append((name,existed));destination.parent.mkdir(parents=True,exist_ok=True)
            temporary=destination.with_name(destination.name+'.updating');shutil.copy2(payload/name,temporary);temporary.replace(destination)
        return journal
    except Exception:
        rollback(target,backup,journal);raise


def rollback(target,backup,journal):
    for name,existed in reversed(journal):
        destination=target/name
        if existed:
            temporary=destination.with_name(destination.name+'.restoring');shutil.copy2(backup/name,temporary);temporary.replace(destination)
        elif destination.is_file():destination.unlink()


def launch(config,receipt=None):
    target=Path(config['target'])
    command=[str(target/'runtime/pythonw.exe'),str(target/'app.py'),'--data',config['data'],'--port',str(config['port']),'--no-browser','--reuse-window']
    if config.get('no_connect'):command.append('--no-connect')
    if receipt:command+=['--update-receipt',str(receipt)]
    return subprocess.Popen(command,cwd=target,creationflags=0x08000000 if os.name=='nt' else 0)


def healthy(config,expected,process,timeout=45):
    identity=hashlib.sha256(os.path.normcase(str(Path(config['data']).resolve())).encode()).hexdigest()
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline and process.poll() is None:
        try:
            with urllib.request.urlopen('http://127.0.0.1:%s/api/health'%config['port'],timeout=.5) as response:value=json.load(response)
            if value.get('app')=='Discord Archive Studio' and value.get('version')==expected and value.get('library_id')==identity:return True
        except (OSError,ValueError):pass
        time.sleep(.2)
    return False


def install(job):
    job=Path(job).resolve();config=json.loads(job.read_text(encoding='utf-8'))
    target=Path(config['target']).resolve();payload=Path(config['payload']).resolve();backup=Path(config['backup']).resolve()
    job.relative_to(target/'.updates');payload.relative_to(target/'.updates');backup.relative_to(target/'.updates/backups')
    result=job.with_suffix('.result.json');journal=[];process=None;parent_exited=False
    try:
        wait_parent(int(config['parent_pid']))
        parent_exited=True
        journal=replace_payload(target,payload,backup)
        process=launch(config,job)
        if not healthy(config,config['version'],process):raise RuntimeError('Updated app did not pass its startup check.')
        atomic_json(result,{'status':'complete','version':config['version'],'time':time.time()})
        return True
    except Exception as error:
        if process and process.poll() is None:process.terminate();process.wait(timeout=15)
        if journal:rollback(target,backup,journal)
        atomic_json(result,{'status':'rolled-back','error':str(error)[:500],'time':time.time()})
        # Never launch a competing service if the original process failed to exit.
        if parent_exited:launch(config)
        return False


if __name__=='__main__':
    raise SystemExit(0 if install(sys.argv[1]) else 1)
