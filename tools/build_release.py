"""Build a portable, standard-library Windows release; preserve earlier outputs."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--python-runtime',type=Path,default=Path(sys.executable).parent)
parser.add_argument('--version',default='1.3.3')
args=parser.parse_args()
runtime=args.python_runtime.resolve()
out=(ROOT/'outputs').resolve()
if out.parent!=ROOT.resolve():raise RuntimeError('Outputs resolves outside this project.')
out.mkdir(exist_ok=True)
base='Discord-Archive-Studio-v'+args.version
package=out/(base+'-Portable')
portable_zip=out/(base+'-Portable.zip')
source_zip=out/(base+'-Source.zip')
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
backup=ROOT/'.work'/'build-backups'/stamp
for existing in (package,portable_zip,source_zip):
    if existing.exists():
        if existing.resolve().parent!=out:raise RuntimeError('Refusing to move an output outside the verified outputs directory.')
        backup.mkdir(parents=True,exist_ok=True)
        existing.rename(backup/existing.name)
package.mkdir()

files=['app.py','README.txt','ARCHITECTURE.md','VALIDATION.md','THIRD-PARTY-NOTICES.txt','OPEN-DISCORD-ARCHIVE.vbs','OPEN-DISCORD-ARCHIVE.bat','CLOSE-ARCHIVE-SERVICE.bat']
for name in files:
    path=ROOT/name
    if not path.is_file():raise RuntimeError('Required release document missing: '+name)
    shutil.copy2(path,package/name)
for directory in ('studio','web','browser-connector','licenses'):
    for source in (ROOT/directory).rglob('*'):
        if source.is_file() and '__pycache__' not in source.parts and source.suffix!='.pyc':
            target=package/source.relative_to(ROOT)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
(package/'tools').mkdir()
shutil.copy2(ROOT/'tools'/'stop_service.py',package/'tools'/'stop_service.py')

dest_runtime=package/'runtime';dest_runtime.mkdir()
for name in ('python.exe','pythonw.exe','python3.dll','python312.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
    if not (runtime/name).is_file():raise RuntimeError('Missing runtime payload: '+name)
    shutil.copy2(runtime/name,dest_runtime/name)
for source in (runtime/'DLLs').iterdir():
    if source.suffix in ('.pyd','.dll') and not source.name.startswith(('_test','_ctypes_test')) and source.name not in ('_tkinter.pyd','tcl86t.dll','tk86t.dll'):
        shutil.copy2(source,dest_runtime/source.name)
exclude={'site-packages','__pycache__','test','tests','idlelib','tkinter','turtledemo','ensurepip','venv'}
with zipfile.ZipFile(dest_runtime/'python312.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for source in (runtime/'Lib').rglob('*'):
        relative=source.relative_to(runtime/'Lib')
        if source.is_file() and not (set(relative.parts)&exclude) and source.suffix not in ('.pyc','.pyo'):
            archive.write(source,relative.as_posix())
(dest_runtime/'python312._pth').write_text('python312.zip\n.\n..\nimport site\n',encoding='utf-8')
check=subprocess.run([str(dest_runtime/'python.exe'),'-c',"import ssl,sqlite3,ctypes; from studio.store import Store; from studio.credentials import dpapi; assert dpapi(dpapi(b'check',True))==b'check'; d=sqlite3.connect(':memory:');d.execute('CREATE VIRTUAL TABLE f USING fts5(text)');print('Portable imports including SSL module, SQLite FTS5 and DPAPI passed')"],cwd=package,capture_output=True,text=True,timeout=30)
if check.returncode:raise RuntimeError(check.stderr or check.stdout)
print(check.stdout.strip())

manifest={}
for source in package.rglob('*'):
    if source.is_file() and '__pycache__' not in source.parts:
        with source.open('rb') as stream:manifest[source.relative_to(package).as_posix()]={'bytes':source.stat().st_size,'sha256':hashlib.file_digest(stream,'sha256').hexdigest()}
(package/'MANIFEST.json').write_text(json.dumps({'app':'Discord Archive Studio','version':args.version,'files':manifest},indent=2),encoding='utf-8')
with zipfile.ZipFile(portable_zip,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as archive:
    for source in package.rglob('*'):
        if source.is_file() and '__pycache__' not in source.parts:archive.write(source,(Path(package.name)/source.relative_to(package)).as_posix())
source_names=files+['tools/build_release.py','tools/benchmark.py','tools/stop_service.py','LESSONS-1.md','LESSONS-2.md','LESSONS-3.md','LESSONS-4.md','LESSONS-5.md','LESSONS-6.md','LESSONS-7.md']
with zipfile.ZipFile(source_zip,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for name in source_names:archive.write(ROOT/name,(Path(base+'-Source')/name).as_posix())
    for directory in ('studio','web','browser-connector','licenses','tests'):
        for source in (ROOT/directory).rglob('*'):
            if source.is_file() and '__pycache__' not in source.parts and source.suffix!='.pyc':archive.write(source,(Path(base+'-Source')/source.relative_to(ROOT)).as_posix())
for artifact in (portable_zip,source_zip):
    with zipfile.ZipFile(artifact) as archive:
        if archive.testzip():raise RuntimeError('Artifact CRC verification failed.')
        forbidden=[n for n in archive.namelist() if any(p in ('Data','.work','outputs','Recovery','Logs','__pycache__') for p in Path(n).parts) or n.endswith(('.dpapi','.sqlite3','.sqlite3-wal','.sqlite3-shm'))]
        if forbidden:raise RuntimeError('Private/development payload entered the package: '+str(forbidden))
    with artifact.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    print(json.dumps({'artifact':artifact.name,'bytes':artifact.stat().st_size,'sha256':digest,'crc':'passed','private_data':'excluded'}))
