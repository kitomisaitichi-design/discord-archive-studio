"""Local-only, paged ZIP reader. Never execute or extract archived documents."""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from .importing import parse_json, parse_txt, DceHTML, synthetic
from .store import packed
from . import reader_library
from .emojis import Emojis,references


MAX_ENTRY = 128 * 1024 * 1024
MAX_TEXT = 512 * 1024 * 1024


def safe_entry(name):
    p = PurePosixPath(name)
    return bool(name and not p.is_absolute() and '\\' not in name and ':' not in name and '..' not in p.parts)


class StudioHTML(DceHTML):
    """Read Studio's old HTML-only exports without constructing an executable DOM."""
    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        super().handle_starttag(tag, attrs)
        if tag == 'article' and re.fullmatch(r'm\d+', attr.get('id', '')):
            mid = attr['id'][1:]
            self.message = {'id': mid, 'author': {'id': synthetic('html-author:Unknown'), 'username': 'Unknown'},
                            'timestamp': '', 'content': '', 'attachments': []}
            self.message_depth = len(self.stack)
            self.body = []
        if self.message and tag == 'b' and any(t == 'header' for t, _ in self.stack):
            self.author_depth = len(self.stack)
            self.author_text = []
        if self.message and tag == 'time':
            self.time_depth, self.time_text = len(self.stack), []
        if self.message and attr.get('class') == 'content':
            self.text_depth = len(self.stack)

    def handle_data(self, data):
        super().handle_data(data)
        if getattr(self, 'time_depth', None):
            self.time_text.append(data)

    def handle_endtag(self, tag):
        if self.message and tag == 'b' and self.author_depth:
            name = ''.join(self.author_text).strip() or 'Unknown'
            self.message['author'] = {'id': synthetic('html-author:'+name), 'username': name}
        if self.message and tag == 'time' and getattr(self, 'time_depth', None):
            self.message['timestamp'] = ''.join(self.time_text).strip()
            self.time_depth = None
        super().handle_endtag(tag)


def parse_studio_text(text, cid, name):
    messages, current, lines = [], None, []
    def flush():
        if current:
            current['content'] = '\n'.join(lines).strip()
            messages.append(current.copy())
    for line in text.splitlines():
        match = re.match(r'^(?:### |\[)(.*?) · (\d{4}-\d\d-\d\d[^·]*?) · (\d+)\]?$', line)
        if match:
            flush()
            current = {'id': match[3], 'author': {'id': synthetic('text-author:'+match[1]), 'username': match[1]},
                       'timestamp': match[2].strip(), 'channel_id': cid, 'content': ''}
            lines = []
        elif current:
            lines.append(line)
    flush()
    if not messages:
        return parse_txt(text, name)
    return {'id': '0', 'name': 'Text archive'}, {'id': cid, 'name': name}, messages


class ZipReader:
    def __init__(self, store, app_root=None, scan_parent=True):
        self.store = store
        self.emojis = Emojis(store)
        self.root = store.root / 'reader-cache'
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.known = {}
        self.app_root = Path(app_root) if app_root else store.root.parent
        self.scan_parent = scan_parent
        self.discovery = []
        self.discovery_roots = None
        self.discovery_until = 0
        self.discovery_warnings = []

    @staticmethod
    def _looks_like_discord_document(prefix,kind):
        if kind=='.json':
            return bool(re.search(rb'"messages"\s*:\s*\[',prefix) and b'"channel"' in prefix)
        if kind in ('.html','.htm'):
            return b'chatlog__message-container' in prefix or bool(re.search(rb'<article\s+id="m\d+',prefix))
        if kind in ('.md','.txt'):
            return bool(re.search(rb'^(?:### |\[).*?\xc2\xb7 \d{4}-\d\d-\d\d',prefix,re.M)
                        or re.search(rb'^\[\d{1,2}/\d{1,2}/\d{4} .*?[AP]M\]',prefix,re.M))
        return False

    def discover(self, refresh=False):
        app=self.app_root.resolve()
        roots=[Path(self.store.setting('destination',str(self.store.root.parent/'Exports'))).expanduser(),app]
        if self.scan_parent:
            # Check the original portable folder and SEVEN ancestor levels. This
            # survives moved installs, downloads and exports saved beside older
            # copies. Never make a second SQLite library or copy a discovered ZIP.
            parent=app
            for _ in range(7):
                if parent.parent == parent: break
                parent=parent.parent
                roots.append(parent)
        roots=list(dict.fromkeys(Path(p).resolve() for p in roots))
        signature=tuple(os.path.normcase(str(p)) for p in roots)
        with self.lock:
            if not refresh and signature==self.discovery_roots and time.monotonic()<self.discovery_until:
                return list(self.discovery)
            found,seen,warnings=[],set(),[]
            skip={'data','runtime','.git','.work','.updates','recovery','logs','__pycache__',
                  'node_modules','reader-cache','reader-archives','.venv','venv','site-packages',
                  'appdata','windows','program files','program files (x86)','$recycle.bin',
                  'system volume information','packages','.cache'}
            visited=0
            def scan_error(error):warnings.append('Folder unavailable: '+str(error.filename))
            for root in roots:
                if not root.is_dir():continue
                for base,dirs,files in os.walk(root,followlinks=False,onerror=scan_error):
                    path=Path(base);normalized=os.path.normcase(str(path.resolve()))
                    if normalized in seen:dirs[:]=[];continue
                    seen.add(normalized);visited+=1
                    if visited>5000:
                        warnings.append('Discovery reached its 5,000-folder limit.');dirs[:]=[];break
                    # Descend recursively rather than stopping after six levels.
                    # Cycles, junctions and giant system/dependency directories
                    # are excluded; the global 5,000-directory cap still applies.
                    dirs[:]=sorted(d for d in dirs if d.casefold() not in skip and not (path/d).is_symlink() and not getattr(path/d,'is_junction',lambda:False)())
                    # On Windows the seventh ancestor can be C:\ itself. Treat
                    # system/profile roots as direct-file lookups rather than
                    # crawling an entire volume or unrelated app credentials.
                    if path==root and (path==Path(path.anchor) or path.name.casefold() in {'users','appdata'}):
                        dirs[:]=[]
                    if path==root and path==Path.home():
                        dirs[:]=[d for d in dirs if d.casefold() in {'downloads','desktop','documents'}]
                    for name in sorted(files):
                        kind=Path(name).suffix.lower()
                        if kind not in ('.zip','.json','.html','.htm','.md','.txt') or re.match(r'Discord-Archive-Studio-v\d',name,re.I):continue
                        candidate=path/name
                        if candidate.is_symlink():continue
                        try:
                            stat=candidate.stat()
                            if getattr(stat,'st_file_attributes',0)&(0x1000|0x40000|0x400000):
                                warnings.append('Online-only archive skipped until available locally: '+name);continue
                            title=None
                            if kind=='.zip':
                                with zipfile.ZipFile(candidate) as archive:
                                    names=archive.namelist()
                                    if len(names)>10000:continue
                                    if 'manifest.json' in names and archive.getinfo('manifest.json').file_size<=262144:
                                        manifest=json.loads(archive.read('manifest.json'))
                                        if isinstance(manifest,dict) and str(manifest.get('schema','')).startswith('discord-archive-studio/'):
                                            title=manifest.get('server_name') or name
                                    if not title:
                                        for entry in archive.infolist():
                                            if entry.filename.lower().endswith(('.json','.html','.htm','.md','.txt')) and entry.file_size<=MAX_ENTRY:
                                                with archive.open(entry) as source:prefix=source.read(65536)
                                                if self._looks_like_discord_document(prefix,Path(entry.filename).suffix.lower()):
                                                    title=name;break
                            elif 0 < stat.st_size <= MAX_ENTRY:
                                # Detect loose DiscordChatExporter/Studio exports in
                                # place, WITHOUT importing or copying the file.
                                with candidate.open('rb') as source:prefix=source.read(65536)
                                if self._looks_like_discord_document(prefix,kind):title=name
                            if title:
                                found.append({'path':str(candidate.resolve()),'name':str(title),'source':'discovered','size':stat.st_size,'updated':stat.st_mtime,'folder':str(path)})
                            if len(found)>=1000:break
                        except (OSError,ValueError,zipfile.BadZipFile,RuntimeError,json.JSONDecodeError):
                            warnings.append('Not a readable Discord archive: '+name)
                    if len(found)>=1000:break
                if visited>5000 or len(found)>=1000:break
            self.discovery,self.discovery_roots,self.discovery_until=found,signature,time.monotonic()+60
            self.discovery_warnings=warnings[:10]
            return list(found)

    def catalogue(self, refresh=False):
        with self.store.db() as db:
            pubs = [dict(r) for r in db.execute('SELECT server_id,path,updated,size FROM publications')]
            names = {r['id']: r['name'] for r in db.execute('SELECT id,name FROM servers')}
        entries = [dict(p, name=names.get(p['server_id'], p['server_id']), source='export') for p in pubs]
        entries += self.store.setting('reader_archives', [])
        entries += self.discover(refresh)
        dedup={}
        for entry in entries:
            entry['id'] = hashlib.sha256(str(Path(entry['path']).resolve()).encode()).hexdigest()
            entry['available'] = Path(entry['path']).is_file()
            dedup.setdefault(os.path.normcase(str(Path(entry['path']).resolve())),entry)
        return reader_library.entries(self.store)+list(dedup.values())

    def upload(self, content, filename):
        if not filename.lower().endswith('.zip'):
            raise ValueError('Choose a ZIP archive.')
        digest = hashlib.sha256(content).hexdigest()
        folder = self.store.root / 'reader-archives'
        folder.mkdir(exist_ok=True)
        path = folder / (digest+'.zip')
        with self.lock:
            if not path.exists():
                with zipfile.ZipFile(__import__('io').BytesIO(content)) as archive:
                    self.validate(archive)
                handle, temp = tempfile.mkstemp(dir=folder, suffix='.partial')
                try:
                    with os.fdopen(handle, 'wb') as output:
                        output.write(content)
                    os.replace(temp, path)
                finally:
                    Path(temp).unlink(missing_ok=True)
            entries = self.store.setting('reader_archives', [])
            if not any(e['path'] == str(path) for e in entries):
                if len(entries) >= 100:
                    raise ValueError('The reader catalogue supports 100 opened ZIPs.')
                entries.append({'path': str(path), 'name': Path(filename).name[:200], 'source': 'opened', 'size': len(content)})
                self.store.set_setting('reader_archives', entries)
        return next(e for e in self.catalogue() if e['path'] == str(path))

    @staticmethod
    def validate(archive):
        infos = archive.infolist()
        if len(infos) > 10000 or any(not safe_entry(i.filename) or not safe_entry(i.orig_filename) for i in infos):
            raise ValueError('ZIP has unsafe paths or more than 10,000 entries.')
        if len({i.filename for i in infos}) != len(infos):
            raise ValueError('ZIP contains ambiguous duplicate paths.')
        text = [i for i in infos if i.filename.lower().endswith(('.json', '.html', '.htm', '.md', '.txt'))]
        if any(i.file_size > MAX_ENTRY for i in text) or sum(i.file_size for i in text) > MAX_TEXT:
            raise ValueError('ZIP text exceeds reader limits (128 MB per part, 512 MB total).')

    def index(self, key):
        if not re.fullmatch('[a-f0-9]{64}', str(key)):
            raise ValueError('Choose an archive from the reader catalogue.')
        entry = next((e for e in self.catalogue() if e['id'] == key), None)
        if not entry or not entry['available']:
            raise ValueError('This ZIP is unavailable. Open a saved ZIP or finish its first export batch.')
        path = Path(entry['path'])
        with self.lock:
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            known = self.known.get(key)
            if known and known[0] == signature and known[1].is_file():
                return known[1], known[2], entry
            handle, temp_name = tempfile.mkstemp(dir=self.root, suffix='.zip')
            snapshot = Path(temp_name)
            try:
                # Hold the publisher lock only for the snapshot, not parsing/paging.
                with os.fdopen(handle, 'wb') as output, self.store.archive_lock:
                    if path.suffix.lower()=='.zip':
                        with path.open('rb') as source:
                            shutil.copyfileobj(source, output, 1024*1024)
                    else:
                        # A transient ZIP lets the existing safe, paged reader
                        # parse standalone JSON/HTML/MD/TXT exports unchanged.
                        # Only the derived index cache persists; source stays put.
                        if path.stat().st_size > MAX_ENTRY:
                            raise ValueError('The Discord export exceeds the 128 MB document limit.')
                        with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as wrapper:
                            wrapper.write(path,arcname=path.name)
                with snapshot.open('rb') as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                target = self.root / (digest+'.sqlite3')
                valid=False
                if target.exists():
                    with closing(sqlite3.connect(target)) as db:valid=db.execute('PRAGMA user_version').fetchone()[0]>=4
                if not valid:
                    self.build(snapshot, target)
                self.known[key] = (signature, target, digest)
                return target, digest, entry
            finally:
                snapshot.unlink(missing_ok=True)

    def build(self, snapshot, target):
        handle, temp_name = tempfile.mkstemp(dir=self.root, suffix='.sqlite3')
        os.close(handle)
        temp = Path(temp_name)
        try:
            with closing(sqlite3.connect(temp)) as db, db, zipfile.ZipFile(snapshot) as archive:
                self.validate(archive)
                db.executescript('''CREATE TABLE channels(id TEXT PRIMARY KEY,name TEXT);
                    CREATE TABLE messages(id TEXT,channel TEXT,stamp TEXT,day TEXT,hour INTEGER,author TEXT,body TEXT,raw TEXT,seq INTEGER,
                        PRIMARY KEY(channel,id));
                    CREATE TABLE assets(id TEXT PRIMARY KEY,kind TEXT,data BLOB);
                    CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
                    CREATE VIRTUAL TABLE search USING fts5(body,author,tokenize='unicode61');''')
                db.execute('PRAGMA user_version=4')
                infos = {i.filename: i for i in archive.infolist() if not i.is_dir()}
                manifest = {}
                if 'manifest.json' in infos:
                    manifest = json.loads(archive.read('manifest.json'))
                labels = {f['file']: f for f in manifest.get('files', [])}
                candidates = [n for n in infos if n.lower().endswith(('.json', '.html', '.htm', '.md', '.txt')) and n not in ('manifest.json','index.html','README.txt')]
                # Prefer detailed JSON; duplicate IDs are indexed exactly once per channel.
                candidates.sort(key=lambda n: (0 if n.endswith('.json') else 1 if n.endswith(('.html','.htm')) else 2, n))
                parsed, asset_bytes, warnings = 0, 0, []
                def asset(path,filename=''):
                    nonlocal asset_bytes
                    if not safe_entry(path) or path not in infos or infos[path].file_size > (10_000_000 if (filename or path).lower().endswith(('.mp4','.webm','.mov','.mkv')) else 100_000_000):
                        return None
                    aid = hashlib.sha256(path.encode()).hexdigest()
                    if db.execute('SELECT 1 FROM assets WHERE id=?',(aid,)).fetchone():
                        return aid
                    if asset_bytes+infos[path].file_size > 100_000_000:
                        return None
                    raw = archive.read(path)
                    from .local_media import mime
                    kind = mime(filename or path,raw)
                    db.execute('INSERT INTO assets VALUES(?,?,?)',(aid,kind,raw))
                    asset_bytes += len(raw)
                    return aid
                for name in candidates:
                    label = labels.get(name, {})
                    folder = posixpath.dirname(name)
                    cid = str(label.get('channel_id') or synthetic('zip-channel:'+folder))
                    title = label.get('channel') or folder or Path(name).stem
                    try:
                        text = archive.read(name).decode('utf-8-sig')
                        if name.endswith('.json'):
                            guild, channel, messages = parse_json(text)
                            cid, title = channel['id'], channel['name']
                        elif name.endswith(('.html', '.htm')):
                            parser = StudioHTML(); parser.feed(text); messages = parser.messages
                        else:
                            _, _, messages = parse_studio_text(text, cid, title)
                        if not messages:
                            if name.endswith('.json'):
                                db.execute('INSERT OR IGNORE INTO channels VALUES(?,?)',(cid,title))
                                parsed += 1
                            continue
                    except (ValueError, KeyError, TypeError, UnicodeError, OverflowError, OSError) as error:
                        warnings.append(name+': '+str(error)[:160]); continue
                    db.execute('INSERT OR IGNORE INTO channels VALUES(?,?)',(cid,title))
                    parsed += 1
                    for original in messages:
                        m = dict(original)
                        try:
                            stamp = datetime.fromisoformat(m['timestamp'].replace('Z','+00:00'))
                            if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
                            stamp = stamp.astimezone(timezone.utc)
                        except (ValueError, KeyError, TypeError):
                            warnings.append('Skipped message with invalid timestamp in '+name); continue
                        m['channel_name'] = title
                        m['channel_id'] = cid
                        author = m.get('author') or {}
                        emoji_assets={}
                        for eid,local in (m.get('emoji_assets') or {}).items():
                            if isinstance(local,str) and re.fullmatch(r'\d{1,22}',str(eid)):
                                aid=asset(posixpath.normpath(posixpath.join(folder,local)))
                                if aid:
                                    emoji_assets[str(eid)]=aid
                                    row=db.execute('SELECT data FROM assets WHERE id=?',(aid,)).fetchone()
                                    captured=references(m).get(str(eid),{})
                                    self.emojis.import_asset(str(eid),row[0],captured.get('name','emoji'),captured.get('animated',False))
                        if emoji_assets:m['_emoji_assets']=emoji_assets
                        linked = {}
                        for url, local in (m.get('linked_images') or {}).items():
                            if isinstance(local, str) and not local.startswith(('http:', 'https:')):
                                aid = asset(posixpath.normpath(posixpath.join(folder,local)))
                                if aid: linked[url] = aid
                        if linked: m['_linked_images'] = linked
                        avatar = author.get('avatar_local_path') or author.get('avatarUrl','')
                        if avatar and not avatar.startswith(('http:', 'https:')):
                            aid = asset(posixpath.normpath(posixpath.join(folder, avatar)))
                            if aid: m['_avatar'] = aid
                        for attachment in m.get('attachments', []):
                            local = attachment.get('local_path') or attachment.get('url','')
                            if local and not local.startswith(('http:', 'https:')):
                                aid = asset(posixpath.normpath(posixpath.join(folder,local)),attachment.get('filename') or attachment.get('fileName') or '')
                                if aid: attachment['_asset'] = aid
                        author_name = author.get('global_name') or author.get('nickname') or author.get('username') or author.get('name') or 'Unknown'
                        db.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?,?,NULL)',
                                   (str(m['id']),cid,stamp.isoformat(),stamp.date().isoformat(),stamp.hour,author_name,str(m.get('content') or ''),packed(m)))
                if not parsed:
                    raise ValueError('No supported message exports found in this ZIP. JSON preserves the most metadata.')
                db.execute('''WITH ranked AS (SELECT rowid,row_number() OVER (PARTITION BY channel ORDER BY stamp,length(id),id) n FROM messages)
                    UPDATE messages SET seq=(SELECT n FROM ranked WHERE ranked.rowid=messages.rowid)''')
                db.executescript('CREATE INDEX message_seq ON messages(channel,seq); CREATE INDEX message_day ON messages(channel,day,hour,seq);')
                db.execute('INSERT INTO search(rowid,body,author) SELECT rowid,body,author FROM messages')
                db.execute('INSERT INTO meta VALUES(?,?)',('warnings',packed(warnings[:25])))
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def query(self, key, kind, query):
        entry=reader_library.entry(self.store,key)
        if entry:
            return reader_library.query(self.store,entry,kind,query,AvatarsView(self.store))
        path, generation, entry = self.index(key)
        if kind in ('overview','calendar'):
            stamp=('zip-metadata',key,generation,kind,query.get('channel'),query.get('month'),query.get('day'))
            return self.store.metadata_cache.get(stamp,lambda:self._query_index(path,generation,entry,kind,query))
        return self._query_index(path,generation,entry,kind,query)

    def _query_index(self,path,generation,entry,kind,query):
        if kind == 'messages':
            from .searching import expand
            query = expand(query)
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            from .linked_images import image_links
            db.create_function('image_link',2,lambda text,name:int(any(str(name or '').lower() in url.lower().split('?')[0] for url in image_links(text))),deterministic=True)
            if kind == 'overview':
                channels = [dict(r) for r in db.execute('SELECT c.*,count(m.id) messages,min(m.day) first,max(m.day) last FROM channels c LEFT JOIN messages m ON m.channel=c.id GROUP BY c.id ORDER BY count(m.id)>0 DESC,c.name')]
                return {'archive':entry,'generation':generation,'channels':channels,'warnings':json.loads(db.execute("SELECT value FROM meta WHERE key='warnings'").fetchone()[0])}
            cid = query.get('channel','')
            if not db.execute('SELECT 1 FROM channels WHERE id=?',(cid,)).fetchone():
                raise ValueError('Choose a channel in this ZIP.')
            if kind == 'calendar':
                month = query.get('month','')
                if not re.fullmatch(r'\d{4}-\d{2}',month): raise ValueError('Choose a month.')
                days = [dict(r) for r in db.execute('SELECT day,count(*) messages FROM messages WHERE channel=? AND day LIKE ? GROUP BY day',(cid,month+'-%'))]
                hours = [dict(r) for r in db.execute('SELECT hour,count(*) messages FROM messages WHERE channel=? AND day=? GROUP BY hour',(cid,query.get('day','')))]
                return {'generation':generation,'days':days,'hours':hours}
            if kind != 'messages': raise ValueError('Unknown reader operation.')
            limit = min(80,max(1,int(query.get('limit',80))))
            terms = query.get('q','').strip()[:500]
            where, args = 'm.channel=?', [cid]
            if terms:
                where += ' AND m.rowid IN (SELECT rowid FROM search WHERE search MATCH ?)'
                from .searching import match_text
                args.append(match_text(terms,query.get('phrase')=='1'))
            from .searching import metadata_filter
            filters,values=metadata_filter(query,zip_index=True)
            from .searching import scope_filter
            scopes, scope_values = scope_filter(query, zip_index=True, archive_name=entry['name'])
            filters += scopes; values += scope_values
            if filters:where+=' AND '+' AND '.join(filters);args+=values
            base,base_args=where,list(args)
            total=self.store.metadata_cache.get(('zip-total',entry['id'],generation,where,tuple(args)),
                lambda:db.execute('SELECT count(*) FROM messages m WHERE '+where,args).fetchone()[0])
            reverse = False
            if query.get('before'):
                where += ' AND seq<?'; args.append(int(query['before'])); reverse = True
            elif query.get('after'):
                where += ' AND seq>?'; args.append(int(query['after']))
            elif query.get('message'):
                row = db.execute('SELECT seq FROM messages WHERE channel=? AND id=?',(cid,query['message'])).fetchone()
                if not row: raise ValueError('The referenced message is absent from this ZIP.')
                where += ' AND seq>=?'; args.append(max(1,row['seq']-10))
            elif query.get('day') and not terms and not any(query.get(k) for k in ('author','person','attachment','type','start','end','scope_channel','scope_server')):
                day = query['day']
                datetime.strptime(day,'%Y-%m-%d')
                hour = min(23,max(0,int(query.get('hour',0))))
                where += ' AND (day>? OR (day=? AND hour>=?))'; args += [day,day,hour]
            rows = list(db.execute('SELECT m.* FROM messages m WHERE '+where+' ORDER BY seq '+('DESC' if reverse else 'ASC')+' LIMIT ?',args+[limit]))
            if reverse: rows.reverse()
            first, last = (rows[0]['seq'],rows[-1]['seq']) if rows else (0,0)
            before = bool(rows and db.execute('SELECT 1 FROM messages m WHERE '+base+' AND seq<? LIMIT 1',base_args+[first]).fetchone())
            after = bool(rows and db.execute('SELECT 1 FROM messages m WHERE '+base+' AND seq>? LIMIT 1',base_args+[last]).fetchone())
            messages = [dict(json.loads(r['raw']),_seq=r['seq']) for r in rows]
            return {'generation':generation,'messages':messages,'total':total,'first':first,'last':last,'before':before,'after':after}

    def saved_messages(self, key, channel, ids):
        entry=reader_library.entry(self.store,key)
        placeholders=','.join('?' for _ in ids)
        if entry:
            with self.store.db() as db:
                rows=db.execute('SELECT m.id,m.raw FROM messages m JOIN channels c ON c.id=m.channel_id WHERE c.server_id=? AND m.channel_id=? AND m.id IN ('+placeholders+')',[entry['server_id'],channel]+ids).fetchall()
        else:
            path,_,_=self.index(key)
            with closing(sqlite3.connect(path)) as db:
                db.row_factory=sqlite3.Row
                rows=db.execute('SELECT id,raw FROM messages WHERE channel=? AND id IN ('+placeholders+')',[channel]+ids).fetchall()
        return {r['id']:json.loads(r['raw']) for r in rows}

    def saved_authors(self, key, channel, ids):
        return {mid:m.get('author') or {} for mid,m in self.saved_messages(key,channel,ids).items()}

    def asset_location(self,key,asset_id):
        if reader_library.entry(self.store,key):
            return reader_library.asset_location(self.store,asset_id)
        return None

    def asset(self, key, asset_id):
        if reader_library.entry(self.store,key):
            return reader_library.asset(self.store,asset_id)
        if not re.fullmatch('[a-f0-9]{64}', str(asset_id)): raise ValueError('Invalid saved asset.')
        path, _, _ = self.index(key)
        with closing(sqlite3.connect(path)) as db:
            row = db.execute('SELECT kind,data FROM assets WHERE id=?',(asset_id,)).fetchone()
        if not row: raise ValueError('This file was not included in the ZIP.')
        return row

    def serve_asset(self,handler,key,asset_id):
        from .local_media import send
        location=self.asset_location(key,asset_id)
        if location:return send(handler,location[0],path=location[1])
        if not re.fullmatch('[a-f0-9]{64}',str(asset_id)):raise ValueError('Invalid saved asset.')
        path,_,_=self.index(key)
        with closing(sqlite3.connect(path)) as db:
            row=db.execute('SELECT rowid,kind,length(data) FROM assets WHERE id=?',(asset_id,)).fetchone()
            if not row:raise ValueError('This file was not included in the ZIP.')
            with db.blobopen('assets','data',row[0],readonly=True) as stream:
                send(handler,row[1],stream=stream,size=row[2])


class AvatarsView:
    """Read cache metadata without resetting any active download task."""
    def __init__(self,store):self.store=store
    def cached(self):
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='avatars'").fetchone():return {}
            return {r['key']:dict(r) for r in db.execute('SELECT * FROM avatars') if (self.store.root/'avatars'/r['hash']).is_file()}
