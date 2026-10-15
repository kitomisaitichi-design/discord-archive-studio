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


def entry(store,key):
    # Asset requests do not need to recount every saved message.
    with store.db() as db:rows=db.execute('SELECT id,name FROM servers').fetchall()
    for row in rows:
        if library_id(row['id'])==key:return {'id':key,'server_id':row['id'],'name':'Saved library · '+row['name'],'source':'library','path':str(store.path),'available':True,'size':store.path.stat().st_size}
    return None


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
    channels=store.channels(entry['server_id'])
    stamp=tuple((c['id'],c['name'],c['generation'],c['count']) for c in channels)
    return store.metadata_cache.get(('overview',entry['server_id'],stamp),lambda:_overview(store,entry))


def _overview(store, entry):
    with store.db() as db:
        rows=list(db.execute('''SELECT c.id,c.name,c.generation,count(m.id) messages,
            date(min(m.timestamp)) first,date(max(m.timestamp)) last FROM channels c
            JOIN messages m ON m.channel_id=c.id WHERE c.server_id=? GROUP BY c.id ORDER BY c.name''',(entry['server_id'],)))
    generation=fingerprint([(r['id'],r['name'],r['generation'],r['messages']) for r in rows])
    return {'archive':entry,'generation':generation,'channels':[dict(r) for r in rows],'warnings':[]}


def query(store, entry, kind, params, avatars):
    if kind=='calendar':
        generation=overview(store,entry)['generation']
        return store.metadata_cache.get(('calendar',entry['server_id'],generation,params.get('channel'),params.get('month'),params.get('day')),
            lambda:_query(store,entry,kind,params,avatars))
    return _query(store,entry,kind,params,avatars)


def _query(store, entry, kind, params, avatars):
    if kind == 'messages':
        from .searching import expand
        params = expand(params)
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
            from .searching import match_text
            match=match_text(terms,params.get('phrase')=='1')
            like='%'+terms.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            authors=[r[0] for r in db.execute("SELECT id FROM users WHERE name LIKE ? ESCAPE '\\' LIMIT 1000",(like,))]
            if authors:
                base+=' AND (m.rowid IN (SELECT rowid FROM message_fts WHERE message_fts MATCH ?) OR m.author_id IN ('+','.join('?' for _ in authors)+'))'
                args += [match,*authors]
            else:
                base+=' AND m.rowid IN (SELECT rowid FROM message_fts WHERE message_fts MATCH ?)';args.append(match)
        from .searching import metadata_filter,backfill,match_text
        if params.get('phrase')=='1' and terms:
            args[0]=cid
            if len(args)>1:args[1]=match_text(terms,True)
        filters,values=metadata_filter(params)
        from .searching import scope_filter
        scopes, scope_values = scope_filter(params)
        filters += scopes; values += scope_values
        if filters:
            backfill(db,cid);base+=' AND '+' AND '.join(filters);args+=values
        identity_stamp=tuple(tuple(r) for r in db.execute('SELECT user_id,person_id FROM aliases ORDER BY user_id')) if params.get('author') or params.get('person') else ()
        total=store.metadata_cache.get(('search-total',cid,data['generation'],identity_stamp,base,tuple(args)),
            lambda:db.execute('SELECT count(*) FROM messages m WHERE '+base,args).fetchone()[0])
        where,values=base,list(args);reverse=False
        if params.get('before') or params.get('after'):
            reverse=bool(params.get('before'))
            anchor=decode_cursor(params.get('before') or params['after'])
            where+=' AND (m.timestamp,length(m.id),m.id)'+('<' if reverse else '>')+'(?,?,?)';values+=anchor
        elif params.get('message'):
            row=db.execute('SELECT * FROM messages WHERE channel_id=? AND id=?',(cid,str(params['message']))).fetchone()
            if not row:raise ValueError('The referenced message has not been saved in this channel.')
            # Include a small amount of preceding context, using the existing local index.
            context=list(db.execute('SELECT id,timestamp FROM messages WHERE channel_id=? AND (timestamp,length(id),id)<=(?,?,?) ORDER BY timestamp DESC,length(id) DESC,id DESC LIMIT ?',
                (cid,row['timestamp'],len(row['id']),row['id'],11 if params.get('surrounding')=='1' else 1)))
            first=context[-1]
            where+=' AND (m.timestamp,length(m.id),m.id)>=(?,?,?)';values += [first['timestamp'],len(first['id']),first['id']]
        elif params.get('day') and not terms and not any(params.get(k) for k in ('author','person','attachment','type','start','end','scope_channel','scope_server')):
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
    cached=avatars.cached();images=store.images.saved();messages=[];name=next(c['name'] for c in data['channels'] if c['id']==cid)
    for row in rows:
        m=dict(json.loads(row['raw']),channel_name=name,channel_id=cid,_seq=cursor(row))
        from .linked_images import image_links
        m['_linked_images'] = {url:images[url]['hash'] for url in image_links(m.get('content','')) if url in images}
        key=avatar_key(m.get('author',{}))
        if key and key[0] in cached:m['_avatar']=cached[key[0]]['hash']
        for a in m.get('attachments',[]):
            saved=media.get(str(a.get('id')))
            if saved and (store.root/saved['relative_path']).is_file():a['_asset']=saved['hash']
        messages.append(m)
    return {'generation':data['generation'],'messages':messages,'total':total,'before':before,'after':after,
            'first':cursor(rows[0]) if rows else '', 'last':cursor(rows[-1]) if rows else ''}


def asset_location(store, asset_id):
    if not re.fullmatch('[a-f0-9]{64}',str(asset_id)):raise ValueError('Invalid saved file.')
    with store.db() as db:
        avatar=db.execute('SELECT kind FROM avatars WHERE hash=? LIMIT 1',(asset_id,)).fetchone()
        media=db.execute('SELECT relative_path,filename FROM media WHERE hash=? LIMIT 1',(asset_id,)).fetchone()
    path=store.root/'avatars'/asset_id if avatar else store.root/media['relative_path'] if media else None
    if not path or not path.is_file():raise ValueError('This file is not saved in the working library.')
    if path.stat().st_size>100_000_000:raise ValueError('This file exceeds the reader preview cap.')
    if not path.resolve().is_relative_to(store.root.resolve()):raise ValueError('Invalid local media path.')
    from .local_media import mime
    with path.open('rb') as source:head=source.read(32)
    kind=mime(media['filename'] if media else '',head)
    if kind.startswith('video/') and path.stat().st_size>10_000_000:raise ValueError('Video exceeds the 10 MB preview cap.')
    return kind,path


def asset(store, asset_id):
    kind,path=asset_location(store,asset_id)
    return kind,path.read_bytes()
