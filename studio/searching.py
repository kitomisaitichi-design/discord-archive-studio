"""Literal local search and a progressively populated metadata index."""
import json
import re
from datetime import date


def expand(params):
    """Extract known operators only; URLs and quoted literal text remain literal."""
    result = dict(params)
    seen = set()
    def operator(match):
        name = match[1].lower()
        value = (match[2] if match[2] is not None else match[3]).strip()
        if not value or name in seen:
            raise ValueError('Use one non-empty '+name+': filter.')
        seen.add(name)
        field = {'from': 'person', 'in': 'scope_channel', 'server': 'scope_server',
                 'has': 'type', 'after': 'start', 'before': 'end', 'file': 'attachment'}[name]
        if name == 'has':
            value = {'attachment': 'any', 'attachments': 'any', 'images': 'image'}.get(value.lower(), value.lower())
            if value not in ('image', 'video', 'audio', 'midi', 'file', 'any'):
                raise ValueError('has: supports image, video, audio, midi, file or attachment.')
        if name in ('before', 'after'):
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value): raise ValueError()
                date.fromisoformat(value)
            except ValueError:
                raise ValueError(name+': needs a date such as 2026-01-31.') from None
        result[field] = value
        if name == 'from': result.pop('author', None)
        return ''
    def token(match):
        found = re.fullmatch(r'(from|in|server|has|before|after|file):(?:"([^"]*)"|(\S+))', match[0], re.I)
        return operator(found) if found else match[0]
    result['q'] = re.sub(r'(?:[^\s"]+|"[^"]*")+', token,
                         str(params.get('q') or '')[:500]).strip()
    return result


def scope_filter(params, *, zip_index=False, archive_name=''):
    where, args = [], []
    channel = params.get('scope_channel')
    if channel:
        column = 'm.channel' if zip_index else 'm.channel_id'
        where.append(column+' IN (SELECT id FROM channels WHERE '+('id=?' if channel.isdigit() else 'name=? COLLATE NOCASE')+')')
        args.append(channel.lstrip('#'))
    server = params.get('scope_server')
    if server:
        if zip_index:
            where.append('?=? COLLATE NOCASE'); args += [server, archive_name]
        else:
            where.append('m.channel_id IN (SELECT c.id FROM channels c JOIN servers s ON s.id=c.server_id WHERE '+('s.id=?' if server.isdigit() else 's.name=? COLLATE NOCASE')+')')
            args.append(server)
    return where, args


def suggestions(store, reader, params):
    operator = str(params.get('operator','')).lower()
    query = str(params.get('value',''))[:100]
    like = '%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    archive = params.get('archive')
    rows = []
    if operator in ('has','before','after'):
        values = ('image','video','audio','midi','file','attachment') if operator=='has' else (date.today().isoformat(),)
        return {'suggestions':[dict(value=value,label=value,detail='Attachment type' if operator=='has' else 'YYYY-MM-DD')
            for value in values if query.lower() in value.lower()]}
    if archive:
        from .reader_library import entry
        if not entry(store, archive):
            path, _, item = reader.index(archive)
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(path)) as db:
                if operator == 'in':
                    rows = [dict(value=r[0],label=r[1],detail='Saved ZIP channel') for r in db.execute(
                        "SELECT id,name FROM channels WHERE name LIKE ? ESCAPE '\\' OR id LIKE ? LIMIT 8",(like,like))]
                elif operator == 'from':
                    rows = [dict(value=r[0],label=r[1] or r[0],detail='Captured author · '+r[0]) for r in db.execute(
                        "SELECT DISTINCT json_extract(raw,'$.author.id'),coalesce(json_extract(raw,'$.author.global_name'),json_extract(raw,'$.author.username'),json_extract(raw,'$.author.name')) name FROM messages WHERE name LIKE ? ESCAPE '\\' OR json_extract(raw,'$.author.id') LIKE ? LIMIT 8",(like,like))]
                elif operator == 'server':
                    rows = [dict(value=item['name'],label=item['name'],detail='Current archive')]
            return {'suggestions':rows}
    with store.db() as db:
        if operator == 'from':
            rows = [dict(value=r['id'],label=r['name'],detail='Captured author · '+r['id']) for r in db.execute(
                "SELECT id,name FROM users WHERE name LIKE ? ESCAPE '\\' OR id LIKE ? OR id IN (SELECT user_id FROM author_names WHERE name LIKE ? ESCAPE '\\') ORDER BY name LIMIT 8",(like,like,like))]
        elif operator == 'in':
            rows = [dict(value=r['id'],label='# '+r['name'],detail=r['server']) for r in db.execute(
                "SELECT c.id,c.name,s.name server FROM channels c JOIN servers s ON s.id=c.server_id WHERE c.name LIKE ? ESCAPE '\\' OR c.id LIKE ? ORDER BY c.name LIMIT 8",(like.lstrip('#'),like))]
        elif operator == 'server':
            rows = [dict(value=r['id'],label=r['name'],detail='Saved server') for r in db.execute(
                "SELECT id,name FROM servers WHERE name LIKE ? ESCAPE '\\' OR id LIKE ? ORDER BY name LIMIT 8",(like,like))]
    return {'suggestions':rows}


def match_text(value, phrase=False):
    value=str(value or '').strip()[:500]
    tokens=[value] if phrase else re.findall(r'"([^"]+)"|(\S+)',value)
    if not phrase: tokens=[a or b for a,b in tokens][:30]
    return ' AND '.join('"'+t.replace('"','""')+'"' for t in tokens if t)


def file_group(name, kind=''):
    suffix=str(name).lower().rsplit('.',1)[-1]
    if suffix in ('png','jpg','jpeg','gif','webp','bmp','avif') or kind.startswith('image/'): return 'image'
    if suffix in ('mp4','webm','mov','mkv') or kind.startswith('video/'): return 'video'
    if suffix in ('mid','midi') or 'midi' in kind: return 'midi'
    if suffix in ('mp3','ogg','oga','m4a','aac','wav','flac','opus') or kind.startswith('audio/'): return 'audio'
    return 'file'


def facets(message):
    author=message.get('author') or {}
    names=' '.join(str(author.get(k) or '') for k in ('id','username','global_name','nickname','name'))
    attachments=message.get('attachments') or []
    files=' '.join(str(a.get('filename') or a.get('fileName') or '') for a in attachments)
    kinds=' '.join(sorted({group for a in attachments for group in (file_group(a.get('filename') or a.get('fileName') or '',str(a.get('content_type') or '')),file_group('',str(a.get('content_type') or '')))}))
    return names,files,kinds


def install(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS author_names(user_id TEXT,name TEXT,PRIMARY KEY(user_id,name));
      CREATE INDEX IF NOT EXISTS author_name_lookup ON author_names(name COLLATE NOCASE,user_id);
      CREATE VIRTUAL TABLE IF NOT EXISTS message_facets USING fts5(author,files,kinds,tokenize='unicode61');
      CREATE TRIGGER IF NOT EXISTS facets_delete AFTER DELETE ON messages BEGIN DELETE FROM message_facets WHERE rowid=old.rowid; END;
      CREATE TRIGGER IF NOT EXISTS facets_update AFTER UPDATE OF raw ON messages BEGIN DELETE FROM message_facets WHERE rowid=old.rowid; END;''')


def index_message(db, rowid, message):
    db.execute('DELETE FROM message_facets WHERE rowid=?',(rowid,))
    db.execute('INSERT INTO message_facets(rowid,author,files,kinds) VALUES(?,?,?,?)',(rowid,*facets(message)))
    author=message.get('author') or {}
    for key in ('username','global_name','nickname','name'):
        if author.get(key):db.execute('INSERT OR IGNORE INTO author_names VALUES(?,?)',(str(author.get('id','0')),str(author[key])))


def backfill(db, channel=None):
    # Each query advances a small local migration. Unindexed rows still participate
    # through JSON predicates below, so partially built indexes never hide results.
    where='m.rowid NOT IN (SELECT rowid FROM message_facets)'
    args=[]
    if channel: where+=' AND m.channel_id=?';args.append(channel)
    rows=db.execute('SELECT m.rowid,m.raw FROM messages m WHERE '+where+' LIMIT 500',args).fetchall()
    for row in rows:
        index_message(db,row[0],json.loads(row[1]))
    return len(rows)


def metadata_filter(params, *, zip_index=False):
    where,args=[],[]
    author=str(params.get('author') or params.get('person') or '').strip()[:200]
    filename=str(params.get('attachment') or '').strip()[:200]
    group=params.get('type','')
    if group not in ('','image','video','audio','midi','file','any'): raise ValueError('Unknown attachment type.')
    def literal(value): return '%'+value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    if author:
        if author.isdigit():
            if zip_index:
                where.append("json_extract(m.raw,'$.author.id')=?");args.append(author)
            else:
                where.append("(m.author_id=? OR m.author_id IN (SELECT user_id FROM aliases WHERE person_id=COALESCE((SELECT person_id FROM aliases WHERE user_id=?),?)))")
                args += [author,author,author]
        else:
            expression="coalesce(json_extract(m.raw,'$.author.username'),'')||' '||coalesce(json_extract(m.raw,'$.author.global_name'),'')||' '||coalesce(json_extract(m.raw,'$.author.nickname'),'')||' '||coalesce(json_extract(m.raw,'$.author.name'),'')"
            if zip_index:
                captured=expression.replace('m.raw','x.raw')
                where.append("json_extract(m.raw,'$.author.id') IN (SELECT json_extract(x.raw,'$.author.id') FROM messages x WHERE "+captured+" LIKE ? ESCAPE '\\')");args.append(literal(author))
            else:
                captured=expression.replace('m.raw','x.raw')
                where.append("(m.author_id IN (SELECT user_id FROM author_names WHERE name LIKE ? ESCAPE '\\') OR m.author_id IN (SELECT x.author_id FROM messages x WHERE x.rowid NOT IN (SELECT rowid FROM message_facets) AND ("+captured+" LIKE ? ESCAPE '\\')) OR m.author_id IN (SELECT id FROM users WHERE name LIKE ? ESCAPE '\\'))")
                args += [literal(author)]*3
    if filename or group:
        attachment_start = len(where)
        # JSON is the complete fallback for legacy caches; filenames and groups
        # are also indexed for current captures and progressively migrated rows.
        fields=[];values=[]
        if group and group!='any' and not zip_index:
            where.append('(m.rowid IN (SELECT rowid FROM message_facets WHERE message_facets MATCH ?) OR m.rowid NOT IN (SELECT rowid FROM message_facets))')
            args.append('kinds: "'+group+'"')
        if filename and not zip_index:
            where.append("(m.rowid IN (SELECT rowid FROM message_facets WHERE files LIKE ? ESCAPE '\\') OR m.rowid NOT IN (SELECT rowid FROM message_facets))")
            args.append(literal(filename))
        if filename:
            fields.append("coalesce(json_extract(j.value,'$.filename'),json_extract(j.value,'$.fileName'),'') LIKE ? ESCAPE '\\'")
            values.append(literal(filename))
        if group and group!='any':
            extensions={'image':['png','jpg','jpeg','gif','webp','bmp','avif'],'video':['mp4','webm','mov','mkv'],'audio':['mp3','ogg','oga','m4a','aac','wav','flac','opus'],'midi':['mid','midi']}
            name="lower(coalesce(json_extract(j.value,'$.filename'),json_extract(j.value,'$.fileName'),''))"
            mime="coalesce(json_extract(j.value,'$.content_type'),'')"
            checks=[]
            for ext in extensions.get(group,sum(extensions.values(),[])):
                checks.append(name+' LIKE ?');values.append('%.'+ext)
            if group in ('image','video','audio'): checks.append(mime+' LIKE ?');values.append(group+'/%')
            clause='('+' OR '.join(checks)+')'
            fields.append('NOT '+clause if group=='file' else clause)
        where.append("EXISTS (SELECT 1 FROM json_each(m.raw,'$.attachments') j"+(' WHERE '+' AND '.join(fields) if fields else '')+')')
        args+=values
        if group in ('image','any') or filename and not group:
            clauses = where[attachment_start:]
            del where[attachment_start:]
            where.append('('+' AND '.join(clauses)+" OR image_link(json_extract(m.raw,'$.content'),?)=1)")
            args.append(filename)
    for field,value,operator in [('timestamp' if not zip_index else 'stamp',params.get('start'),'>='),('timestamp' if not zip_index else 'stamp',params.get('end'),'<=')]:
        if value:
            where.append('m.'+field+operator+'?');args.append(str(value)+('T23:59:59.999999+00:00' if operator=='<=' and len(str(value))==10 else ''))
    return where,args
