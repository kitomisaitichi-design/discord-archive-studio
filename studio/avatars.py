"""Bounded profile images, keyed by captured user ID and avatar version."""
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from .discord import download, Interrupted


def image_kind(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if raw.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if raw.startswith((b'GIF87a',b'GIF89a')): return 'image/gif'
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP': return 'image/webp'
    return None


def avatar_key(author):
    uid = str(author.get('id',''))
    version = str(author.get('avatar') or '')
    if not re.fullmatch(r'\d{1,22}',uid): return None
    if not re.fullmatch(r'(?:a_)?[a-f0-9]{32}',version):
        match = re.fullmatch(r'https://(?:cdn\.discordapp\.com|media\.discordapp\.net)/avatars/'+uid+r'/((?:a_)?[a-f0-9]{32})\.(?:png|gif|webp|jpe?g)(?:\?[^#]*)?',str(author.get('avatarUrl') or ''))
        if not match: return None
        version = match[1]
    return uid+':'+version, 'https://cdn.discordapp.com/avatars/'+uid+'/'+version+'.webp?size=128'


class Avatars:
    def __init__(self, store):
        self.store = store
        (store.root/'avatars').mkdir(exist_ok=True)
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS avatars(key TEXT PRIMARY KEY,hash TEXT,kind TEXT,size INTEGER);
                CREATE TABLE IF NOT EXISTS avatar_tasks(key TEXT PRIMARY KEY,url TEXT,status TEXT,detail TEXT,updated REAL);''')
            db.execute("UPDATE avatar_tasks SET status='paused',detail='Paused after restart; retry explicitly.' WHERE status='running'")

    def tasks(self):
        with self.store.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM avatar_tasks ORDER BY CASE WHEN status IN ('queued','running') THEN 0 ELSE 1 END,updated DESC LIMIT 100")]

    def cached(self):
        with self.store.db() as db:
            return {r['key']:dict(r) for r in db.execute('SELECT * FROM avatars') if (self.store.root/'avatars'/r['hash']).is_file()}

    def queue(self, channels, retry=False):
        if not isinstance(channels,list) or not channels: raise ValueError('Select saved channels for profile pictures.')
        channels = list(dict.fromkeys(str(c) for c in channels))
        if len(channels)>1000: raise ValueError('Select at most 1,000 channels.')
        count = deferred = reused = 0
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute("SELECT count(*) FROM avatar_tasks WHERE status IN ('queued','running')").fetchone()[0]
            media = db.execute("SELECT count(*),coalesce(sum(max_bytes),0) FROM media_requests WHERE status IN ('queued','running')").fetchone()
            available = min(50-media[0]-pending,(100_000_000-media[1]-pending*1_000_000)//1_000_000)
            seen = set()
            for cid in channels:
                if not db.execute('SELECT 1 FROM channels WHERE id=?',(cid,)).fetchone(): raise ValueError('Selected channel is absent from the saved library.')
                for row in db.execute('SELECT DISTINCT json_extract(raw,\'$.author\') author FROM messages WHERE channel_id=?',(cid,)):
                    captured = avatar_key(json.loads(row['author'] or '{}'))
                    if not captured or captured[0] in seen: continue
                    key,url = captured; seen.add(key)
                    saved = db.execute('SELECT hash FROM avatars WHERE key=?',(key,)).fetchone()
                    if saved and (self.store.root/'avatars'/saved[0]).is_file(): reused += 1; continue
                    task = db.execute('SELECT status FROM avatar_tasks WHERE key=?',(key,)).fetchone()
                    if task and (task[0] in ('queued','running') or not retry): continue
                    if available <= 0: deferred += 1; continue
                    db.execute('INSERT OR REPLACE INTO avatar_tasks VALUES(?,?,?,?,?)',(key,url,'queued','Selected; waits for a committed text rest.',time.time()))
                    available -= 1; count += 1
        return {'queued':count,'cached':reused,'deferred':deferred}

    def update(self, key, status, detail):
        with self.store.db() as db:
            db.execute('UPDATE avatar_tasks SET status=?,detail=?,updated=? WHERE key=?',(status,detail,time.time(),key))

    def visible(self, authors):
        """Authors come from saved message rows, never caller-supplied CDN URLs."""
        result = {}; queued = 0
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute("SELECT count(*) FROM avatar_tasks WHERE status IN ('queued','running')").fetchone()[0]
            media = db.execute("SELECT count(*),coalesce(sum(max_bytes),0) FROM media_requests WHERE status IN ('queued','running')").fetchone()
            available = min(50-media[0]-pending,(100_000_000-media[1]-pending*1_000_000)//1_000_000)
            for mid, author in authors.items():
                captured = avatar_key(author)
                if not captured: result[mid] = {'status':'unavailable'}; continue
                key, url = captured
                saved = db.execute('SELECT hash FROM avatars WHERE key=?',(key,)).fetchone()
                if saved and (self.store.root/'avatars'/saved[0]).is_file():
                    result[mid] = {'status':'cached','url':'/avatar/'+saved[0]}; continue
                task = db.execute('SELECT status FROM avatar_tasks WHERE key=?',(key,)).fetchone()
                if task:
                    result[mid] = {'status':task[0]}; continue
                if available <= 0: result[mid] = {'status':'deferred'}; continue
                db.execute('INSERT INTO avatar_tasks VALUES(?,?,?,?,?)',(key,url,'queued','Visible author; waits for a committed text rest.',time.time()))
                available -= 1; queued += 1; result[mid] = {'status':'queued'}
        return {'pictures':result,'queued':queued}

    def fetch(self, task, control):
        cached = self.cached().get(task['key'])
        if cached: return cached['size']
        handle, name = tempfile.mkstemp(dir=self.store.root, suffix='.partial')
        os.close(handle); temp = Path(name)
        try:
            size = download(task['url'],temp,1_000_000,control)
            raw = temp.read_bytes(); kind = image_kind(raw)
            if not kind: raise ValueError('Profile-picture response was not a supported raster image.')
            digest = hashlib.sha256(raw).hexdigest()
            with self.store.archive_lock:
                target = self.store.root/'avatars'/digest
                if target.exists(): temp.unlink()
                else: os.replace(temp,target)
                with self.store.db() as db:
                    db.execute('INSERT OR REPLACE INTO avatars VALUES(?,?,?,?)',(task['key'],digest,kind,size))
            return size
        finally:
            temp.unlink(missing_ok=True)

    def servers(self, key):
        with self.store.db() as db:
            return [r[0] for r in db.execute('SELECT DISTINCT c.server_id FROM channels c JOIN messages m ON m.channel_id=c.id WHERE m.author_id=?',(key.split(':',1)[0],))]
