"""Explicit, bounded offline image saving with one shared content-hashed cache."""
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit, urljoin, unquote
from .discord import Interrupted, MediaTooLarge
from .store import valid_id


def image_links(text):
    result = []
    for match in re.finditer(r'https?://[^\s<>"`]+', str(text), re.I):
        raw = match[0].rstrip('),.;!?]}')
        try:
            url = urlsplit(raw)
            if url.username or url.password or not url.hostname or not re.search(r'\.(jpe?g|png|gif)$', url.path, re.I):
                continue
            host = url.hostname.encode('idna').decode().lower()
            host = '['+host+']' if ':' in host else host
            port = url.port
            if port and port != (443 if url.scheme.lower() == 'https' else 80):
                host += ':'+str(port)
            value = urlunsplit((url.scheme.lower(), host, url.path or '/', url.query, ''))
            if value not in result and len(value) <= 4096:
                result.append(value)
        except (ValueError, UnicodeError):
            continue
        if len(result) >= 8:
            break
    return result


def public_target(value):
    url = urlsplit(value)
    if url.scheme not in ('http', 'https') or url.username or url.password or not url.hostname or url.port not in (None, 80, 443):
        raise ValueError('Offline saving supports public HTTP/HTTPS image URLs on standard ports.')
    addresses = socket.getaddrinfo(url.hostname, url.port or (443 if url.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global or ipaddress.ip_address(item[4][0]).is_multicast for item in addresses):
        raise ValueError('Offline saving cannot request local, private or reserved network addresses.')
    return url, addresses[0][4][0]


def download_image(url, target, maximum, control):
    """Pin the validated address, retain TLS hostname verification, recheck each redirect."""
    started = time.monotonic()
    for redirect in range(5):
        if not control():
            raise Interrupted('Yielded to text work or cancelled.')
        parsed, address = public_target(url)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        connection = (http.client.HTTPSConnection(parsed.hostname, port, timeout=8, context=ssl.create_default_context())
                      if parsed.scheme == 'https' else http.client.HTTPConnection(parsed.hostname, port, timeout=8))
        connection._create_connection = lambda *args, **kwargs: socket.create_connection((address, port), timeout=8)
        try:
            connection.request('GET', urlunsplit(('', '', parsed.path or '/', parsed.query, '')),
                headers={'User-Agent': 'DiscordArchiveStudio/1.7', 'Accept': 'image/png,image/jpeg,image/gif', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location or redirect == 4:
                    raise ValueError('The image redirected too many times or without a destination.')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError('Image host returned HTTP '+str(response.status)+'.')
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('The image host returned an unsupported content encoding.')
            length = response.getheader('Content-Length')
            if length and int(length) > maximum:
                raise MediaTooLarge('Image exceeds the selected offline size cap.')
            total = 0
            with target.open('wb') as output:
                while True:
                    if not control():
                        raise Interrupted('Yielded to text work or cancelled.')
                    if time.monotonic()-started > 60:
                        raise ValueError('Image download exceeded the 60-second time budget.')
                    chunk = response.read(min(65536, maximum-total+1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > maximum:
                        raise MediaTooLarge('Image exceeds the selected offline size cap.')
                    output.write(chunk)
            with target.open('rb') as source:
                head = source.read(16)
            if not (head.startswith(b'\x89PNG\r\n\x1a\n') or head.startswith((b'GIF87a', b'GIF89a', b'\xff\xd8\xff'))):
                raise ValueError('The URL did not return a PNG, JPEG or GIF image.')
            return total
        finally:
            connection.close()


class LinkedImages:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS linked_images(url_key TEXT PRIMARY KEY,url TEXT NOT NULL,
                filename TEXT NOT NULL,status TEXT NOT NULL,max_bytes INTEGER NOT NULL,received INTEGER NOT NULL DEFAULT 0,
                hash TEXT NOT NULL DEFAULT '',detail TEXT NOT NULL DEFAULT '',updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS image_refs(scope TEXT,channel_id TEXT,message_id TEXT,url_key TEXT,server_id TEXT,
                PRIMARY KEY(scope,channel_id,message_id,url_key));
                CREATE INDEX IF NOT EXISTS image_server ON image_refs(server_id,url_key);''')
            db.execute("UPDATE linked_images SET status='paused',detail='Paused after restart; retry explicitly.' WHERE status='running'")

    def tasks(self):
        with self.store.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM linked_images ORDER BY status IN ('queued','running') DESC,updated DESC LIMIT 150")]

    def saved(self):
        with self.store.db() as db:
            return {r['url']: dict(r) for r in db.execute("SELECT * FROM linked_images WHERE hash<>''")
                    if (self.store.root/'media'/r['hash']).is_file()}

    def select(self, selections, reader, cap_mb=10):
        if not isinstance(selections, list) or not 1 <= len(selections) <= 50:
            raise ValueError('Select between 1 and 50 linked images.')
        maximum = max(1, min(10, int(cap_mb)))*1000000
        from .reader_library import entry
        prepared = []
        for item in selections:
            mid, cid = valid_id(item.get('message','')), valid_id(item.get('channel',''))
            archive = str(item.get('archive') or '')
            native = entry(self.store, archive) if archive else None
            if archive:
                m = reader.saved_messages(archive, cid, [mid]).get(mid)
            else:
                with self.store.db() as db:
                    row = db.execute('SELECT raw FROM messages WHERE id=? AND channel_id=?', (mid,cid)).fetchone()
                m = json.loads(row[0]) if row else None
            if not m:
                raise ValueError('Choose an image from a saved message.')
            urls = image_links(m.get('content',''))
            chosen = urlsplit(str(item.get('url','')))._replace(fragment='').geturl()
            if chosen not in urls:
                raise ValueError('This image URL is not referenced by the saved message.')
            key = hashlib.sha256(chosen.encode()).hexdigest()
            with self.store.db() as db:
                row = db.execute('SELECT server_id FROM channels WHERE id=?',(cid,)).fetchone() if not archive or native else None
            scope = 'library' if not archive or native else archive
            filename = Path(unquote(urlsplit(chosen).path)).name[:200] or 'image'
            prepared.append((key, chosen, filename, scope, cid, mid, row[0] if row else ''))
        added = reused = 0
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute("SELECT count(*),coalesce(sum(max_bytes),0) FROM media_requests WHERE status IN ('queued','running')").fetchone()
            linked = db.execute("SELECT count(*),coalesce(sum(max_bytes),0) FROM linked_images WHERE status IN ('queued','running')").fetchone()
            count, total = pending[0]+linked[0], pending[1]+linked[1]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('avatar_tasks','emojis'):
                if table in tables:
                    extra = db.execute("SELECT count(*) FROM "+table+" WHERE status IN ('queued','running')").fetchone()[0]
                    count += extra; total += extra*1000000
            for key, url, filename, scope, cid, mid, sid in prepared:
                old = db.execute('SELECT * FROM linked_images WHERE url_key=?', (key,)).fetchone()
                db.execute('INSERT OR IGNORE INTO image_refs VALUES(?,?,?,?,?)',(scope,cid,mid,key,sid))
                if old and old['hash'] and (self.store.root/'media'/old['hash']).is_file():
                    reused += 1
                    if old['status'] != 'running':
                        db.execute("UPDATE linked_images SET status='queued',detail='Reusing cached image; updating relevant ZIPs.',updated=? WHERE url_key=?", (time.time(),key))
                    continue
                if old and old['status'] in ('queued','running'):
                    continue
                if count >= 50 or total+maximum > 100000000:
                    raise ValueError('Pending downloads are capped at 50 files and 100 MB. Finish or cancel some first.')
                db.execute('''INSERT INTO linked_images VALUES(?,?,?,?,?,0,'',?,?) ON CONFLICT(url_key)
                    DO UPDATE SET status='queued',max_bytes=excluded.max_bytes,detail=excluded.detail,updated=excluded.updated''',
                    (key,url,filename,'queued',maximum,'Selected manually; waiting behind text exports.',time.time()))
                added += 1; count += 1; total += maximum
        return {'queued': added, 'cached': reused}

    def update(self, key, status, detail, **fields):
        if set(fields)-{'received','hash'}:
            raise ValueError('Unsupported linked-image update.')
        with self.store.db() as db:
            db.execute('UPDATE linked_images SET status=?,detail=?,updated=?'+''.join(','+k+'=?' for k in fields)+' WHERE url_key=?',
                (status,detail,time.time(),*fields.values(),key))

    def fetch(self, task, control):
        if task['hash'] and (self.store.root/'media'/task['hash']).is_file():
            return task['received']
        handle, name = tempfile.mkstemp(prefix='linked-', suffix='.partial', dir=self.store.root)
        os.close(handle)
        temp = Path(name)
        try:
            size = download_image(task['url'], temp, task['max_bytes'], control)
            with temp.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            target = self.store.root/'media'/digest
            with self.store.archive_lock:
                if target.exists():
                    temp.unlink()
                else:
                    os.replace(temp, target)
                self.update(task['url_key'], 'running', 'Saved locally; updating related ZIPs.', received=size, hash=digest)
            return size
        finally:
            temp.unlink(missing_ok=True)
