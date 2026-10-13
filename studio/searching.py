"""Literal local search and a progressively populated metadata index."""
import json
import re


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
    for field,value,operator in [('timestamp' if not zip_index else 'stamp',params.get('start'),'>='),('timestamp' if not zip_index else 'stamp',params.get('end'),'<=')]:
        if value:
            where.append('m.'+field+operator+'?');args.append(str(value)+('T23:59:59.999999+00:00' if operator=='<=' and len(str(value))==10 else ''))
    return where,args
