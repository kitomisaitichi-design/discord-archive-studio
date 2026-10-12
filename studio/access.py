"""Inventory-first access preflight. No stale-ID existence requests."""
from .discord import PermissionError

VIEW = 1 << 10
HISTORY = 1 << 16
CONNECT = 1 << 20
ADMIN = 1 << 3


class Inaccessible(RuntimeError):
    pass


def permissions(guild_id, user_id, roles, member, channel, owner=False):
    if owner:
        return (1 << 63)-1
    role_ids = set(map(str, member.get('roles', []))) | {str(guild_id)}
    value = 0
    for role in roles:
        if str(role['id']) in role_ids:
            value |= int(role.get('permissions', 0))
    if value & ADMIN:
        return (1 << 63)-1
    overwrites = channel.get('permission_overwrites', [])
    everyone = next((r for r in overwrites if str(r['id']) == str(guild_id)), {})
    value = (value & ~int(everyone.get('deny', 0))) | int(everyone.get('allow', 0))
    allow = deny = 0
    for overwrite in overwrites:
        if int(overwrite.get('type', 0)) == 0 and str(overwrite['id']) in role_ids and str(overwrite['id']) != str(guild_id):
            deny |= int(overwrite.get('deny', 0))
            allow |= int(overwrite.get('allow', 0))
    value = (value & ~deny) | allow
    personal = next((r for r in overwrites if int(r.get('type', 0)) == 1 and str(r['id']) == str(user_id)), {})
    return (value & ~int(personal.get('deny', 0))) | int(personal.get('allow', 0))


class Access:
    def __init__(self, store):
        self.store = store

    def inventory(self, api, owner, server_id, archived=False, required_channel=None):
        # Always query membership first. Never probe a saved guild/channel ID to find out if it still exists.
        guilds = api.guilds()
        self.store.catalog(guilds)
        guild = next((g for g in guilds if str(g['id']) == str(server_id)), None)
        if not guild:
            raise Inaccessible('You are no longer a member of this server. Its saved archive remains available offline.')
        if server_id == '0':
            channels = api.get('users/@me/channels')
            allowed = {str(c['id']): c for c in channels}
        else:
            # These requests are made only after current membership was confirmed.
            channels = api.get('guilds/%s/channels' % server_id)
            roles = api.get('guilds/%s/roles' % server_id)
            member = api.get('guilds/%s/members/%s' % (server_id, owner))
            allowed = {}
            for channel in channels:
                if channel.get('type') == 4:
                    continue
                bits = permissions(server_id, owner, roles, member, channel, bool(guild.get('owner')))
                required = VIEW | HISTORY | (CONNECT if channel.get('type') == 2 else 0)
                if bits & required == required:
                    allowed[str(channel['id'])] = channel
            guild['roles'] = roles
            self.store.catalog([guild])
            # This is a user-session client: DiscordChatExporter uses per-parent thread SEARCH.
            # Do not use the bot-only guild-wide active/archived thread endpoints.
            # A normal channel can be validated without any thread request.
            required_parent = None
            if required_channel:
                with self.store.db() as db:
                    record = db.execute('SELECT parent_id,type FROM channels WHERE id=?', (required_channel,)).fetchone()
                if record and record['type'] in (10, 11, 12):
                    required_parent = record['parent_id']
            parents = [c for c in list(allowed.values()) if c.get('type') in (0, 5, 15, 16) and c.get('last_message_id') and
                       (not required_channel or (required_parent and str(c['id']) == required_parent))]
            for parent in parents:
                for is_archived in ((False, True) if archived or required_parent else (False,)):
                    offset, seen = 0, set()
                    while True:
                        route = 'channels/%s/threads/search' % parent['id']
                        page = api.get(route, sort_by='last_message_time', sort_order='desc', archived=str(is_archived).lower(), offset=offset)
                        threads = page.get('threads', [])
                        for thread in threads:
                            if str(thread['id']) in seen:
                                raise Inaccessible('Thread inventory repeated an ID; stopped without probing saved thread IDs.')
                            seen.add(str(thread['id']))
                            thread.setdefault('parent_id', str(parent['id']))
                            allowed[str(thread['id'])] = thread
                        if required_channel and str(required_channel) in allowed:
                            break
                        if not threads or not page.get('has_more'):
                            break
                        offset += len(threads)
                    if required_channel and str(required_channel) in allowed:
                        break
        self.store.catalog([], list(allowed.values()), server_id)
        self.store.set_setting('inventory:'+str(server_id), {'owner': str(owner), 'ids': list(allowed)})
        if required_channel and str(required_channel) not in allowed:
            raise Inaccessible('This channel/thread is absent from your current accessible inventory. Automatic requests are stopped.')
        return allowed

    def quarantine(self, server_id, reason, channel_id=None):
        inventory = self.store.setting('inventory:'+str(server_id),{})
        inventory['ids'] = [cid for cid in inventory.get('ids',[]) if cid!=channel_id] if channel_id else []
        self.store.set_setting('inventory:'+str(server_id),inventory)
        with self.store.db() as db:
            if channel_id:
                db.execute("UPDATE jobs SET status='blocked',detail=?,updated=strftime('%s','now') WHERE channel_id=? AND status IN ('queued','running','waiting','paused')", (reason, channel_id))
            else:
                db.execute("UPDATE jobs SET status='blocked',detail=?,updated=strftime('%s','now') WHERE channel_id IN (SELECT id FROM channels WHERE server_id=?) AND status IN ('queued','running','waiting','paused')", (reason, server_id))
            # Disable the server default too; it could otherwise keep recreating the blocked child job.
            db.execute('UPDATE schedules SET enabled=0 WHERE scope=? OR scope IN (SELECT \'channel:\'||id FROM channels WHERE server_id=?)', ('server:'+server_id, server_id))
