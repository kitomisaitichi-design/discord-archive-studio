"""Captured author identity and names only; no remote member enumeration."""
import json
from contextlib import closing
import sqlite3
from .store import valid_id
from . import reader_library


def author_view(store, reader, user_id, archive=''):
    uid=valid_id(user_id)
    entry=reader_library.entry(store,archive) if archive else None
    if archive and not entry:
        path,generation,_=reader.index(archive)
        with closing(sqlite3.connect(path)) as db:
            db.row_factory=sqlite3.Row
            db.execute("CREATE INDEX IF NOT EXISTS captured_author_id ON messages(CAST(json_extract(raw,'$.author.id') AS TEXT))")
            # SQLite's captured JSON index avoids constructing all message objects.
            rows=db.execute("SELECT DISTINCT author FROM messages WHERE CAST(json_extract(raw,'$.author.id') AS TEXT)=? LIMIT 40",(uid,)).fetchall()
            count=db.execute("SELECT count(*) FROM messages WHERE CAST(json_extract(raw,'$.author.id') AS TEXT)=?",(uid,)).fetchone()[0]
        return {'id':uid,'name':rows[0]['author'] if rows else uid,'names':[r['author'] for r in rows], 'messages':count,'linked_ids':[],'source':'Saved ZIP'}
    with store.db() as db:
        user=db.execute('SELECT name FROM users WHERE id=?',(uid,)).fetchone()
        names=[r[0] for r in db.execute('SELECT name FROM author_names WHERE user_id=? ORDER BY name LIMIT 40',(uid,))]
        if user and user['name'] not in names:names.insert(0,user['name'])
        count=db.execute('SELECT count(*) FROM messages WHERE author_id=?',(uid,)).fetchone()[0]
        links=[r[0] for r in db.execute('SELECT user_id FROM aliases WHERE person_id=? UNION SELECT person_id FROM aliases WHERE user_id=?',(uid,uid))]
    return {'id':uid,'name':user['name'] if user else uid,'names':names,'messages':count,'linked_ids':links,'source':'Captured local library'}
