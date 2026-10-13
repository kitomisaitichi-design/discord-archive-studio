"""Read the existing message index directly; no export, import, or network call."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from .avatars import avatar_key
from .store import packed, fingerprint


def library_id(server):
    return hashlib.sha256(('library:'+str(server)).encode()).hexdigest()


def entries(store):
    with store.db() as db:
        rows = db.execute('''SELECT s.id server_id,s.name,count(m.id) messages FROM servers s
            JOIN channels c ON c.server_id=s.id JOIN messages m ON m.channel_id=c.id GROUP BY s.id ORDER BY s.name''')
        return [dict(r,id=library_id(r['server_id']),name='Saved library · '+r['name'],source='library',
                     path=str(store.path),available=True,size=store.path.stat().st_size) for r in rows]


def cursor(row):
    return base64.urlsafe_b64encode(packed([row['timestamp'],len(row['id']),row['id']]).encode()).decode()


def decode_cursor(value):
    try:
        result = json.loads(base64.b64decode(str(value),altchars=b'-_',validate=True))
        if not isinstance(result,list) or len(result)!=3 or not isinstance(result[0],str) or not isinstance(result[1],int) or not re.fullmatch(r'\d{1,22}',result[2]): raise ValueError()
        return result
    except (ValueError,TypeError,UnicodeError):
        raise ValueError('Invalid saved-library message cursor.') from None


def overview(store, entry):
    with store.db() as db:
        rows=list(db.execute('''SELECT c.id,c.name,c.generation,count(m.id) messages,
            date(min(m.timestamp)) first,date(max(m.timestamp)) last FROM channels c
            JOIN messages m ON m.channel_id=c.id WHERE c.server_id=? GROUP BY c.id ORDER BY c.name''',(entry['server_id'],)))
    generation=fingerprint([(r['id'],r['name'],r['generation'],r['messages']) for r in rows])
    return {'archive':entry,'generation':generation,'channels':[dict(r) for r in rows],'warnings':[]}


def query(store, entry, kind, params, avatars):
    data=overview(store,entry)
    if kind=='overview':return data
    cid=params.get('channel','')
    if not any(c['id']==cid for c in data['channels']):raise ValueError('Choose a saved channel in this library.')
    with store.db() as db:
        if kind=='calendar':
            month=params.get('month','');day=params.get('day','')
            start=datetime.strptime(month+'-01','%Y-%m-%d').replace(tzinfo=timezone.utc)
            end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
            # Existing timestamps can retain offsets; widened index bounds include those edge days.
            days=[dict(r) for r in db.execute('''SELECT date(timestamp) day,count(*) messages FROM messages
                WHERE channel_id=? AND timestamp>=? AND timestamp<? AND strftime('%Y-%m',timestamp)=? GROUP BY day''',
                (cid,(start-timedelta(days=1)).isoformat(),(end+timedelta(days=1)).isoformat(),month))]
            hours=[]
            if day:
                date=datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=timezone.utc)
                hours=[dict(r) for r in db.execute('''SELECT cast(strftime('%H',timestamp) AS INTEGER) hour,count(*) messages FROM messages
                    WHERE channel_id=? AND timestamp>=? AND timestamp<? AND date(timestamp)=? GROUP BY hour''',
                    (cid,(date-timedelta(days=1)).isoformat(),(date+timedelta(days=2)).isoformat(),day))]
            return {'generation':data['generation'],'days':days,'hours':hours}
        if kind!='messages':raise ValueError('Unknown reader operation.')
        limit=min(80,max(1,int(params.get('limit',80))))
        terms=params.get('q','').strip()[:500]
        base,args='m.channel_id=?',[cid]
        if terms:
            match=' AND '.join('"'+t.replace('"','""')+'"' for t in terms.split())
            like='%'+terms.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            authors=[r[0] for r in db.execute("SELECT id FROM users WHERE name LIKE ? ESCAPE '\\' LIMIT 1000",(like,))]
            if authors:
                base+=' AND (m.rowid IN (SELECT rowid FROM message_fts WHERE message_fts MATCH ?) OR m.author_id IN ('+','.join('?' for _ in authors)+'))'
                args += [match,*authors]
            else:
                base+=' AND m.rowid IN (SELECT rowid FROM message_fts WHERE message_fts MATCH ?)';args.append(match)
        total=db.execute('SELECT count(*) FROM messages m WHERE '+base,args).fetchone()[0]
        where,values=base,list(args);reverse=False
        if params.get('before') or params.get('after'):
            reverse=bool(params.get('before'))
            anchor=decode_cursor(params.get('before') or params['after'])
            where+=' AND (m.timestamp,length(m.id),m.id)'+('<' if reverse else '>')+'(?,?,?)';values+=anchor
        elif params.get('message'):
            row=db.execute('SELECT * FROM messages WHERE channel_id=? AND id=?',(cid,str(params['message']))).fetchone()
            if not row:raise ValueError('The referenced message has not been saved in this channel.')
            where+=' AND (m.timestamp,length(m.id),m.id)>=(?,?,?)';values += [row['timestamp'],len(row['id']),row['id']]
        elif params.get('day') and not terms:
            hour=min(23,max(0,int(params.get('hour',0))))
            start=datetime.strptime(params['day'],'%Y-%m-%d').replace(hour=hour,tzinfo=timezone.utc)
            where+=' AND m.timestamp>=? AND julianday(m.timestamp)>=julianday(?)'
            values += [(start-timedelta(days=1)).isoformat(),start.isoformat()]
        direction='DESC' if reverse else 'ASC'
        rows=list(db.execute('SELECT m.* FROM messages m WHERE '+where+' ORDER BY m.timestamp '+direction+',length(m.id) '+direction+',m.id '+direction+' LIMIT ?',values+[limit]))
        if reverse:rows.reverse()
        before=after=False
        if rows:
            for label,row,operator in [('before',rows[0],'<'),('after',rows[-1],'>')]:
                present=bool(db.execute('SELECT 1 FROM messages m WHERE '+base+' AND (m.timestamp,length(m.id),m.id)'+operator+'(?,?,?) LIMIT 1',args+[row['timestamp'],len(row['id']),row['id']]).fetchone())
                if label=='before':before=present
                else:after=present
        wanted={str(a.get('id')) for row in rows for a in json.loads(row['raw']).get('attachments',[])}
        media={r['attachment_id']:dict(r) for r in db.execute('SELECT * FROM media WHERE attachment_id IN ('+','.join('?' for _ in wanted)+')',list(wanted))} if wanted else {}
    cached=avatars.cached();messages=[];name=next(c['name'] for c in data['channels'] if c['id']==cid)
    for row in rows:
        m=dict(json.loads(row['raw']),channel_name=name,channel_id=cid,_seq=cursor(row))
        key=avatar_key(m.get('author',{}))
        if key and key[0] in cached:m['_avatar']=cached[key[0]]['hash']
        for a in m.get('attachments',[]):
            saved=media.get(str(a.get('id')))
            if saved and (store.root/saved['relative_path']).is_file():a['_asset']=saved['hash']
        messages.append(m)
    return {'generation':data['generation'],'messages':messages,'total':total,'before':before,'after':after,
            'first':cursor(rows[0]) if rows else '', 'last':cursor(rows[-1]) if rows else ''}


def asset(store, asset_id):
    if not re.fullmatch('[a-f0-9]{64}',str(asset_id)):raise ValueError('Invalid saved file.')
    with store.db() as db:
        avatar=db.execute('SELECT kind FROM avatars WHERE hash=? LIMIT 1',(asset_id,)).fetchone()
        media=db.execute('SELECT relative_path FROM media WHERE hash=? LIMIT 1',(asset_id,)).fetchone()
    path=store.root/'avatars'/asset_id if avatar else store.root/media['relative_path'] if media else None
    if not path or not path.is_file():raise ValueError('This file is not saved in the working library.')
    if path.stat().st_size>10_000_000:raise ValueError('This file exceeds the reader preview cap.')
    raw=path.read_bytes()
    from .avatars import image_kind
    return image_kind(raw) or 'application/octet-stream',raw
