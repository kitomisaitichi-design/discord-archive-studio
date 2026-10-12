"""One running service per library, conflict-free loopback binding and local launch metadata."""
import errno
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request


def library_identity(root):
    return hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode('utf-8')).hexdigest()


class LibraryLock:
    def __init__(self,root):
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.stream=None
        self.acquired=False

    def __enter__(self):
        self.stream=(self.root/'.service.lock').open('a+b')
        self.stream.seek(0,2)
        if self.stream.tell()==0:
            self.stream.write(b'0');self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.acquired=True
        except OSError:
            self.acquired=False
        return self

    def __exit__(self,*unused):
        if self.acquired:
            self.stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
        self.stream.close()


def running_port(root,wait_seconds=6):
    deadline=time.monotonic()+wait_seconds
    while True:
        try:
            info=json.loads((Path(root)/'service.json').read_text(encoding='utf-8'))
            port=int(info['port'])
            if not 1024<=port<=65535:
                raise ValueError('Invalid saved port.')
            with urllib.request.urlopen('http://127.0.0.1:%s/api/health'%port,timeout=.5) as response:
                health=json.load(response)
            if health.get('app')=='Discord Archive Studio' and health.get('library_id')==library_identity(root):
                return port
        except (OSError,ValueError,KeyError):
            pass
        if time.monotonic()>=deadline:
            raise RuntimeError('Another copy is starting or still stopping. Wait a few seconds, then open the launcher again.')
        time.sleep(.2)


def preferred_port(root,default=8765):
    try:
        info=json.loads((Path(root)/'service.json').read_text(encoding='utf-8'))
        port=int(info['port'])
        if 1024<=port<=65535 and info.get('library_id')==library_identity(root):return port
    except (OSError,ValueError,KeyError,TypeError):pass
    return default


def bind_server(factory,requested=None,preferred=8765):
    ports=[requested] if requested is not None else [*range(preferred,min(preferred+21,65536)),0]
    last=None
    for port in ports:
        try:
            return factory(('127.0.0.1',port))
        except OSError as error:
            last=error
            if requested is not None or (error.errno not in (errno.EADDRINUSE,errno.EACCES,10013,10048) and getattr(error,'winerror',None) not in (10013,10048)):
                raise
    raise RuntimeError('No local port could be opened: '+str(last))


def save_address(root,port):
    root=Path(root)
    info={'port':port,'library_id':library_identity(root),'pid':os.getpid(),'url':'http://127.0.0.1:%s/'%port}
    temp=root/'service.json.tmp'
    temp.write_text(json.dumps(info),encoding='utf-8')
    os.replace(temp,root/'service.json')
    (root/'OPEN-ARCHIVE-UI.url').write_text('[InternetShortcut]\nURL='+info['url']+'\n',encoding='utf-8')
