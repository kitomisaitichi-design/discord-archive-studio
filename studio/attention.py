"""A local failure inventory. Merely opening this view never retries network work."""
import time


def retry(server, data):
    store, worker = server.store, server.worker
    kind, key = data.get('kind'), str(data.get('id',''))
    if kind == 'export':
        job = store.job(key)
        owner = (server.connection.account or {}).get('id')
        if job['status'] != 'failed' or owner != job['owner_id']:
            raise ValueError('Only a failed task belonging to the connected account can be retried here.')
        with store.db() as db:
            channel = db.execute('SELECT server_id FROM channels WHERE id=?',(job['channel_id'],)).fetchone()
        access = store.setting('inventory:'+channel[0], {}) if channel else {}
        if access.get('owner') != owner or job['channel_id'] not in access.get('ids',[]):
            raise ValueError('Current saved access does not include this channel. Review it in Export; no resource was requested.')
        store.control(key, 'resume')
    elif kind == 'attachment':
        with store.db() as db:
            task = db.execute('SELECT * FROM media_requests WHERE attachment_id=?',(key,)).fetchone()
        if not task or task['status'] in ('queued','running','skipped'):
            raise ValueError('This attachment is active or exceeds its size cap. Review its selection in Library.')
        store.enqueue_media([{'message_id':task['message_id'],'attachment_id':key}], max(1,task['max_bytes']//1000000))
    elif kind == 'image':
        with store.db() as db:
            task = db.execute('SELECT * FROM linked_images WHERE url_key=?',(key,)).fetchone()
            ref = db.execute('SELECT * FROM image_refs WHERE url_key=? LIMIT 1',(key,)).fetchone()
        if not task or not ref or task['status'] in ('queued','running'):
            raise ValueError('This image is already active or no longer has a saved reference.')
        store.images.select([dict(message=ref['message_id'],channel=ref['channel_id'],url=task['url'],
            archive='' if ref['scope']=='library' else ref['scope'])], server.reader, max(1,task['max_bytes']//1000000))
    else:
        raise ValueError('Review this issue in its original page.')
    return {'queued':True}


def inventory(store, updater):
    def collect():
        rows = []
        with store.db() as db:
            for r in db.execute('''SELECT j.*,c.name,c.server_id FROM jobs j JOIN channels c ON c.id=j.channel_id
                    WHERE j.status IN ('failed','blocked') ORDER BY j.updated DESC LIMIT 300'''):
                rows.append(dict(kind='export', id=r['id'], title=r['name'], status=r['status'],
                    detail=r['detail'], channel=r['channel_id'], updated=r['updated'], action='review' if r['status']=='blocked' else 'retry'))
            for r in db.execute('''SELECT r.*,c.name FROM media_requests r JOIN channels c ON c.id=r.channel_id
                    WHERE r.status IN ('failed','paused','skipped') ORDER BY r.updated DESC LIMIT 150'''):
                rows.append(dict(kind='attachment', id=r['attachment_id'], title=r['name'], status=r['status'],
                    detail=r['detail'], message=r['message_id'], updated=r['updated'], action='retry' if r['status']!='skipped' else 'review'))
            for r in db.execute('SELECT * FROM media LIMIT 500'):
                if not (store.root/r['relative_path']).is_file():
                    task = db.execute('SELECT * FROM media_requests WHERE attachment_id=?', (r['attachment_id'],)).fetchone()
                    if task and task['status'] not in ('failed','paused','skipped','queued','running'):
                        rows.append(dict(kind='attachment', id=r['attachment_id'], title=r['filename'], status='missing',
                            detail='The indexed local file is missing. Select Retry to download this file again.',
                            message=task['message_id'], updated=task['updated'], action='retry'))
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'linked_images' in tables:
                for r in db.execute("SELECT * FROM linked_images WHERE status IN ('failed','paused') ORDER BY updated DESC LIMIT 150"):
                    rows.append(dict(kind='image', id=r['url_key'], title=r['filename'], status=r['status'], detail=r['detail'],
                        updated=r['updated'], action='retry'))
                for r in db.execute("SELECT * FROM linked_images WHERE status='completed' LIMIT 500"):
                    if not (store.root/'media'/r['hash']).is_file():
                        rows.append(dict(kind='image', id=r['url_key'], title=r['filename'], status='missing',
                            detail='The saved linked image is missing from the local cache.', updated=r['updated'], action='retry'))
        update = updater.status()
        if update.get('status') in ('failed', 'error', 'rolled_back') or update.get('error'):
            rows.append(dict(kind='update', id='application', title='Application update', status=update.get('status','failed'),
                detail=update.get('error') or update.get('detail') or 'Review the update status in Settings.', updated=update.get('last_check',0), action='settings'))
        error = store.setting('worker_error', '')
        if error:
            rows.append(dict(kind='worker', id='worker', title='Background worker', status='error', detail=error,
                updated=0, action='review'))
        rows.sort(key=lambda r: r['updated'] or 0, reverse=True)
        return {'items': rows, 'checked': time.time(), 'note': 'Local status only. Missing-file checks cover up to 500 indexed files per type; quarantined channels are never probed here.'}
    return store.metadata_cache.get(('attention', store.version, int(time.time()/60)), collect)
