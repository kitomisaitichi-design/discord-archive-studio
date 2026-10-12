"""Optional reproducible large-library check; all records are synthetic."""
import json
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.store import Store


with tempfile.TemporaryDirectory(prefix='discord-studio-benchmark-') as root:
    store=Store(root)
    store.catalog([{'id':'1','name':'Synthetic benchmark'}],[{'id':'2','name':'messages','type':0}],'1')
    stamp=datetime.now(timezone.utc).isoformat();start=time.perf_counter()
    for base in range(0,100000,1000):
        store.upsert('2',[{'id':str(1000000000000000000+i),'channel_id':'2','author':{'id':'3','username':'Synthetic'},'timestamp':stamp,
          'content':('findneedle ' if i%1000==0 else '')+'A saved conversation about releases and archive updates.'} for i in range(base,base+1000)])
    import_time=time.perf_counter()-start
    timings=[]
    for query in ('findneedle','releases',''):
        start=time.perf_counter();result=store.search(query);elapsed=(time.perf_counter()-start)*1000
        timings.append({'query':query or '(empty)','matching':result['total'],'page':len(result['messages']),'milliseconds':round(elapsed,2)})
    print(json.dumps({'synthetic_messages':store.stats()['messages'],'insert_seconds':round(import_time,2),'searches':timings}))
