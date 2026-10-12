from datetime import datetime, timedelta, timezone
from .exporting import DEFAULT_OPTIONS


def seed(store):
    store.set_setting('demo', True)
    store.set_setting('auto_connect', False)
    if store.stats()['messages']:
        return
    guild={'id':'820000000000000001','name':'Midnight Lounge'}
    channel_ids=['830000000000000001','830000000000000002','830000000000000003','830000000000000004','830000000000000005','830000000000000006']
    names=['general','development','showcase','media','announcements','off-topic']
    store.catalog([guild],[{'id':i,'name':n,'type':0,'guild_id':guild['id']} for i,n in zip(channel_ids,names)],guild['id'])
    people=[{'id':'840000000000000001','username':'Stella','global_name':'Stella'}, {'id':'840000000000000002','username':'Orion'}, {'id':'840000000000000003','username':'Luna'}, {'id':'840000000000000004','username':'Mira'}]
    texts=['The first batch is safely in the archive. Everything stays in one current server ZIP. ✨','I found the launch discussion with a search for `release notes`. That was quick.','Here’s the concept for the export flow:\n**Choose channels → gentle batches → searchable library.**','A quiet channel can rescan weekly. The development channel can adapt to its own activity.','The library is useful offline too. I can still see saved conversations while Discord is closed.','New messages arriving during an export wait for a catch-up pass. No duplicate archive copies.']
    for n,cid in enumerate(channel_ids):
        msgs=[]
        for j in range(120):
            stamp=datetime.now(timezone.utc)-timedelta(minutes=(120-j)*45+n*5)
            mid=str((int(stamp.timestamp()*1000)-1420070400000)<<22 | (n*200+j))
            msgs.append({'id':mid,'channel_id':cid,'author':people[j%4],'timestamp':stamp.isoformat(),'content':texts[(j+n)%len(texts)],'attachments':[],'reactions':[{'emoji':{'name':'✨'},'count':j%7+1}] if j%3==0 else []})
        store.upsert(cid,msgs)
    # Demo work is paused and cannot issue Discord requests. It is visibly labeled demonstration data.
    if not store.jobs() and not store.jobs(True):
        ids=store.enqueue(channel_ids[:2],'840000000000000001',DEFAULT_OPTIONS)
        store.update_job(ids[0],status='paused',progress=1000,detail='Demo task · no Discord requests are sent.')
