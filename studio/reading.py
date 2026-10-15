"""Local read watermarks and frozen unread searches; never fetch conversation history."""
from collections import OrderedDict
import secrets
import threading
import time
from .store import valid_id


class Reading:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.snapshots = OrderedDict()
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS read_marks(scope TEXT,channel_id TEXT,
                stamp TEXT NOT NULL,message_id TEXT NOT NULL,updated REAL NOT NULL,
                PRIMARY KEY(scope,channel_id))''')

    def mark(self, selections, reader):
        if not isinstance(selections, list) or not 1 <= len(selections) <= 50:
            raise ValueError('Choose up to 50 visible saved messages.')
        validated = []
        from .reader_library import entry
        for selection in selections:
            cid, mid = valid_id(selection.get('channel', '')), valid_id(selection.get('message', ''))
            archive = str(selection.get('archive') or '')
            scope = 'library' if not archive or entry(self.store, archive) else archive
            if archive:
                message = reader.saved_messages(archive, cid, [mid]).get(mid)
                if not message:
                    raise ValueError('This visible message is not saved in the selected archive.')
                stamp = message['timestamp']
            else:
                with self.store.db() as db:
                    row = db.execute('SELECT timestamp FROM messages WHERE channel_id=? AND id=?', (cid, mid)).fetchone()
                if not row:
                    raise ValueError('This visible message is not saved in the library.')
                stamp = row[0]
            validated.append((scope, cid, stamp, mid))
        with self.store.db() as db:
            for scope, cid, stamp, mid in validated:
                db.execute('''INSERT INTO read_marks VALUES(?,?,?,?,?) ON CONFLICT(scope,channel_id)
                    DO UPDATE SET stamp=excluded.stamp,message_id=excluded.message_id,updated=excluded.updated
                    WHERE (excluded.stamp,length(excluded.message_id),excluded.message_id)>
                    (read_marks.stamp,length(read_marks.message_id),read_marks.message_id)''',
                    (scope, cid, stamp, mid, time.time()))
        return {'marked': len(validated)}

    def summary(self, channel=None):
        channels = self.store.channels()
        rows = []
        with self.store.db() as db:
            marks = {r['channel_id']: r for r in db.execute("SELECT * FROM read_marks WHERE scope='library'")}
            for c in channels:
                if channel and c['id'] != channel:
                    continue
                mark = marks.get(c['id'])
                boundary = (mark['stamp'], len(mark['message_id']), mark['message_id']) if mark else None
                def count():
                    if not boundary:
                        return c['count']
                    return db.execute('''SELECT count(*) FROM messages WHERE channel_id=? AND
                        (timestamp,length(id),id)>(?,?,?)''', (c['id'], *boundary)).fetchone()[0]
                unread = self.store.count_cache.get(('unread', c['id'], c['generation'], boundary), count)
                if unread:
                    item = dict(channel=c['id'], server=c['server_id'], name=c['name'], unread=unread)
                    if channel:
                        condition = ' AND (timestamp,length(id),id)>(?,?,?)' if boundary else ''
                        first = db.execute('SELECT id FROM messages WHERE channel_id=?'+condition+
                            ' ORDER BY timestamp,length(id),id LIMIT 1', (c['id'], *(boundary or ()))).fetchone()
                        item['first'] = first[0] if first else ''
                    rows.append(item)
        return {'total': sum(r['unread'] for r in rows), 'channels': rows}

    def snapshot(self):
        with self.store.db() as db:
            marks = [(r['channel_id'], r['stamp'], r['message_id']) for r in db.execute("SELECT * FROM read_marks WHERE scope='library'")]
        key = secrets.token_urlsafe(18)
        with self.lock:
            self.snapshots[key] = marks
            while len(self.snapshots) > 32:
                self.snapshots.popitem(last=False)
        return key

    def condition(self, db, key):
        with self.lock:
            if key not in self.snapshots:
                raise ValueError('This unread view expired. Refresh New since last read.')
            marks = self.snapshots[key]
            self.snapshots.move_to_end(key)
        db.execute('CREATE TEMP TABLE read_boundary(channel TEXT PRIMARY KEY,stamp TEXT,message TEXT)')
        db.executemany('INSERT INTO read_boundary VALUES(?,?,?)', marks)
        return '''NOT EXISTS (SELECT 1 FROM read_boundary b WHERE b.channel=m.channel_id AND
            (m.timestamp,length(m.id),m.id)<=(b.stamp,length(b.message),b.message))'''
