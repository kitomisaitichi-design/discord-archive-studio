"""Account-scoped contact metadata; never create or probe a DM by a stored ID."""
import threading
import time
from .discord import PermissionError
from .store import valid_id


class People:
    ttl = 600

    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()

    def cached(self, owner):
        value = self.store.setting('people:'+str(owner), {}) if owner else {}
        counts = {c['id']:c['count'] for c in self.store.channels('0')}
        contacts = [dict(p, saved=sum(counts.get(cid,0) for cid in set(p['channel_ids']+p['group_ids']))) for p in value.get('contacts',[])]
        return dict(value, owner=owner, contacts=contacts)

    def refresh(self, api, owner, friends=False, force=False):
        owner = valid_id(owner)
        with self.lock:
            value = self.store.setting('people:'+owner, {})
            now = time.time()
            if not force and value.get('updated',0)+self.ttl>now and (not friends or value.get('friends_updated',0)+self.ttl>now):
                return self.cached(owner)
            channels = api.get('users/@me/channels')
            if not isinstance(channels,list):raise ValueError('Discord returned an invalid DM inventory.')
            channels = [c for c in channels if c.get('type') in (1,3)]
            for c in channels:valid_id(c['id'])
            friend_users = value.get('friend_users',[])
            if friends:
                try:
                    relationships = api.get('users/@me/relationships')
                    if not isinstance(relationships,list):raise ValueError('Discord returned an invalid friends inventory.')
                    friend_users = [dict(r['user'],id=valid_id(r.get('id') or r['user']['id'])) for r in relationships if r.get('type')==1 and r.get('user')]
                    value.update(friends_available=True,friends_note='',friends_updated=now)
                except PermissionError as error:
                    value.update(friends_available=False,friends_note=str(error),friends_updated=now)
            people = {}
            def person(user, prefer=False):
                uid = valid_id(user['id'])
                if uid==owner:return None
                p = people.setdefault(uid,{'id':uid,'channel_ids':[],'group_ids':[],'friend':False})
                if prefer or not p.get('name'):p.update(name=user.get('global_name') or user.get('username') or uid,username=user.get('username') or '')
                return p
            for c in channels:
                for user in c.get('recipients',[]):
                    p=person(user,c['type']==1)
                    if p is not None:p['channel_ids' if c['type']==1 else 'group_ids'].append(str(c['id']))
            for user in friend_users:
                p=people.get(str(user['id'])) if not friends or not value.get('friends_available') else None
                p=p or person(user,True)
                if p is not None:p['friend']=bool(value.get('friends_available'))
            value.update(contacts=sorted(people.values(),key=lambda p:(p['name'].casefold(),p['id'])),friend_users=friend_users,updated=now)
            self.store.catalog([{'id':'0','name':'Direct messages'}],channels,'0')
            self.store.set_setting('inventory:0',{'owner':owner,'ids':[str(c['id']) for c in channels]})
            self.store.set_setting('people:'+owner,value)
            return self.cached(owner)

    def queue(self, api, owner, users, opts, groups=False, friends=False, adaptive=False):
        if not isinstance(users,list) or not users or len(users)>3000:raise ValueError('Select one or more people (up to 3,000).')
        wanted=list(dict.fromkeys(map(valid_id,users)))
        current=self.refresh(api,owner,friends=friends,force=True)
        if friends and not current.get('friends_available'):raise ValueError('A current friends inventory is required for friends-only export.')
        selected={p['id']:p for p in current['contacts']}
        channels=[];skipped=0
        for uid in wanted:
            p=selected.get(uid)
            ids=(p['channel_ids']+(p['group_ids'] if groups else [])) if p and (not friends or p['friend']) else []
            if not ids:skipped+=1
            channels.extend(ids)
        channels=list(dict.fromkeys(channels))
        if not channels:raise ValueError('No currently available DM chats match this selection. Refresh People after opening the chat normally in Discord.')
        # People exports are whole conversations. A hidden server-person filter or full-rescan flag must not leak into this bulk action.
        opts=dict(opts,full_rescan=False,people=[],_queue_overrides=['people'])
        jobs=self.store.enqueue(channels,owner,opts)
        if adaptive:
            scopes={s['scope'] for s in self.store.schedules()}
            for cid in channels:
                if 'server:0' not in scopes and 'channel:'+cid not in scopes:
                    self.store.schedule('channel:'+cid,owner,True,'adaptive',1440,opts)
        return {'tasks':len(jobs),'chats':len(channels),'skipped':skipped}
