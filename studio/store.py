import hashlib
import json
from pathlib import Path
import sqlite3
import time
import threading
from datetime import datetime, timezone
import uuid
from contextlib import contextmanager


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(packed(value).encode('utf-8')).hexdigest()


def valid_id(value):
    value = str(value)
    if not value.isdigit() or len(value) > 22:
        raise ValueError('A valid Discord ID is required.')
    return value


class Store:
    def __init__(self, root):
        self.version = 0
        self.archive_lock = threading.RLock()
        self.queue_lock = threading.RLock()
        self.processing_job = None
        self.changed = threading.Condition()
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'media').mkdir(exist_ok=True)
        self.path = self.root / 'archive.sqlite3'
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS servers (id TEXT PRIMARY KEY,name TEXT NOT NULL,raw TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS channels (id TEXT PRIMARY KEY,server_id TEXT NOT NULL,name TEXT NOT NULL,
              type INTEGER NOT NULL DEFAULT 0,parent_id TEXT,raw TEXT NOT NULL,last_id TEXT,history_done INTEGER NOT NULL DEFAULT 0,
              generation INTEGER NOT NULL DEFAULT 0,last_scan REAL);
            CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY,name TEXT NOT NULL,raw TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS aliases (user_id TEXT PRIMARY KEY,person_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY,channel_id TEXT NOT NULL,author_id TEXT NOT NULL,
              timestamp TEXT NOT NULL,content TEXT NOT NULL,hash TEXT NOT NULL,raw TEXT NOT NULL,captured REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS message_channel_time ON messages(channel_id,timestamp,id);
            CREATE INDEX IF NOT EXISTS message_channel_id ON messages(channel_id,length(id) DESC,id DESC);
            CREATE INDEX IF NOT EXISTS message_time_order ON messages(timestamp DESC,length(id) DESC,id DESC);
            CREATE INDEX IF NOT EXISTS message_author ON messages(author_id,timestamp);
            CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(content,content='messages',content_rowid='rowid',tokenize='unicode61');
            CREATE TRIGGER IF NOT EXISTS msg_insert AFTER INSERT ON messages BEGIN
              INSERT INTO message_fts(rowid,content) VALUES(new.rowid,new.content); END;
            CREATE TRIGGER IF NOT EXISTS msg_delete AFTER DELETE ON messages BEGIN
              INSERT INTO message_fts(message_fts,rowid,content) VALUES('delete',old.rowid,old.content); END;
            CREATE TRIGGER IF NOT EXISTS msg_update AFTER UPDATE OF content ON messages BEGIN
              INSERT INTO message_fts(message_fts,rowid,content) VALUES('delete',old.rowid,old.content);
              INSERT INTO message_fts(rowid,content) VALUES(new.rowid,new.content); END;
            CREATE TABLE IF NOT EXISTS revisions (message_id TEXT NOT NULL,hash TEXT NOT NULL,raw TEXT NOT NULL,
              captured REAL NOT NULL,PRIMARY KEY(message_id,hash));
            CREATE TABLE IF NOT EXISTS media (attachment_id TEXT PRIMARY KEY,hash TEXT NOT NULL,filename TEXT NOT NULL,
              size INTEGER NOT NULL,relative_path TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS media_requests (attachment_id TEXT PRIMARY KEY,message_id TEXT NOT NULL,
              channel_id TEXT NOT NULL,status TEXT NOT NULL,max_bytes INTEGER NOT NULL,received INTEGER NOT NULL DEFAULT 0,
              detail TEXT NOT NULL DEFAULT '',updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,channel_id TEXT NOT NULL,owner_id TEXT NOT NULL,
              status TEXT NOT NULL,position REAL NOT NULL,options TEXT NOT NULL,progress INTEGER NOT NULL DEFAULT 0,
              cursor TEXT,boundary TEXT,phase TEXT NOT NULL DEFAULT 'messages',dirty INTEGER NOT NULL DEFAULT 0,
              detail TEXT NOT NULL DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS schedules (scope TEXT PRIMARY KEY,owner_id TEXT NOT NULL,enabled INTEGER NOT NULL,
              mode TEXT NOT NULL,minutes INTEGER NOT NULL,options TEXT NOT NULL,next_run REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS publications (server_id TEXT PRIMARY KEY,path TEXT NOT NULL,hash TEXT NOT NULL,
              options TEXT NOT NULL,updated REAL NOT NULL,size INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS channel_exports (channel_id TEXT PRIMARY KEY,options TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS presets (name TEXT PRIMARY KEY,options TEXT NOT NULL);
            ''')
            db.execute("UPDATE jobs SET status='paused',detail='Paused after restart; resume from the last committed page.' WHERE status IN ('running','waiting')")
            db.execute("UPDATE media_requests SET status='paused',detail='Paused after restart; retry explicitly.' WHERE status IN ('queued','running')")
            if 'quality' not in {r['name'] for r in db.execute('PRAGMA table_info(messages)')}:
                if db.execute('SELECT count(*) FROM messages').fetchone()[0]:
                    recovery = self.root / 'Recovery'
                    recovery.mkdir(exist_ok=True)
                    path = recovery / ('schema-'+str(time.time_ns())+'.sqlite3')
                    with sqlite3.connect(path) as backup:
                        # End any startup transaction before SQLite's online backup operation.
                        db.commit()
                        db.backup(backup)
                db.execute('ALTER TABLE messages ADD COLUMN quality INTEGER NOT NULL DEFAULT 4')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=20000')
        try:
            with db:
                yield db
        finally:
            changes = db.total_changes
            db.close()
            if changes:
                with self.changed:
                    self.version += 1
                    self.changed.notify_all()

    def setting(self, key, default=None):
        with self.db() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else default

    def set_setting(self, key, value):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, packed(value)))

    def media_tasks(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT r.*,c.server_id,c.name channel_name FROM media_requests r JOIN channels c ON c.id=r.channel_id ORDER BY CASE WHEN r.status IN ('queued','running') THEN 0 WHEN r.status='paused' THEN 1 ELSE 2 END,r.updated DESC LIMIT 150")]

    def update_media(self, attachment_id, **changes):
        if not changes or set(changes)-{'status','received','detail'}:
            raise ValueError('Unsupported attachment task update.')
        with self.db() as db:
            db.execute('UPDATE media_requests SET '+','.join(k+'=?' for k in changes)+',updated=? WHERE attachment_id=?',(*changes.values(),time.time(),attachment_id))
            if changes.get('status')=='skipped':
                db.execute('UPDATE channels SET generation=generation+1 WHERE id=(SELECT channel_id FROM media_requests WHERE attachment_id=?)',(attachment_id,))

    def enqueue_media(self, selections, cap_mb=10):
        from .exporting import media_limit, media_reason
        if not isinstance(selections,list) or not 1 <= len(selections) <= 50:
            raise ValueError('Select between 1 and 50 attachments.')
        cap_mb = int(cap_mb)
        if not 1 <= cap_mb <= 100:
            raise ValueError('Choose a per-file cap between 1 and 100 MB. Videos remain capped at 10 MB.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = {r['attachment_id']:r['max_bytes'] for r in db.execute("SELECT * FROM media_requests WHERE status IN ('queued','running')")}
            avatar_count = db.execute("SELECT count(*) FROM avatar_tasks WHERE status IN ('queued','running')").fetchone()[0] if db.execute("SELECT 1 FROM sqlite_master WHERE name='avatar_tasks'").fetchone() else 0
            added = skipped = 0
            for selection in selections:
                mid, aid = valid_id(selection['message_id']), valid_id(selection['attachment_id'])
                if aid in pending:
                    continue
                row = db.execute('SELECT raw,channel_id FROM messages WHERE id=?',(mid,)).fetchone()
                if not row:
                    raise ValueError('Selected message is not saved in this library.')
                attachment = next((a for a in json.loads(row['raw']).get('attachments',[]) if str(a.get('id'))==aid),None)
                if not attachment:
                    raise ValueError('Selected attachment is not part of this saved message.')
                maximum = media_limit(attachment,cap_mb)
                reason = media_reason(attachment,maximum)
                if not reason and (len(pending)+avatar_count>=50 or sum(pending.values())+avatar_count*1000000+maximum>100000000):
                    raise ValueError('Pending downloads are capped at 100 MB and 50 files. Finish or cancel some selections first.')
                status = 'skipped' if reason else 'queued'
                db.execute('INSERT OR REPLACE INTO media_requests VALUES(?,?,?,?,?,0,?,?)',(aid,mid,row['channel_id'],status,maximum,reason or 'Selected manually; waiting until text exports finish.',time.time()))
                if reason:
                    skipped += 1
                else:
                    pending[aid]=maximum
                    added += 1
            return {'tasks':added,'skipped':skipped}

    def catalog(self, servers, channels=None, server_id=None):
        with self.db() as db:
            for s in servers:
                sid = valid_id(s['id'])
                db.execute('INSERT OR REPLACE INTO servers VALUES(?,?,?)', (sid, s.get('name', 'Direct messages'), packed(s)))
            for c in channels or []:
                cid = valid_id(c['id'])
                recipients = c.get('recipients', [])
                name = c.get('name') or ', '.join(u.get('global_name') or u.get('username', 'User') for u in recipients) or cid
                sid = str(c.get('guild_id') or server_id or '0')
                db.execute('''INSERT INTO channels(id,server_id,name,type,parent_id,raw) VALUES(?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET server_id=excluded.server_id,name=excluded.name,type=excluded.type,
                  parent_id=excluded.parent_id,raw=excluded.raw''', (cid, sid, name, c.get('type', 0), c.get('parent_id'), packed(c)))

    def upsert(self, channel_id, messages, quality=4):
        with self.archive_lock:
            return self._upsert(channel_id, messages, quality)

    def _upsert(self, channel_id, messages, quality):
        cid = valid_id(channel_id)
        added = edited = 0
        with self.db() as db:
            if not db.execute('SELECT 1 FROM channels WHERE id=?', (cid,)).fetchone():
                raise ValueError('Select a known channel before importing messages.')
            for original in messages:
                m = dict(original)
                mid = valid_id(m['id'])
                if m.get('channel_id') and str(m['channel_id']) != cid:
                    raise ValueError('Message channel does not match its archive.')
                author = m.get('author') or {'id': '0', 'username': 'Unknown'}
                aid = valid_id(author['id'])
                timestamp = m.get('timestamp')
                if not isinstance(timestamp, str) or not timestamp:
                    raise ValueError('Message timestamp is required.')
                try:
                    instant = datetime.fromisoformat(timestamp.replace('Z','+00:00'))
                    if instant.tzinfo is None:
                        raise ValueError('Timezone missing')
                    order_time = instant.astimezone(timezone.utc).isoformat(timespec='microseconds')
                except ValueError:
                    raise ValueError('Message timestamps must be valid ISO-8601 with a timezone.') from None
                m['channel_id'] = cid
                # Signed CDN query strings expire; their rotation is not a message edit.
                stable = json.loads(packed(m))
                for attachment in stable.get('attachments', []):
                    for field in ('url', 'proxy_url'):
                        if field in attachment:
                            attachment[field] = attachment[field].split('?', 1)[0]
                digest = fingerprint(stable)
                old = db.execute('SELECT hash,raw,channel_id,quality FROM messages WHERE id=?', (mid,)).fetchone()
                if old and old['quality'] > quality:
                    continue
                db.execute('INSERT OR REPLACE INTO users VALUES(?,?,?)', (aid, author.get('global_name') or author.get('username', aid), packed(author)))
                if old and old['hash'] == digest:
                    # Refresh attachment URLs without counting it as an edit.
                    db.execute('UPDATE messages SET raw=?,quality=max(quality,?) WHERE id=?', (packed(m), quality, mid))
                    continue
                if old:
                    edited += 1
                    db.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?)', (mid, old['hash'], old['raw'], time.time()))
                else:
                    added += 1
                if old and old['channel_id'] != cid:
                    db.execute('UPDATE channels SET generation=generation+1 WHERE id=?', (old['channel_id'],))
                db.execute('''INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                  channel_id=excluded.channel_id,author_id=excluded.author_id,timestamp=excluded.timestamp,content=excluded.content,hash=excluded.hash,
                  raw=excluded.raw,captured=excluded.captured,quality=excluded.quality''',
                  (mid, cid, aid, order_time, m.get('content', ''), digest, packed(m), time.time(), quality))
            if added or edited:
                db.execute('UPDATE channels SET generation=generation+1 WHERE id=?', (cid,))
        return {'added': added, 'edited': edited}

    def channels(self, server_id=None):
        with self.db() as db:
            return [dict(r) for r in db.execute('''SELECT c.id,c.server_id,c.name,c.type,c.parent_id,c.last_id,c.history_done,
              c.last_scan,c.generation,(SELECT count(*) FROM messages m WHERE m.channel_id=c.id) count
              FROM channels c WHERE (? IS NULL OR c.server_id=?) ORDER BY c.type,c.name''', (server_id, server_id))]

    def servers(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('''SELECT s.id,s.name,(SELECT count(*) FROM channels c WHERE c.server_id=s.id) channels,
              (SELECT count(*) FROM messages m JOIN channels c ON c.id=m.channel_id WHERE c.server_id=s.id) messages FROM servers s ORDER BY s.name''')]

    def search(self, text='', channel=None, server=None, person=None, start=None, end=None, offset=0, limit=80):
        terms = text.strip().split()
        where, params = [], []
        if terms:
            # Treat user input as literal FTS terms; punctuation/operator syntax cannot break a query.
            query = ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms[:30])
            if text.strip().isdigit() and len(text.strip()) <= 22:
                where.append('(m.id=? OR m.rowid IN (SELECT rowid FROM message_fts WHERE message_fts MATCH ?))')
                params.extend([text.strip(), query])
            else:
                where.append('m.rowid IN (SELECT rowid FROM message_fts WHERE message_fts MATCH ?)')
                params.append(query)
        for field, value in [('m.channel_id', channel), ('c.server_id', server)]:
            if value:
                where.append(field + '=?')
                params.append(str(value))
        if person:
            where.append("COALESCE(a.person_id,m.author_id)=COALESCE((SELECT person_id FROM aliases WHERE user_id=?),?)")
            params.extend([str(person), str(person)])
        if start:
            where.append('m.timestamp>=?')
            params.append(start)
        if end:
            where.append('m.timestamp<?')
            params.append(end + 'T23:59:59.999999Z' if len(end) == 10 else end)
        condition = ' AND '.join(where) or '1'
        join = ' FROM messages m JOIN channels c ON c.id=m.channel_id LEFT JOIN aliases a ON a.user_id=m.author_id '
        with self.db() as db:
            count = db.execute('SELECT count(*)' + join + ' WHERE ' + condition, params).fetchone()[0]
            rows = db.execute('SELECT m.raw,m.channel_id,c.name channel_name,c.server_id' + join + ' WHERE ' + condition +
                              ' ORDER BY m.timestamp DESC,length(m.id) DESC,m.id DESC LIMIT ? OFFSET ?',
                              params + [max(1, min(int(limit), 200)), max(0, int(offset))]).fetchall()
        return {'total': count, 'messages': [dict(json.loads(r['raw']), channel_name=r['channel_name'], server_id=r['server_id']) for r in rows]}

    def preview(self, channel_id, before=None, limit=50):
        cid=valid_id(channel_id);limit=max(1,min(int(limit),100))
        params=[cid];where='m.channel_id=?'
        with self.db() as db:
            if before:
                before=valid_id(before)
                boundary=db.execute('SELECT timestamp FROM messages WHERE id=? AND channel_id=?',(before,cid)).fetchone()
                if not boundary:raise ValueError('The preview cursor is not in this saved channel.')
                where+=' AND (m.timestamp<? OR (m.timestamp=? AND (length(m.id)<length(?) OR (length(m.id)=length(?) AND m.id<?))))'
                params.extend([boundary['timestamp'],boundary['timestamp'],before,before,before])
            rows=db.execute('SELECT m.raw,c.name channel_name,c.server_id FROM messages m JOIN channels c ON c.id=m.channel_id WHERE '+where+' ORDER BY m.timestamp DESC,length(m.id) DESC,m.id DESC LIMIT ?',params+[limit+1]).fetchall()
        messages=[dict(json.loads(r['raw']),channel_name=r['channel_name'],server_id=r['server_id']) for r in rows[:limit]]
        return {'messages':messages,'has_more':len(rows)>limit,'next_cursor':messages[-1]['id'] if messages else None,'media':{}}

    def iter_messages(self, channel_id):
        with self.db() as db:
            for row in db.execute('SELECT raw FROM messages WHERE channel_id=? ORDER BY timestamp,length(id),id', (channel_id,)):
                yield json.loads(row['raw'])

    def newest_saved(self, channel_id):
        with self.db() as db:
            row = db.execute('SELECT id FROM messages WHERE channel_id=? ORDER BY length(id) DESC,id DESC LIMIT 1',(channel_id,)).fetchone()
        return row['id'] if row else None

    def alias(self, user_id, person_id=None):
        uid = valid_id(user_id)
        with self.db() as db:
            if not db.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone():
                raise ValueError('This user ID is not in the library.')
            if not person_id or str(person_id) == uid:
                db.execute('DELETE FROM aliases WHERE user_id=?', (uid,))
                return
            pid = valid_id(person_id)
            if not db.execute('SELECT 1 FROM users WHERE id=?', (pid,)).fetchone():
                raise ValueError('The target user ID is not in the library.')
            target = db.execute('SELECT person_id FROM aliases WHERE user_id=?', (pid,)).fetchone()
            pid = target['person_id'] if target else pid
            if pid == uid:
                raise ValueError('This link would create an identity cycle.')
            db.execute('UPDATE aliases SET person_id=? WHERE person_id=?', (pid, uid))
            db.execute('INSERT OR REPLACE INTO aliases VALUES(?,?)', (uid, pid))

    def users(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT u.id,u.name,a.person_id FROM users u LEFT JOIN aliases a ON a.user_id=u.id ORDER BY u.name LIMIT 3000')]

    def enqueue(self, channels, owner, options, scheduled=False):
        options=dict(options)
        ids = []
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            defaults=db.execute('SELECT value FROM settings WHERE key=?',('queue_defaults:'+owner,)).fetchone()
            if options.pop('_use_queue_defaults',True) and defaults:
                for k,v in json.loads(defaults['value']).items():
                    if k not in options.get('_queue_overrides',[]):options[k]=v
            if scheduled:options.update(full_rescan=False,_scheduled=True)
            position = db.execute('SELECT COALESCE(max(position),0) FROM jobs').fetchone()[0]
            for cid in dict.fromkeys(map(valid_id, channels)):
                row = db.execute('SELECT type FROM channels WHERE id=?', (cid,)).fetchone()
                if not row or row['type'] in (4, 15, 16):
                    continue
                existing = db.execute("SELECT id,status,options FROM jobs WHERE channel_id=? AND owner_id=? AND status IN ('queued','running','waiting','paused','blocked') ORDER BY position LIMIT 1", (cid, owner)).fetchone()
                if existing:
                    if existing['status'] in ('running', 'waiting') and scheduled:
                        db.execute('UPDATE jobs SET dirty=1 WHERE id=?', (existing['id'],))
                    elif existing['status'] == 'queued' and not scheduled:
                        previous=json.loads(existing['options'])
                        internal={k:v for k,v in previous.items() if k.startswith('_')}
                        merged=dict(options,**internal)
                        for k in previous.get('_queue_overrides',[]):
                            if k in previous:merged[k]=previous[k]
                        db.execute('UPDATE jobs SET options=? WHERE id=?', (packed(merged), existing['id']))
                    ids.append(existing['id'])
                    continue
                jid = uuid.uuid4().hex
                position += 1
                db.execute('INSERT INTO jobs(id,channel_id,owner_id,status,position,options,created,updated) VALUES(?,?,?,\'queued\',?,?,?,?)',
                           (jid, cid, owner, position, packed(options), time.time(), time.time()))
                ids.append(jid)
        return ids

    def jobs(self, history=False):
        with self.db() as db:
            rows = db.execute('''SELECT j.*,c.name channel_name,c.server_id,s.name server_name FROM jobs j
              JOIN channels c ON c.id=j.channel_id JOIN servers s ON s.id=c.server_id
              WHERE ''' + ("j.status IN ('completed','cancelled','failed') ORDER BY j.updated DESC LIMIT 100" if history else
                           "j.status NOT IN ('completed','cancelled','failed') ORDER BY j.position")).fetchall()
        return [dict(r, options=json.loads(r['options'])) for r in rows]

    def job(self, jid):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        if not row:
            raise ValueError('Queue task was not found.')
        return dict(row, options=json.loads(row['options']))

    def update_job(self, jid, **fields):
        allowed = {'status', 'progress', 'cursor', 'boundary', 'phase', 'dirty', 'detail', 'position'}
        if set(fields) - allowed:
            raise ValueError('Invalid job update.')
        fields['updated'] = time.time()
        with self.db() as db:
            db.execute('UPDATE jobs SET ' + ','.join(k+'=?' for k in fields) + ' WHERE id=?', list(fields.values())+[jid])

    def claim_job(self, jid, owner):
        with self.queue_lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed=db.execute("UPDATE jobs SET status='running' WHERE id=? AND owner_id=? AND status IN ('queued','waiting')",(jid,owner)).rowcount
            if changed:self.processing_job=jid
            return bool(changed)

    def release_job(self, jid):
        with self.queue_lock:
            if self.processing_job==jid:
                self.processing_job=None
                with self.changed:
                    self.version+=1;self.changed.notify_all()

    def reorder(self, jid, before=None, direction=None):
        with self.queue_lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT id,position,status FROM jobs WHERE status NOT IN ('completed','cancelled','failed') ORDER BY position").fetchall()
            movable=[r for r in rows if r['status']!='running' and r['id']!=self.processing_job]
            ids=[r['id'] for r in movable]
            if jid not in ids:raise ValueError('This task is exporting or no longer movable. Refresh the queue.')
            if direction:
                index=ids.index(jid);target=index+(-1 if direction=='up' else 1)
                if target<0 or target>=len(ids):return
                ids[index],ids[target]=ids[target],ids[index]
            elif before!=jid:
                if before is not None and before not in ids:raise ValueError('The drop target is exporting or no longer in the queue.')
                ids.remove(jid);ids.insert(ids.index(before) if before else len(ids),jid)
            # Active positions remain fixed. Only vacant movable slots change ownership.
            for row,uid in zip(movable,ids):db.execute('UPDATE jobs SET position=? WHERE id=?',(row['position'],uid))

    def control(self, jid, action):
        job = self.job(jid)
        if action == 'pause' and job['status'] in ('running', 'waiting', 'queued'):
            self.update_job(jid, status='paused', detail='Paused; committed pages are safe.')
        elif action == 'resume' and job['status'] in ('paused', 'failed', 'blocked'):
            self.update_job(jid, status='queued', detail='Ready to resume.')
        elif action == 'cancel' and job['status'] not in ('completed', 'cancelled'):
            self.update_job(jid, status='cancelled', detail='Cancelled; captured messages are preserved.')
        elif action in ('up', 'down'):
            self.reorder(jid,direction=action)
        else:
            raise ValueError('This action is not available for this task state.')

    def configure_job(self, jid, opts):
        with self.queue_lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row or row['id']==self.processing_job or row['status'] not in ('queued','waiting','paused','failed','blocked'):
                raise ValueError('This task is actively exporting or no longer editable.')
            job=dict(row,options=json.loads(row['options']))
            merged = dict(opts, **{k:v for k,v in job['options'].items() if k.startswith('_')})
            if opts.get('full_rescan') and not job['options'].get('full_rescan'):
                db.execute("UPDATE jobs SET options=?,cursor=NULL,boundary=NULL,phase='messages',progress=0,detail='Settings updated; full history recheck requested.' WHERE id=?", (packed(opts),jid))
            else:
                db.execute("UPDATE jobs SET options=?,detail='Settings updated; checkpoint preserved.' WHERE id=?", (packed(merged),jid))

    def configure_queue(self, owner, target, changes, ids=None, future=False):
        from .exporting import DEFAULT_OPTIONS,options
        if target not in ('items','all','future'):raise ValueError('Choose current tasks or future defaults.')
        if not isinstance(changes,dict) or not changes or set(changes)-(set(DEFAULT_OPTIONS)-{'full_rescan'}):
            raise ValueError('Choose supported settings to change. Full-history rescans remain explicit Export actions.')
        normalized=options(changes)
        patch={k:normalized[k] for k in changes}
        if ids is not None and (not isinstance(ids,list) or len(ids)>20000 or any(not isinstance(i,str) for i in ids)):
            raise ValueError('Choose a bounded list of queue tasks.')
        with self.queue_lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=[]
            if target=='all':
                rows=db.execute("SELECT * FROM jobs WHERE owner_id=? AND id<>? AND status IN ('queued','waiting','paused','blocked','failed')",(owner,self.processing_job or '')).fetchall()
            elif target=='items':
                if not ids:raise ValueError('Select one or more tasks.')
                for jid in dict.fromkeys(ids):
                    row=db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
                    if not row or row['owner_id']!=owner:raise ValueError('A selected task is missing or belongs to another account.')
                    if row['id']==self.processing_job or row['status'] not in ('queued','waiting','paused','blocked','failed'):
                        raise ValueError('A selected task started exporting or is no longer editable. Refresh the queue.')
                    rows.append(row)
            replacements=[]
            for row in rows:
                old=json.loads(row['options']);new=options(dict(old,**patch))
                new['_queue_overrides']=sorted(set(old.get('_queue_overrides',[]))|set(patch))
                replacements.append((packed(new),row['id']))
            for opts,jid in replacements:
                db.execute("UPDATE jobs SET options=?,detail='Settings updated; checkpoint and current rest preserved.' WHERE id=?",(opts,jid))
            if target=='future' or future:
                key='queue_defaults:'+owner
                old=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
                merged=dict(json.loads(old['value']) if old else {},**patch)
                options(merged)
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,packed(merged)))
            return {'changed':len(rows),'future':target=='future' or bool(future)}

    def save_queue_preferences(self, owner, value):
        from .exporting import options
        if not isinstance(value,dict):raise ValueError('Settings must be an object.')
        opts=options(value.get('options'));opts={k:v for k,v in opts.items() if not k.startswith('_')}
        opts['full_rescan']=False
        scope=value.get('scope','server');mode=value.get('mode','fixed')
        if scope not in ('server','channel') or mode not in ('fixed','adaptive'):raise ValueError('Invalid schedule controls.')
        saved={'options':opts,'scope':scope,'mode':mode,'minutes':max(10,min(int(value.get('minutes',1440)),10080)),
               'use_defaults':bool(value.get('use_defaults',True)),'advanced':bool(value.get('advanced',False)),
               'updated':float(value.get('updated',time.time()*1000))}
        import math
        if not math.isfinite(saved['updated']):raise ValueError('Invalid settings timestamp.')
        key='queue_preferences:'+owner
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            old=json.loads(row['value']) if row else {}
            if old.get('updated',0)>saved['updated']:return old
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,packed(saved)))
        return saved

    def schedule(self, scope, owner, enabled, mode, minutes, options):
        options = dict(options,full_rescan=False)
        if not scope.startswith(('server:', 'channel:')):
            raise ValueError('Schedule scope must be a server or channel.')
        valid_id(scope.split(':', 1)[1])
        if mode not in ('fixed', 'adaptive'):
            raise ValueError('Choose a fixed or adaptive schedule.')
        minutes = max(10, min(int(minutes), 10080))
        if mode == 'adaptive' and scope.startswith('channel:'):
            minutes = self.interval(scope.split(':',1)[1])['minutes']
        with self.db() as db:
            key='schedule_exclusions:'+owner
            row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            excluded=json.loads(row['value']) if row else []
            if scope in excluded:
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,packed([s for s in excluded if s!=scope])))
            db.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?,?,?,?,?)',
                       (scope, owner, int(bool(enabled)), mode, minutes, packed(options), time.time()+minutes*60))

    def manage_schedules(self, owner, action, scopes=None):
        if action not in ('pause','enable','remove','clear','restore'):
            raise ValueError('Unknown schedule action.')
        if not isinstance(scopes or [],list) or len(scopes or [])>20000 or any(not isinstance(s,str) for s in scopes or []):
            raise ValueError('Choose a bounded list of schedules.')
        key='schedule_exclusions:'+owner
        recovery='removed_schedules:'+owner
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows={r['scope']:dict(r) for r in db.execute('SELECT * FROM schedules')}
            record=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            excluded=set(json.loads(record['value']) if record else [])
            if action=='restore':
                record=db.execute('SELECT value FROM settings WHERE key=?',(recovery,)).fetchone()
                restored=0
                for row in json.loads(record['value']) if record else []:
                    if row['owner_id']!=owner or row['scope'] in rows:continue
                    db.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?)',tuple(row[k] for k in ('scope','owner_id','enabled','mode','minutes','options','next_run')))
                    excluded.discard(row['scope']);restored+=1
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(recovery,packed([])))
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,packed(sorted(excluded))))
                return {'changed':restored}
            wanted={r['scope'] for r in rows.values() if r['owner_id']==owner} if action=='clear' else set(scopes or [])
            for scope in wanted:
                if not isinstance(scope,str) or not scope.startswith(('server:','channel:')):raise ValueError('Invalid schedule selection.')
                valid_id(scope.split(':',1)[1])
                if scope in rows and rows[scope]['owner_id']!=owner:raise ValueError('A selected schedule belongs to another account.')
            chosen={s for s in wanted if s in rows}
            parents={s.split(':',1)[1] for s in chosen if s.startswith('server:')}
            channels={r['id']:r['server_id'] for r in db.execute('SELECT id,server_id FROM channels')}
            for scope,row in rows.items():
                if row['owner_id']==owner and scope.startswith('channel:') and channels.get(scope.split(':',1)[1]) in parents and json.loads(row['options']).get('inherited'):
                    chosen.add(scope)
            if action in ('remove','clear'):
                if chosen:
                    db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(recovery,packed([rows[s] for s in sorted(chosen)])))
                for scope in chosen:
                    db.execute('DELETE FROM schedules WHERE scope=?',(scope,))
                    if scope.startswith('channel:'):excluded.add(scope)
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,packed(sorted(excluded))))
            else:
                now=time.time()
                for scope in chosen:
                    row=rows[scope];opts=json.loads(row['options'])
                    if scope in wanted and scope.startswith('channel:'):opts['inherited']=False
                    next_run=now+row['minutes']*60 if action=='enable' and not row['enabled'] else row['next_run']
                    db.execute('UPDATE schedules SET enabled=?,options=?,next_run=? WHERE scope=?',(int(action=='enable'),packed(opts),next_run,scope))
            return {'changed':len(chosen)}

    def schedules(self):
        with self.db() as db:
            return [dict(r, options=json.loads(r['options'])) for r in db.execute('SELECT * FROM schedules')]

    def interval(self, channel_id):
        with self.db() as db:
            row = db.execute("SELECT count(*),min(timestamp),max(timestamp) FROM messages WHERE channel_id=? AND timestamp>=strftime('%Y-%m-%dT%H:%M:%fZ','now','-7 days')", (channel_id,)).fetchone()
            channel = db.execute('SELECT history_done FROM channels WHERE id=?', (channel_id,)).fetchone()
        count = row[0]
        covered_minutes = 10080
        if count and channel and not channel['history_done']:
            earliest = datetime.fromisoformat(row[1].replace('Z','+00:00'))
            covered_minutes = max(5,min(10080,(datetime.now(timezone.utc)-earliest).total_seconds()/60))
        # Aim for about 50 new messages per sweep. Empty/quiet channels settle at seven days.
        minutes = max(10, min(10080, round(50*covered_minutes/max(1, count))))
        return {'minutes': minutes, 'sample_messages': count, 'sample_days': 7, 'covered_minutes':round(covered_minutes,2)}

    def stats(self):
        with self.db() as db:
            return {'messages': db.execute('SELECT count(*) FROM messages').fetchone()[0],
                    'people': db.execute('SELECT count(*) FROM users').fetchone()[0],
                    'attachments': db.execute('SELECT count(*) FROM media').fetchone()[0],
                    'channels': db.execute('SELECT count(*) FROM channels WHERE generation>0').fetchone()[0],
                    'revisions': db.execute('SELECT count(*) FROM revisions').fetchone()[0]}
