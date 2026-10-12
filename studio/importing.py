"""Import DiscordChatExporter JSON/HTML/TXT or Studio ZIPs; never execute export HTML."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
import re
import os
import tempfile
import zipfile
from .store import valid_id, packed


def synthetic(value):
    return str(900000000000000000000 + int(hashlib.sha256(value.encode()).hexdigest()[:16], 16))


def timestamp_from_id(value):
    return datetime.fromtimestamp(((int(value) >> 22)+1420070400000)/1000, timezone.utc).isoformat()


class DceHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.messages = []
        self.author = {'id': '0', 'username': 'Unknown'}
        self.message = None
        self.text_depth = self.author_depth = None
        self.author_text = []
        self.body = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        classes = set(attr.get('class', '').split())
        if tag not in ('br', 'img', 'hr', 'meta', 'link', 'input', 'source', 'wbr'):
            self.stack.append((tag, classes))
        if 'chatlog__author' in classes or 'chatlog__system-notification-author' in classes:
            self.author = {'id': attr.get('data-user-id') or synthetic('author:'+attr.get('title', 'Unknown')), 'username': attr.get('title', 'Unknown')}
            self.author_depth = len(self.stack)
            self.author_text = []
        if 'chatlog__message-container' in classes:
            mid = attr.get('data-message-id') or attr.get('id', '').removeprefix('message-')
            if mid.isdigit():
                self.message = {'id': mid, 'author': dict(self.author), 'timestamp': timestamp_from_id(mid), 'content': '', 'attachments': []}
                self.message_depth = len(self.stack)
                self.body = []
        if self.message and classes & {'chatlog__markdown-preserve', 'chatlog__system-notification-content'}:
            self.text_depth = len(self.stack)
        if self.text_depth and tag == 'br':
            self.body.append('\n')
        if self.message and 'chatlog__reply-link' in classes:
            match = re.search(r'\d{17,22}', attr.get('onclick', ''))
            if match:
                self.message['message_reference'] = {'message_id': match.group()}
        if self.message and ('chatlog__attachment' in classes or any('chatlog__attachment' in c for _, c in self.stack)):
            url = attr.get('href') or attr.get('src')
            if url and not any(a['url']==url for a in self.message['attachments']):
                self.message['attachments'].append({'id': synthetic('attachment:'+url.split('?', 1)[0]), 'url': url,
                                                   'filename': url.split('?', 1)[0].rsplit('/', 1)[-1]})

    def handle_data(self, data):
        if self.author_depth:
            self.author_text.append(data)
        if self.text_depth:
            self.body.append(data)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        # Tolerate malformed nested markup without executing script or constructing a browser DOM.
        index = next((i for i in range(len(self.stack)-1, -1, -1) if self.stack[i][0] == tag), None)
        if index is None:
            return
        depth = index+1
        if self.author_depth and depth <= self.author_depth:
            self.author['global_name'] = ''.join(self.author_text).strip() or self.author['username']
            self.author_depth = None
        if self.text_depth and depth <= self.text_depth:
            self.text_depth = None
        if self.message and depth <= self.message_depth:
            self.message['content'] = ''.join(self.body).strip()
            self.messages.append(self.message)
            self.message = None
        self.stack = self.stack[:index]


def parse_json(text):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get('messages'), list):
        raise ValueError('JSON must contain a DiscordChatExporter/Studio messages array.')
    channel = data.get('channel') or {}
    guild = data.get('guild') or {'id': '0', 'name': 'Imported direct messages'}
    cid = valid_id(channel.get('id'))
    sid = valid_id(guild.get('id') or '0')
    result = []
    for original in data['messages']:
        m = dict(original)
        valid_id(m.get('id'))
        a = dict(m.get('author') or {})
        valid_id(a.get('id'))
        a.setdefault('username', a.get('name', 'Unknown'))
        a.setdefault('global_name', a.get('nickname') or a.get('name'))
        color = a.get('color')
        if isinstance(color,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',color):
            a['role_color'] = int(color[1:],16)
        m['author'] = a
        m['channel_id'] = cid
        m['edited_timestamp'] = m.get('edited_timestamp') or m.get('timestampEdited')
        if m.get('reference'):
            m['message_reference'] = {'message_id': m['reference'].get('messageId')}
        for attachment in m.get('attachments', []):
            attachment.setdefault('filename', attachment.get('fileName', 'Attachment'))
        # Validate timestamps before anything is committed.
        datetime.fromisoformat(m['timestamp'].replace('Z', '+00:00'))
        result.append(m)
    return {'id': sid, 'name': guild.get('name', 'Imported server')}, {'id': cid, 'guild_id': sid, 'name': channel.get('name', cid), 'type': 0}, result


def parse_txt(text, filename):
    header = '\n'.join(text.splitlines()[:12])
    guild = re.search(r'^Guild:\s*(.*)', header, re.M)
    channel = re.search(r'^Channel:\s*(.*)', header, re.M)
    scope = (guild.group(1) if guild else 'Imported text')+'|'+(channel.group(1) if channel else filename)
    sid, cid = synthetic('txt-server:'+scope.split('|')[0]), synthetic('txt-channel:'+scope)
    messages, current, parts, occurrences = [], None, [], {}
    def flush():
        if current:
            current['content'] = '\n'.join(parts).strip()
            # Preserve repeated identical messages using their occurrence number, not only a content hash.
            key = packed(current)
            occurrences[key] = occurrences.get(key, 0)+1
            current['id'] = synthetic(scope+key+str(occurrences[key]))
            messages.append(dict(current))
    for line in text.splitlines():
        match = re.match(r'^\[(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)\]\s+(.+)$', line)
        if match:
            flush()
            stamp = datetime.strptime(match[1], '%m/%d/%Y %I:%M %p').replace(tzinfo=timezone.utc).isoformat()
            current = {'author': {'id': synthetic(scope+'author:'+match[2]), 'username': match[2]}, 'timestamp': stamp, 'content': '', 'channel_id': cid}
            parts = []
        elif re.match(r'^={40,}$', line.strip()):
            flush()
            current = None
            parts = []
        elif current:
            parts.append(line)
    flush()
    if not messages:
        raise ValueError('TXT has no recognized US-locale DCE message headers. Prefer JSON; source was not changed.')
    return {'id': sid, 'name': scope.split('|')[0]}, {'id': cid, 'guild_id': sid, 'name': scope.split('|')[1], 'type': 0}, messages


def import_data(store, content, filename):
    digest = hashlib.sha256(content).hexdigest()
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS imports(hash TEXT PRIMARY KEY,name TEXT,kind TEXT,created REAL)')
        if db.execute('SELECT 1 FROM imports WHERE hash=?', (digest,)).fetchone():
            return {'added': 0, 'edited': 0, 'unchanged': True, 'warnings': []}
    payloads, warnings, media_payloads = [], [], []
    if filename.lower().endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            candidates = [i for i in archive.infolist() if i.filename.lower().endswith('.json') and not i.filename.endswith('manifest.json')]
            if sum(i.file_size for i in candidates) > 512*1024*1024 or any(i.file_size > 128*1024*1024 for i in candidates):
                raise ValueError('Archive JSON exceeds import limits. Import smaller parts separately.')
            for entry in candidates:
                text = archive.read(entry).decode('utf-8-sig')
                try:
                    payloads.append(parse_json(text))
                except (ValueError, KeyError, TypeError):
                    warnings.append('Not a message export: '+entry.filename)
            if not payloads:
                raise ValueError('This ZIP has no recognized JSON message exports. Select JSON for portable re-import.')
            # Restore only hashed Studio objects referenced by parsed messages. Never extract arbitrary ZIP paths.
            names = set(archive.namelist())
            wanted = {}
            for _, _, messages in payloads:
                for message in messages:
                    for attachment in message.get('attachments', []):
                        match = re.fullmatch(r'(?:\.\./)*media/([a-f0-9]{64})', attachment.get('local_path',''))
                        if match and 'media/'+match[1] in names:
                            wanted[str(attachment.get('id'))]=(match[1],attachment.get('filename','Attachment'))
            total = sum(archive.getinfo('media/'+digest).file_size for digest in {value[0] for value in wanted.values()})
            if total > 512*1024*1024:
                raise ValueError('ZIP media exceeds the 512 MB import limit; import JSON parts or smaller ZIPs.')
            media_cache = {}
            for aid,(object_hash,name) in wanted.items():
                raw = media_cache.get(object_hash)
                if raw is None:
                    raw = archive.read('media/'+object_hash)
                    media_cache[object_hash] = raw
                if hashlib.sha256(raw).hexdigest()!=object_hash:
                    raise ValueError('Studio ZIP contains a media object whose content hash does not match.')
                media_payloads.append((aid,object_hash,name,raw))
    else:
        text = content.decode('utf-8-sig')
        if filename.lower().endswith('.json'):
            payloads.append(parse_json(text))
        elif filename.lower().endswith(('.html', '.htm')):
            parser = DceHTML()
            parser.feed(text)
            if not parser.messages:
                raise ValueError('No DiscordChatExporter message containers were found. Prefer JSON.')
            link = re.search(r'https://discord\.com/channels/(\d+)/(\d+)', text)
            sid, cid = (link[1], link[2]) if link else (synthetic('html-server:'+filename), synthetic('html-channel:'+filename))
            payloads.append(({'id': sid, 'name': 'Imported HTML'}, {'id': cid, 'guild_id': sid, 'name': filename, 'type': 0}, parser.messages))
            warnings.append('HTML import retains message IDs and text; JSON is preferred for complete metadata.')
        elif filename.lower().endswith('.txt'):
            payloads.append(parse_txt(text, filename))
            warnings.append('TXT identity/deduplication is best effort; its clock is assumed UTC. It is kept separate from ID-based channels.')
        else:
            raise ValueError('Import JSON, DiscordChatExporter HTML/TXT, or a ZIP containing JSON exports.')
    totals = {'added': 0, 'edited': 0, 'warnings': warnings, 'unchanged': False}
    for aid, object_hash, name, raw in media_payloads:
        target=store.root/'media'/object_hash
        if not target.exists():
            handle,temp_name=tempfile.mkstemp(prefix='import-',dir=store.root)
            with os.fdopen(handle,'wb') as output:output.write(raw)
            os.replace(temp_name,target)
        with store.db() as db:
            db.execute('INSERT OR REPLACE INTO media VALUES(?,?,?,?,?)',(aid,object_hash,name,len(raw),'media/'+object_hash))
    # Parsing/validation completes before database mutation. Originals are never renamed/deleted.
    for guild, channel, messages in payloads:
        store.catalog([guild], [channel], guild['id'])
        quality = 2 if filename.lower().endswith(('.html','.htm')) else 1 if filename.lower().endswith('.txt') else 3
        change = store.upsert(channel['id'], messages, quality=quality)
        totals['added'] += change['added']
        totals['edited'] += change['edited']
    with store.db() as db:
        db.execute("INSERT OR REPLACE INTO imports VALUES(?,?,?,strftime('%s','now'))", (digest, filename, filename.rsplit('.', 1)[-1]))
    return totals
