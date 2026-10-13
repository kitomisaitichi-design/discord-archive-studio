import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
import time
import zipfile
from .store import fingerprint, packed
from .discord import download, Interrupted, MediaTooLarge
from .avatars import avatar_key


FORMAT_ORDER = ('json','html','md','txt')
DEFAULT_OPTIONS = {'formats': ['json', 'html'], 'download_media': True, 'include_attachments': True,
                   'reactions': True, 'edits': True, 'role_colors': True, 'split_count': 10000,
                   'split_mb': 0, 'exclude_bots': False, 'people': [], 'start': '', 'end': '',
                   'batch_messages': 1000, 'cooldown_minutes': 5, 'page_delay': 2.5, 'include_avatars': False,
                   'max_media_mb': 10, 'edit_lookback_days': 7, 'archived_threads': False, 'full_rescan': False, 'recheck_edits':False,'timing_variation':25}


def options(value):
    result = dict(DEFAULT_OPTIONS, **(value or {}))
    formats = result['formats']
    if not isinstance(formats, list) or not formats or set(formats)-{'html', 'json', 'md', 'txt'}:
        raise ValueError('Select at least one supported export format.')
    result['formats'] = [fmt for fmt in FORMAT_ORDER if fmt in formats]
    for name, low, high in [('split_count', 1, 100000), ('split_mb', 0, 1000), ('batch_messages', 100, 100000),
                            ('cooldown_minutes', 1, 1440), ('max_media_mb', 1, 100), ('edit_lookback_days', 1, 365),('timing_variation',0,100)]:
        result[name] = int(result[name])
        if not low <= result[name] <= high:
            raise ValueError('%s must be between %s and %s.' % (name.replace('_',' '),low,high))
    result['page_delay'] = max(1, min(float(result['page_delay']), 60))
    result['people'] = [str(x).strip() for x in result.get('people', []) if str(x).strip()][:1000]
    for key in ('start', 'end'):
        value = result.get(key, '')
        if value and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('Dates must use YYYY-MM-DD.')
    if result['start'] and result['end'] and result['start'] > result['end']:
        raise ValueError('The end date must be on or after the start date.')
    return result


def media_limit(attachment, cap_mb=10):
    video = str(attachment.get('content_type') or '').startswith('video/') or bool(re.search(r'\.(mp4|webm|mov|m4v|avi|mkv|mpeg|mpg|wmv|3gp)$', str(attachment.get('filename','')), re.I))
    return min(int(cap_mb), 10 if video else 100) * 1000000


def media_reason(attachment, maximum, saved=None):
    size = max(int(attachment.get('size') or 0), int((saved or {}).get('size') or 0))
    return 'Skipped: exceeds %.0f MB cap.' % (maximum/1000000) if size > maximum else ''


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')[:100]
    if not value or value.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        value = '_' + (value or 'file')
    return value


def filtered(message, opts):
    author = message.get('author', {})
    date = message.get('timestamp', '')[:10]
    return not ((opts['exclude_bots'] and author.get('bot')) or
                (opts['people'] and str(author.get('id')) not in opts['people']) or
                (opts['start'] and date < opts['start']) or (opts['end'] and date > opts['end']))


def author_name(m):
    author = m.get('author', {})
    return author.get('global_name') or author.get('nickname') or author.get('username') or author.get('name') or 'Unknown'


def normalized(message, opts, media, requests=None, avatars=None):
    m = json.loads(packed(message))
    m.get('author', {}).pop('avatar_local_path', None)
    captured = avatar_key(m.get('author', {}))
    saved_avatar = (avatars or {}).get(captured[0]) if captured else None
    if opts.get('include_avatars') and saved_avatar:
        m['author']['avatar_local_path'] = '../../avatars/'+saved_avatar['hash']
    if not opts['reactions']:
        m.pop('reactions', None)
    if not opts['edits']:
        m.pop('edited_timestamp', None)
    if not opts['include_attachments']:
        m.pop('attachments', None)
    for attachment in m.get('attachments', []):
        attachment.pop('local_path', None)
        saved = media.get(str(attachment.get('id')))
        reason = media_reason(attachment, media_limit(attachment, opts['max_media_mb']), saved)
        if reason:
            attachment['download_status'] = reason
        elif saved and opts['download_media']:
            attachment['local_path'] = '../../' + saved['relative_path']
            attachment['download_status'] = 'Saved by manual selection'
        else:
            request = (requests or {}).get(str(attachment.get('id')), {})
            attachment['download_status'] = request.get('detail') if request.get('status')=='skipped' else 'Not downloaded; manual selection required'
    return m


def render(messages, fmt, channel, opts):
    if fmt == 'json':
        return packed({'schema': 'discord-archive-studio/1', 'guild': {'id': channel['server_id'], 'name':channel.get('server_name','Imported server')},
                       'channel': {'id': channel['id'], 'name': channel['name']}, 'messages': messages})
    if fmt in ('txt', 'md'):
        lines = ['# ' + channel['name']] if fmt == 'md' else [channel['name']]
        for m in messages:
            label = '%s · %s · %s' % (author_name(m), m.get('timestamp', ''), m['id'])
            lines.append(('### ' if fmt == 'md' else '[') + label + ('' if fmt == 'md' else ']'))
            if m.get('message_reference'):
                lines.append('Reply to: ' + str(m['message_reference'].get('message_id', '')))
            lines.append(m.get('content', ''))
            for attachment in m.get('attachments', []):
                url = attachment.get('local_path') or attachment.get('url', '')
                if fmt == 'md':
                    url = url.replace(')', '%29').replace('(', '%28').replace(' ', '%20')
                    lines.append('[%s](%s)' % (str(attachment.get('filename', 'Attachment')).replace(']', '\\]'), url))
                else:
                    lines.append('Attachment: %s — %s' % (attachment.get('filename', ''), url))
            for embed in m.get('embeds', []):
                lines.extend([embed.get('title', ''), embed.get('description', '')])
            if m.get('reactions'):
                lines.append('Reactions: ' + ', '.join('%s ×%s' % (r.get('emoji', {}).get('name', '?'), r.get('count', 0)) for r in m['reactions']))
            if m.get('edited_timestamp'):
                lines.append('Edited: ' + m['edited_timestamp'])
            lines.append('')
        return '\n'.join(lines)
    esc = html.escape
    cards = []
    for m in messages:
        attachments = []
        for a in m.get('attachments', []):
            url = a.get('local_path') or a.get('url', '')
            safe_url = url if url.startswith('../../media/') or url.startswith('https://') else ''
            label = esc(a.get('filename', 'Attachment'))
            if a.get('content_type', '').startswith('image/') and a.get('local_path') and safe_url:
                attachments.append('<a href="%s"><img loading="lazy" src="%s" alt="%s"></a>' % (esc(safe_url, quote=True), esc(safe_url, quote=True), label))
            elif safe_url:
                attachments.append('<a href="%s">📎 %s</a>' % (esc(safe_url, quote=True), label))
            attachments.append('<small>%s</small>' % esc(a.get('download_status','')))
        reactions = ' '.join('%s ×%s' % (esc(r.get('emoji', {}).get('name') or '?'), r.get('count', 0)) for r in m.get('reactions', []))
        reply = m.get('message_reference', {}).get('message_id')
        color = m.get('author', {}).get('role_color', 0) if opts['role_colors'] else 0
        color = '#%06x' % int(color) if isinstance(color, int) and 0 <= color <= 0xffffff else '#b6a4ff'
        embeds = ''.join('<aside><b>%s</b><p>%s</p></aside>' % (esc(e.get('title', '')), esc(e.get('description', ''))) for e in m.get('embeds', []))
        avatar = m.get('author', {}).get('avatar_local_path','')
        picture = '<img class="pfp" width="40" height="40" src="%s" alt="" loading="lazy">' % esc(avatar,quote=True) if re.fullmatch(r'\.\./\.\./avatars/[a-f0-9]{64}',avatar) else ''
        cards.append('<article id="m%s"><header>%s<b style="color:%s">%s</b><time>%s</time></header>%s<div class="content">%s</div>%s%s<footer>%s %s</footer></article>' %
                     (esc(m['id'], quote=True), picture, color, esc(author_name(m)), esc(m.get('timestamp', '')),
                      '<small>↩ Reply to '+esc(str(reply))+'</small>' if reply else '', esc(m.get('content', '')), ''.join(attachments), embeds, reactions,
                      '· edited '+esc(m.get('edited_timestamp', '')) if m.get('edited_timestamp') else ''))
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src https: data: file:; media-src https: file:">
    <title>''' + esc(channel['name']) + '''</title><style>body{background:#0c1220;color:#e8edf7;font:16px system-ui;margin:0 auto;max-width:1000px;padding:32px}article{background:#141e30;border:1px solid #273750;border-radius:14px;padding:20px;margin:12px 0}header{display:flex;gap:16px;align-items:center}time,footer,small{color:#99a9c2;font-size:12px}.content{white-space:pre-wrap;overflow-wrap:anywhere;margin:12px 0}img{display:block;max-width:100%;max-height:500px;border-radius:10px}a{color:#a69bff}aside{border-left:3px solid #7865ff;padding:10px}</style><h1>''' + esc(channel['name']) + '</h1>' + ''.join(cards) + '</html>'


class Exporter:
    def __init__(self, store):
        self.store = store
        from .avatars import Avatars
        self.avatars = Avatars(store)

    def download_selected(self, task, control):
        aid, cid = task['attachment_id'], task['channel_id']
        with self.store.db() as db:
            row = db.execute('SELECT raw FROM messages WHERE id=?',(task['message_id'],)).fetchone()
            old = db.execute('SELECT * FROM media WHERE attachment_id=?',(aid,)).fetchone()
        if not row:
            raise ValueError('The selected message is no longer in the library.')
        attachment = next((a for a in json.loads(row['raw']).get('attachments',[]) if str(a.get('id'))==aid), None)
        if not attachment:
            raise ValueError('This attachment is absent from the current saved message.')
        maximum = min(task['max_bytes'], media_limit(attachment,100))
        reason = media_reason(attachment, maximum, dict(old) if old else None)
        if reason:
            raise MediaTooLarge(reason)
        if old and (self.store.root/old['relative_path']).is_file():
            return old['size']
        handle, name = tempfile.mkstemp(prefix='media-', suffix='.partial', dir=self.store.root)
        os.close(handle)
        temp = Path(name)
        try:
            last = 0
            def progress(total):
                nonlocal last
                if time.monotonic()-last >= .5:
                    self.store.update_media(aid, received=total)
                    last = time.monotonic()
            size = download(attachment.get('url',''),temp,maximum,control,progress)
            with temp.open('rb') as source:
                digest = hashlib.file_digest(source,'sha256').hexdigest()
            target = self.store.root/'media'/digest
            with self.store.archive_lock:
                if target.exists():
                    temp.unlink()
                else:
                    os.replace(temp,target)
                with self.store.db() as db:
                    db.execute('INSERT OR REPLACE INTO media VALUES(?,?,?,?,?)',(aid,digest,attachment.get('filename',aid),size,'media/'+digest))
                    db.execute('UPDATE channels SET generation=generation+1 WHERE id=?',(cid,))
            return size
        finally:
            temp.unlink(missing_ok=True)

    def publish(self, server_id, opts, destination, control=lambda: True, channel_id=None, selected_channels=None):
        with self.store.archive_lock:
            return self._publish(server_id, opts, destination, control, channel_id, selected_channels)

    def _publish(self, server_id, opts, destination, control, channel_id, selected_channels):
        destination = Path(destination).expanduser()
        if not destination.is_absolute():
            raise ValueError('Select an absolute destination folder.')
        destination.mkdir(parents=True, exist_ok=True)
        channels = [c for c in self.store.channels(server_id) if c['generation'] or c['history_done']]
        with self.store.db() as db:
            server = db.execute('SELECT name FROM servers WHERE id=?',(server_id,)).fetchone()
            server_name = server['name'] if server else server_id
            affected = {channel_id} if channel_id else (set(selected_channels) if selected_channels is not None else {c['id'] for c in channels})
            for channel in channels:
                if channel['id'] in affected:
                    db.execute('INSERT OR REPLACE INTO channel_exports VALUES(?,?)',(channel['id'],packed({k:v for k,v in opts.items() if not k.startswith('_')})))
            views = {r['channel_id']:options(dict(json.loads(r['options']),max_media_mb=min(100,int(json.loads(r['options']).get('max_media_mb',10))))) for r in db.execute('SELECT * FROM channel_exports')}
            media = {r['attachment_id']: dict(r) for r in db.execute('SELECT * FROM media')}
            requests = {r['attachment_id']:dict(r) for r in db.execute('SELECT * FROM media_requests')}
            previous = db.execute('SELECT * FROM publications WHERE server_id=?', (server_id,)).fetchone()
        avatars = self.avatars.cached()
        for channel in channels:
            if channel['id'] in affected and views.get(channel['id'],opts).get('include_avatars'):
                self.avatars.queue([channel['id']])
        media = {aid:dict(saved,size=max(saved['size'],(self.store.root/saved['relative_path']).stat().st_size)) for aid,saved in media.items() if (self.store.root/saved['relative_path']).is_file()}
        view_keys = ('formats','download_media','include_attachments','include_avatars','max_media_mb','reactions','edits','role_colors','split_count','split_mb','exclude_bots','people','start','end')
        presentation = {c['id']:{k:views.get(c['id'],opts)[k] for k in view_keys} for c in channels}
        with self.store.db() as db:
            pictured_users={r[0] for r in db.execute("SELECT DISTINCT m.author_id FROM messages m JOIN channels c ON c.id=m.channel_id JOIN channel_exports e ON e.channel_id=c.id WHERE c.server_id=? AND json_extract(e.options,'$.include_avatars')=1",(server_id,))}
        picture_versions={key:saved['hash'] for key,saved in avatars.items() if key.split(':',1)[0] in pictured_users}
        digest = fingerprint({'reader_schema':1,'server_name':server_name,'channels': [(c['id'], c['name'], c['generation'], c['history_done']) for c in channels], 'options': presentation,'avatars':picture_versions})
        target = destination / ('server_%s.zip' % server_id)
        if previous and previous['hash'] == digest and previous['path'] == str(target) and target.is_file():
            return {'path': str(target), 'unchanged': True, 'bytes': target.stat().st_size}
        handle, name = tempfile.mkstemp(prefix='.studio-server-'+server_id+'-', suffix='.tmp', dir=destination)
        os.close(handle)
        temp = Path(name)
        try:
            index, used_media, used_avatars = [], set(), set()
            with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
                archive.writestr('README.txt', 'Discord Archive Studio\nOpen index.html to browse channels. JSON preserves stable message IDs.\nCaptured data may be partial during a paced export. Deleted messages and unseen edits are not recoverable.\n')
                for channel in channels:
                    channel['server_name'] = server_name
                    channel_opts = views.get(channel['id'],opts)
                    part, batch, size = 1, [], 0
                    def write_part():
                        base = 'channels/%s/%05d' % (channel['id'], part)
                        # Reader data is local presentation metadata, independent of selected formats.
                        if 'json' not in channel_opts['formats']:
                            archive.writestr('reader/%s/%05d.json' % (channel['id'],part),render(batch,'json',channel,channel_opts))
                        for fmt in channel_opts['formats']:
                            ext = fmt
                            archive.writestr(base+'.'+ext, render(batch, fmt, channel, channel_opts))
                            index.append({'channel': channel['name'], 'channel_id': channel['id'], 'file': base+'.'+ext, 'messages': len(batch), 'format': fmt})
                    for m in self.store.iter_messages(channel['id']):
                        if not control():
                            raise Interrupted('ZIP publication paused; previous ZIP remains intact.')
                        if not filtered(m, channel_opts):
                            continue
                        normalized_message = normalized(m, channel_opts, media, requests, avatars)
                        if normalized_message.get('author',{}).get('avatar_local_path'):
                            used_avatars.add(normalized_message['author']['avatar_local_path'][6:])
                        estimated = len(packed(normalized_message).encode('utf-8'))
                        if batch and (len(batch) >= channel_opts['split_count'] or (channel_opts['split_mb'] and size+estimated > channel_opts['split_mb']*1024*1024)):
                            write_part()
                            part, batch, size = part+1, [], 0
                        batch.append(normalized_message)
                        size += estimated
                        used_media.update(str(a.get('id')) for a in normalized_message.get('attachments', []) if a.get('local_path'))
                    if batch or part == 1:
                        write_part()
                written = set()
                for aid in used_media:
                    saved = media.get(aid)
                    if saved and saved['hash'] not in written:
                        archive.write(self.store.root / saved['relative_path'], saved['relative_path'])
                        written.add(saved['hash'])
                manifest = {'schema': 'discord-archive-studio/1', 'server_id': server_id, 'server_name':server_name, 'content_hash': digest, 'channels': channels, 'files': index, 'options': presentation}
                for relative in used_avatars:
                    archive.write(self.store.root/relative,relative)
                archive.writestr('manifest.json', packed(manifest))
                links = ''.join('<li><a href="%s">%s — %s (%s messages)</a></li>' % (html.escape(i['file'], quote=True), html.escape(i['channel']), i['format'].upper(), i['messages']) for i in index)
                archive.writestr('index.html', '<!doctype html><meta charset="utf-8"><title>'+html.escape(server_name)+'</title><style>body{font:16px system-ui;background:#0c1220;color:#eee;padding:32px}a{color:#b6a4ff}li{margin:12px}</style><h1>'+html.escape(server_name)+'</h1><ul>'+links+'</ul>')
            with zipfile.ZipFile(temp) as verify:
                broken = verify.testzip()
                if broken:
                    raise RuntimeError('ZIP verification failed; previous archive was preserved.')
            if not control():
                raise Interrupted('ZIP publication paused; previous ZIP remains intact.')
            os.replace(temp, target)
            with self.store.db() as db:
                db.execute('INSERT OR REPLACE INTO publications VALUES(?,?,?,?,?,?)', (server_id, str(target), digest, packed(opts), time.time(), target.stat().st_size))
            return {'path': str(target), 'unchanged': False, 'bytes': target.stat().st_size}
        finally:
            temp.unlink(missing_ok=True)
