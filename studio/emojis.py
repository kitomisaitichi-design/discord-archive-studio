"""One captured custom emoji ID, one reusable local asset. No member lookups."""
import hashlib
import html
import os
import re
import tempfile
import time
from pathlib import Path
from .avatars import image_kind
from .discord import download

TOKEN = re.compile(r'<(a?):([A-Za-z0-9_]{1,100}):(\d{1,22})>')
CODE = re.compile(r'```[\s\S]*?(?:```|$)|`[^`\n]*(?:`|$)')


def text_parts(text):
    text=str(text or '');position=0
    for match in CODE.finditer(text):
        yield text[position:match.start()],False
        yield match[0],True
        position=match.end()
    yield text[position:],False


def references(message):
    found={}
    def add(eid,name,animated=False):
        if re.fullmatch(r'\d{1,22}',str(eid or '')):
            eid=str(eid);name=str(name or 'emoji')[:100]
            found[eid]={'id':eid,'name':name,'animated':bool(animated or found.get(eid,{}).get('animated')),'names':list(dict.fromkeys(found.get(eid,{}).get('names',[])+[name]))}
    def walk(m,depth=0):
        texts=[m.get('content','')]+[str(e.get(k) or '') for e in m.get('embeds',[]) for k in ('title','description')]
        for text in texts:
            for part,code in text_parts(text):
                if not code:
                    for token in TOKEN.finditer(part):add(token[3],token[2],token[1]=='a')
        for reaction in m.get('reactions',[]):
            emoji=reaction.get('emoji') or {};add(emoji.get('id'),emoji.get('name'),emoji.get('animated'))
        if depth<2 and isinstance(m.get('referenced_message'),dict):walk(m['referenced_message'],depth+1)
    walk(message)
    return found


def record(db,refs,server=None):
    for eid,e in refs.items():
        db.execute("INSERT INTO emojis VALUES(?,?,?,NULL,NULL,0,'deferred','Captured reference; waiting for capacity.',?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,animated=max(emojis.animated,excluded.animated)",(eid,e['name'],int(e['animated']),time.time()))
        for name in e.get('names',[e['name']]):db.execute('INSERT OR IGNORE INTO emoji_names VALUES(?,?)',(eid,name))
        if server is not None:db.execute('INSERT OR IGNORE INTO emoji_servers VALUES(?,?)',(eid,str(server)))


def reservation(db):
    media=db.execute("SELECT count(*),coalesce(sum(max_bytes),0) FROM media_requests WHERE status IN ('queued','running')").fetchone()
    avatars=db.execute("SELECT count(*) FROM avatar_tasks WHERE status IN ('queued','running')").fetchone()[0] if db.execute("SELECT 1 FROM sqlite_master WHERE name='avatar_tasks'").fetchone() else 0
    emoji=db.execute("SELECT count(*) FROM emojis WHERE status IN ('queued','running')").fetchone()[0]
    return min(50-media[0]-avatars-emoji,(100_000_000-media[1]-(avatars+emoji)*1_000_000)//1_000_000)


def content_text(text,assets=None,markdown=False):
    assets=assets or {}
    def replace(match):
        label=':'+match[2]+':';path=assets.get(match[3],'')
        if markdown and re.fullmatch(r'\.\./\.\./emojis/[a-f0-9]{64}',path):return '!['+label+']('+path+')'
        return label
    return ''.join(part if code else TOKEN.sub(replace,part) for part,code in text_parts(text))


def content_html(text,assets=None):
    assets=assets or {}
    def replace(match):
        label=':'+match[2]+':';path=assets.get(match[3],'')
        if re.fullmatch(r'\.\./\.\./emojis/[a-f0-9]{64}',path):
            return '<img class="custom-emoji" data-emoji-id="%s" src="%s" alt="%s" title="%s" loading="lazy">'%(match[3],path,html.escape(label,quote=True),html.escape(label,quote=True))
        return '<span class="custom-emoji-label">'+html.escape(label)+'</span>'
    rendered=[]
    for part,code in text_parts(text):
        if code:rendered.append(html.escape(part));continue
        position=0
        for match in TOKEN.finditer(part):
            rendered.extend((html.escape(part[position:match.start()]),replace(match)));position=match.end()
        rendered.append(html.escape(part[position:]))
    return ''.join(rendered)


class Emojis:
    def __init__(self,store):
        self.store=store;(store.root/'emojis').mkdir(exist_ok=True)

    def cached(self,ids=None):
        ids=list(ids) if ids is not None else None
        if ids==[]:return {}
        with self.store.db() as db:
            query='SELECT * FROM emojis WHERE hash IS NOT NULL'
            if ids is not None:query+=' AND id IN ('+','.join('?' for _ in ids)+')'
            return {r['id']:dict(r) for r in db.execute(query,ids or []) if (self.store.root/'emojis'/r['hash']).is_file()}

    def promote(self):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');available=max(0,reservation(db))
            ids=[r[0] for r in db.execute("SELECT id FROM emojis WHERE status='deferred' ORDER BY updated LIMIT ?",(available,))]
            for eid in ids:db.execute("UPDATE emojis SET status='queued',detail='Waiting for a committed text rest.' WHERE id=?",(eid,))

    def capture(self,messages,server=None):
        refs={};by_channel={}
        for m in messages:
            captured=references(m)
            by_channel.setdefault(str(m.get('channel_id','')),{}).update(captured)
            for eid,e in captured.items():
                e['names']=list(dict.fromkeys(refs.get(eid,{}).get('names',[])+e.get('names',[e['name']])))
                e['animated']=bool(e['animated'] or refs.get(eid,{}).get('animated'));refs[eid]=e
        with self.store.db() as db:
            record(db,refs,server)
            if server is None:
                for cid,subset in by_channel.items():
                    row=db.execute('SELECT server_id FROM channels WHERE id=?',(cid,)).fetchone()
                    if row:record(db,subset,row[0])
        self.promote();cached=self.cached(refs)
        with self.store.db() as db:
            result={eid:{'status':db.execute('SELECT status FROM emojis WHERE id=?',(eid,)).fetchone()[0],**({'url':'/emoji/'+cached[eid]['hash']} if eid in cached else {})} for eid in refs}
        return {'emojis':result}

    def task(self):
        self.promote()
        with self.store.db() as db:
            row=db.execute("SELECT * FROM emojis WHERE status='queued' ORDER BY updated LIMIT 1").fetchone()
            return dict(row) if row else None

    def update(self,eid,status,detail):
        with self.store.db() as db:db.execute('UPDATE emojis SET status=?,detail=?,updated=? WHERE id=?',(status,detail,time.time(),eid))

    def fetch(self,task,control):
        if task['id'] in self.cached([task['id']]):return
        url='https://cdn.discordapp.com/emojis/'+task['id']+('.gif' if task['animated'] else '.png')+'?size=48'
        handle,name=tempfile.mkstemp(dir=self.store.root,suffix='.partial');os.close(handle);temp=Path(name)
        try:
            size=download(url,temp,1_000_000,control)
            raw=temp.read_bytes();kind=image_kind(raw)
            if not kind:raise ValueError('Emoji response was not a supported raster image.')
            digest=hashlib.sha256(raw).hexdigest()
            with self.store.archive_lock:
                target=self.store.root/'emojis'/digest
                if target.exists():temp.unlink()
                else:os.replace(temp,target)
                with self.store.db() as db:db.execute('UPDATE emojis SET hash=?,kind=?,size=? WHERE id=?',(digest,kind,size,task['id']))
        finally:temp.unlink(missing_ok=True)

    def import_asset(self,eid,raw,name='emoji',animated=False):
        if not re.fullmatch(r'\d{1,22}',str(eid)) or len(raw)>1_000_000 or not image_kind(raw):return
        if str(eid) in self.cached([str(eid)]):return
        digest=hashlib.sha256(raw).hexdigest();handle,path=tempfile.mkstemp(dir=self.store.root,suffix='.partial');os.close(handle);temp=Path(path)
        try:
            temp.write_bytes(raw)
            with self.store.archive_lock:
                target=self.store.root/'emojis'/digest
                if target.exists():temp.unlink()
                else:os.replace(temp,target)
                with self.store.db() as db:
                    record(db,{str(eid):{'name':name,'animated':animated}})
                    db.execute("UPDATE emojis SET hash=?,kind=?,size=?,status='completed',detail='Reused embedded local ZIP graphic.' WHERE id=?",(digest,image_kind(raw),len(raw),str(eid)))
        finally:temp.unlink(missing_ok=True)
        dirty=self.store.setting('emoji_zip_dirty',[])
        self.store.set_setting('emoji_zip_dirty',list(dict.fromkeys(dirty+self.servers(str(eid)))))

    def servers(self,eid):
        with self.store.db() as db:return [r[0] for r in db.execute('SELECT server_id FROM emoji_servers WHERE emoji_id=?',(eid,))]

    def retry(self,ids):
        if not isinstance(ids,list) or not 1<=len(ids)<=50:raise ValueError('Select up to 50 captured emoji IDs.')
        with self.store.db() as db:
            for eid in ids:
                db.execute("UPDATE emojis SET status='deferred',detail='Explicit retry selected.',updated=? WHERE id=? AND status IN ('failed','paused')",(time.time(),str(eid)))
        self.promote()

    def library(self,q=''):
        with self.store.db() as db:
            term='%'+str(q)[:100]+'%'
            rows=[dict(r) for r in db.execute('SELECT * FROM emojis e WHERE name LIKE ? OR id=? OR EXISTS (SELECT 1 FROM emoji_names n WHERE n.emoji_id=e.id AND n.name LIKE ?) ORDER BY name LIMIT 100',(term,str(q)[:100],term))]
        for row in rows:
            if row['hash'] and (self.store.root/'emojis'/row['hash']).is_file():row['url']='/emoji/'+row['hash']
        return {'emojis':rows}
