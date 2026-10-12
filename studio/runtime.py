import hashlib
import json
import os
from pathlib import Path
import threading
import time
from datetime import datetime, timedelta, timezone
from .credentials import Vault, desktop_candidates
from .discord import Discord, AuthError, PermissionError, Interrupted, MediaTooLarge
from .access import Access, Inaccessible
from .exporting import Exporter, options
from .store import packed
from .pacing import varied_delay


class Connection:
    def __init__(self, store):
        self.store = store
        self.vault = Vault(store.root)
        self.token = None
        self.account = None
        self.source = None
        self.error = ''
        self.busy = False
        self.lock = threading.RLock()
        self.wire = threading.RLock()
        self.throttle = {'next': 0}
        self.failed = set()
        self.attempt_lock = threading.Lock()
        self.stop = threading.Event()
        self.reconnect = threading.Event()

    def status(self):
        return {'connected': bool(self.token), 'account': self.account, 'source': self.source,
                'error': self.error, 'busy': self.busy}

    def accept(self, token, source):
        with self.lock:
            return self._accept(token, source)

    def _accept(self, token, source):
        if not isinstance(token, str) or '\n' in token or '\r' in token or not 30 <= len(token) <= 200:
            raise ValueError('The local session credential is invalid.')
        digest = hashlib.sha256(token.encode()).hexdigest()
        if digest in self.failed:
            raise AuthError('This session has already expired; open Discord with a current login.')
        try:
            with self.wire:
                client = Discord(token)
                client.throttle = self.throttle
                account = client.get('users/@me')
        except AuthError:
            self.failed.add(digest)
            raise
        pin = self.store.setting('account_id')
        if pin and str(account['id']) != pin:
            raise ValueError('A different Discord account was detected. Disconnect in Settings before switching accounts.')
        public = {'id': str(account['id']), 'name': account.get('global_name') or account.get('username', 'Discord user')}
        self.vault.save(token, public, source)
        with self.lock:
            self.token, self.account, self.source, self.error = token, public, source, ''
        self.store.set_setting('account_id', public['id'])
        return public

    def api(self, control=None, status=None, delay=2.5):
        with self.lock:
            if not self.token:
                raise AuthError('Open logged-in Discord, or pair the browser connector in Settings.')
            client = Discord(self.token, control, status)
        client.lock = self.wire
        client.throttle = self.throttle
        client.page_delay = delay
        return client

    def expired(self, expected_digest=None):
        with self.lock:
            if expected_digest and self.token and hashlib.sha256(self.token.encode()).hexdigest() != expected_digest:
                return False
            if self.token:
                self.failed.add(hashlib.sha256(self.token.encode()).hexdigest())
            self.token = None
            self.error = 'Session expired. Queued exports are paused. Reopen Discord to reconnect.'
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='paused',detail=? WHERE status IN ('queued','running','waiting')", (self.error,))
        self.reconnect.set()
        return True

    def disconnect(self):
        self.expired()
        self.vault.clear()
        self.store.set_setting('account_id', None)
        self.store.set_setting('auto_connect', False)
        with self.lock:
            self.account, self.source, self.error = None, None, ''

    def connect_desktop(self, manual=False):
        if not self.attempt_lock.acquire(blocking=False):
            return False
        if manual:
            self.store.set_setting('auto_connect', True)
        self.busy = True
        try:
            count = 0
            for token, source in desktop_candidates():
                if token == self.token:
                    return True
                count += 1
                if count > 10:
                    break
                try:
                    self.accept(token, source)
                    return True
                except AuthError:
                    continue
                except ValueError:
                    continue
            if not self.token:
                self.error = 'No current desktop login was found. Open Discord or use the browser connector.'
            return False
        except (OSError, RuntimeError) as error:
            self.error = str(error)
            return False
        finally:
            self.busy = False
            self.attempt_lock.release()

    def signature(self):
        items = []
        for profile in ('discord', 'discordptb', 'discordcanary'):
            folder = Path(os.environ.get('APPDATA', '')) / profile / 'Local Storage' / 'leveldb'
            try:
                items += [(p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in folder.glob('*.log')]
                items += [(p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in folder.glob('*.ldb')]
            except OSError:
                pass
        return hashlib.sha256(packed(items).encode()).hexdigest()

    def monitor(self):
        if self.store.setting('auto_connect', True):
            try:
                previous = self.vault.load()
                if previous:
                    self.accept(previous['token'], previous['source'])
            except (OSError, RuntimeError, ValueError):
                pass
            if not self.token:
                self.connect_desktop()
        previous_signature = self.signature()
        while not self.stop.is_set():
            requested = self.reconnect.wait(30)
            self.reconnect.clear()
            if self.stop.is_set():
                break
            signature = self.signature()
            # No network polling while profile state is unchanged. A browser bridge is event-driven.
            if (requested or signature != previous_signature) and self.store.setting('auto_connect', True):
                previous_signature = signature
                if not self.token or self.source != 'browser':
                    self.connect_desktop()


class Worker:
    def __init__(self, store, connection):
        self.store, self.connection = store, connection
        self.access, self.exporter = Access(store), Exporter(store)
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.member_cache = {}

    def signal(self):
        self.wake.set()

    def active(self, job):
        if self.stop.is_set() or not self.connection.account or self.connection.account['id'] != job['owner_id']:
            return False
        return self.store.job(job['id'])['status'] == 'running'

    def tick_schedules(self):
        if not self.connection.account:
            return
        owner = self.connection.account['id']
        schedules = self.store.schedules()
        exclusions=set(self.store.setting('schedule_exclusions:'+owner,[]))
        overrides = {s['scope']: s for s in schedules if s['scope'].startswith('channel:') and s['owner_id'] == owner}
        now = time.time()
        # Server defaults produce durable per-channel clocks, preserving independent adaptive timing.
        for schedule in schedules:
            if schedule['owner_id'] != owner or not schedule['enabled'] or not schedule['scope'].startswith('server:'):
                continue
            sid = schedule['scope'].split(':', 1)[1]
            pending = any(j['server_id']==sid and j['status'] in ('queued','running','waiting','paused') for j in self.store.jobs())
            if schedule['next_run'] <= now and not pending and now >= self.store.setting('cooldown_until', 0):
                try:
                    self.access.inventory(self.connection.api(), owner, sid, bool(schedule['options'].get('archived_threads')))
                except AuthError as error:
                    self.connection.expired(error.digest)
                    return
                except (Inaccessible, PermissionError) as error:
                    self.access.quarantine(sid, str(error))
                    continue
                except Exception as error:
                    self.store.set_setting('worker_error', 'Scheduled inventory check: '+str(error))
                    with self.store.db() as db:
                        db.execute('UPDATE schedules SET next_run=? WHERE scope=?', (now+max(900,schedule['minutes']*60),schedule['scope']))
                    continue
                with self.store.db() as db:
                    db.execute('UPDATE schedules SET next_run=? WHERE scope=?', (now+schedule['minutes']*60,schedule['scope']))
            for channel in self.store.channels(sid):
                if channel['type'] in (4, 15, 16):
                    continue
                scope = 'channel:'+channel['id']
                if not any(s['scope']==scope for s in schedules) and scope not in exclusions:
                    self.store.schedule(scope, owner, True, schedule['mode'], schedule['minutes'], dict(schedule['options'], inherited=True))
        for schedule in self.store.schedules():
            if schedule['owner_id'] != owner or not schedule['enabled'] or not schedule['scope'].startswith('channel:') or schedule['next_run'] > now:
                continue
            cid = schedule['scope'].split(':', 1)[1]
            self.store.enqueue([cid], owner, options(schedule['options']), scheduled=True)
            minutes = self.store.interval(cid)['minutes'] if schedule['mode'] == 'adaptive' else schedule['minutes']
            with self.store.db() as db:
                db.execute('UPDATE schedules SET next_run=?,minutes=? WHERE scope=?', (now+minutes*60, minutes, schedule['scope']))

    def enrich(self, api, server_id, messages, opts):
        if not opts['role_colors'] or server_id == '0':
            return
        with self.store.db() as db:
            row = db.execute('SELECT raw FROM servers WHERE id=?', (server_id,)).fetchone()
        roles = json.loads(row['raw']).get('roles', []) if row else []
        # No individual user/member probes: only role data already present on returned message objects.
        by_id = {str(r['id']): r for r in roles}
        for message in messages:
            role_ids = message.get('member', {}).get('roles', [])
            selected = sorted((by_id[str(r)] for r in role_ids if str(r) in by_id), key=lambda r: r.get('position', 0), reverse=True)
            role = next((r for r in selected if r.get('color')), None)
            if role:
                message.setdefault('author', {})['role_color'] = role['color']

    def process(self, job):
        jid, cid = job['id'], job['channel_id']
        channel = next(c for c in self.store.channels() if c['id'] == cid)
        sid, opts = channel['server_id'], options(job['options'])
        control = lambda: self.active(job)
        status = lambda text: self.store.update_job(jid, detail=text)
        api = self.connection.api(control, status, opts['page_delay'])
        api.timing_variation=opts['timing_variation']
        status('Checking current membership and accessible channel/thread inventory…')
        self.access.inventory(api, job['owner_id'], sid, required_channel=cid)
        checked = time.monotonic()
        if not control():
            raise Interrupted('Paused during preflight.')
        if not job['boundary']:
            latest = api.get('channels/%s/messages' % cid, limit=1)
            boundary = str(int(latest[0]['id'])+1) if latest else '1'
            job['boundary'] = boundary
            # Snapshot the lower checkpoint. It must not advance before this sweep completes.
            cached = self.store.newest_saved(cid)
            checkpoints = [int(x) for x in (cached,channel['last_id']) if x]
            opts['_lower'] = str(max(checkpoints)) if checkpoints else None
            opts['_initial'] = bool(opts.get('full_rescan')) or (not checkpoints and not channel['history_done'] and not opts.get('_scheduled'))
            if not checkpoints and opts.get('_scheduled'):
                # A schedule may discover an old channel; establish a head baseline, never backfill it silently.
                opts['_lower'] = str(int(boundary)-1)
            opts['_forward'] = not opts['_initial'] and (not opts.get('recheck_edits',False) or not cached)
            job['cursor'] = (opts['_lower'] or '0') if opts['_forward'] else boundary
            with self.store.db() as db:
                db.execute('UPDATE jobs SET boundary=?,cursor=?,options=? WHERE id=?', (boundary, job['cursor'], packed(opts), jid))
        else:
            opts.update({k: v for k, v in job['options'].items() if k.startswith('_')})
        if job['phase'] == 'messages':
            scanned = 0
            finished = False
            old_scanned = int(opts.get('_old_scanned', 0))
            cutoff = (datetime.now(timezone.utc)-timedelta(days=opts['edit_lookback_days'])).isoformat()
            while control():
                forward = opts.get('_forward',False)
                if forward and int(job['cursor'])>=int(job['boundary'])-1:
                    finished = True
                    break
                if time.monotonic()-checked > 60:
                    self.access.inventory(api, job['owner_id'], sid, required_channel=cid)
                    checked = time.monotonic()
                raw_page = api.get('channels/%s/messages' % cid, **({'after':job['cursor']} if forward else {'before':job['cursor']}), limit=100)
                page = [m for m in raw_page if int(m['id'])<int(job['boundary'])] if forward else raw_page
                if not page:
                    finished = True
                    break
                cursor = str((max if forward else min)(int(m['id']) for m in page))
                if (forward and int(cursor)<=int(job['cursor'])) or (not forward and int(cursor)>=int(job['cursor'])):
                    raise RuntimeError('Discord repeated a message page; stopped without losing the checkpoint.')
                self.enrich(api, sid, page, opts)
                change = self.store.upsert(cid, page)
                scanned += len(page)
                batch_usage = self.store.setting('batch_usage', 0)+len(page)
                self.store.set_setting('batch_usage', batch_usage)
                job['progress'] += len(page)
                job['cursor'] = cursor
                self.store.update_job(jid, cursor=cursor, progress=job['progress'], detail='%s messages scanned · +%s new / %s updated this page' % (job['progress'], change['added'], change['edited']))
                lower = opts.get('_lower')
                if not forward and lower and not opts.get('_initial') and int(cursor) <= int(lower):
                    old_scanned += sum(int(m['id']) <= int(lower) for m in page)
                    opts['_old_scanned'] = old_scanned
                    with self.store.db() as db:
                        db.execute('UPDATE jobs SET options=? WHERE id=?', (packed(opts), jid))
                    if old_scanned >= 500 or min(m['timestamp'] for m in page) < cutoff:
                        finished = True
                        break
                if len(raw_page) < 100 or (forward and int(cursor)>=int(job['boundary'])-1):
                    finished = True
                    break
                if batch_usage >= opts['batch_messages']:
                    break
            if not control():
                raise Interrupted('Paused or cancelled after a committed page.')
            if not finished:
                # Make a partial archive concrete before entering the durable global cooldown.
                status('Saving this batch to the current server ZIP…')
                self.exporter.publish(sid, opts, self.destination(), control, channel_id=cid)
                until = time.time()+varied_delay(opts['cooldown_minutes']*60,opts['timing_variation'])
                self.store.set_setting('cooldown_until', until)
                self.store.set_setting('batch_usage', 0)
                self.store.update_job(jid, status='waiting', detail='Batch saved. Cooling down; resumes automatically.')
                return
            with self.store.db() as db:
                checkpoint = max(int(job['boundary'])-1,int(opts.get('_lower') or 0))
                db.execute('UPDATE channels SET last_id=?,history_done=CASE WHEN ? THEN 1 ELSE history_done END,last_scan=? WHERE id=?', (str(checkpoint) if checkpoint else None,bool(opts.get('_initial')),time.time(),cid))
            self.store.update_job(jid, phase='zip', detail='Text sweep committed; saving metadata and selected local files…')
            job['phase'] = 'zip'
        if job['phase'] == 'media':
            # Upgrade older checkpoints without downloading unselected files.
            self.store.update_job(jid, phase='zip', detail='Verifying the current server ZIP…')
        result = self.exporter.publish(sid, opts, self.destination(), control, channel_id=cid)
        if time.monotonic()-checked > 60:
            self.access.inventory(api, job['owner_id'], sid, required_channel=cid)
        latest = api.get('channels/%s/messages' % cid, limit=1)
        catchup = bool(latest and int(latest[0]['id']) >= int(job['boundary'])) or bool(self.store.job(jid)['dirty'])
        self.store.update_job(jid, status='completed', phase='done', detail=('No changes; current ZIP retained.' if result['unchanged'] else 'Verified ZIP updated.')+' '+result['path'])
        if self.store.setting('batch_usage', 0) >= opts['batch_messages']:
            self.store.set_setting('cooldown_until', time.time()+varied_delay(opts['cooldown_minutes']*60,opts['timing_variation']))
            self.store.set_setting('batch_usage', 0)
        if catchup:
            self.store.enqueue([cid], job['owner_id'], {k: v for k, v in opts.items() if not k.startswith('_')}, scheduled=True)
            self.store.set_setting('cooldown_until', time.time()+varied_delay(opts['cooldown_minutes']*60,opts['timing_variation']))

    def destination(self):
        return self.store.setting('destination', str(self.store.root.parent / 'Exports'))

    def text_pending(self):
        return any(j['status'] in ('queued','running','waiting') for j in self.store.jobs())

    def process_media(self):
        if self.text_pending() or time.time()<self.store.setting('media_next',0):
            return
        tasks = [r for r in self.store.media_tasks() if r['status']=='queued']
        if not tasks:
            return
        task = min(tasks,key=lambda r:r['updated'])
        aid = task['attachment_id']
        self.store.update_media(aid,status='running',received=0,detail='Downloading selected attachment…')
        def control():
            return not self.stop.is_set() and not self.text_pending() and any(r['attachment_id']==aid and r['status']=='running' for r in self.store.media_tasks())
        try:
            size = self.exporter.download_selected(task,control)
            if not control():
                raise Interrupted('Yielded to text export or cancelled.')
            self.exporter.publish(task['server_id'],options(None),self.destination(),control,selected_channels=[])
            self.store.update_media(aid,status='completed',received=size,detail='Saved locally; current server ZIP updated.')
        except Interrupted:
            current = next(r for r in self.store.media_tasks() if r['attachment_id']==aid)
            if current['status']=='running':
                self.store.update_media(aid,status='queued',detail='Yielded to text export; waiting.')
        except MediaTooLarge as error:
            self.store.update_media(aid,status='skipped',detail=str(error))
            try:
                self.exporter.publish(task['server_id'],options(None),self.destination(),selected_channels=[])
            except Exception as publish_error:
                self.store.update_media(aid,detail=str(error)+' ZIP update failed: '+str(publish_error))
        except Exception as error:
            self.store.update_media(aid,status='failed',detail='Download failed: '+str(error)+'. Signed links may expire; rescan text and retry explicitly.')
        self.store.set_setting('media_next',time.time()+5)

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick_schedules()
                if self.connection.token and time.time() >= self.store.setting('cooldown_until', 0):
                    candidates = [j for j in self.store.jobs() if j['status'] in ('queued', 'waiting') and j['owner_id'] == self.connection.account['id']]
                    if candidates:
                        job = candidates[0]
                        with self.store.db() as db:
                            changed = db.execute("UPDATE jobs SET status='running' WHERE id=? AND status IN ('queued','waiting')", (job['id'],)).rowcount
                        if changed:
                            try:
                                self.process(self.store.job(job['id']))
                            except Interrupted:
                                pass
                            except AuthError as error:
                                if not self.connection.expired(error.digest):
                                    self.store.update_job(job['id'], status='queued', detail='Session refreshed; continuing from the saved checkpoint.')
                            except Inaccessible as error:
                                channel = next(c for c in self.store.channels() if c['id']==job['channel_id'])
                                self.access.quarantine(channel['server_id'], str(error), job['channel_id'] if 'channel/thread' in str(error) else None)
                            except PermissionError as error:
                                channel = next(c for c in self.store.channels() if c['id']==job['channel_id'])
                                self.access.quarantine(channel['server_id'], str(error))
                            except Exception as error:
                                self.store.update_job(job['id'], status='failed', detail=str(error))
                                self.store.set_setting('cooldown_until', time.time()+900)
                self.process_media()
            except Exception as error:
                self.store.set_setting('worker_error', str(error))
            self.wake.wait(2)
            self.wake.clear()
