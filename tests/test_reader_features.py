import hashlib
import json
from urllib.request import Request
from urllib.error import HTTPError
from studio.reader_library import library_id
from studio.zipreader import ZipReader
from studio.exporting import Exporter,options
from studio.local_media import mime,bounds
from test_studio import Base,SID,CID,UID,message
import test_http
import unittest


class SearchFeatures(Base):
    def seed(self):
        rows=[]
        for i in range(180):
            m=message(9000+i,'hello wide world' if i%2 else 'hello world')
            m['timestamp']=f'2026-04-11T{3+i//60:02d}:{i%60:02d}:00Z'
            m['author']['username']='Old Alice' if i<90 else 'Alice renamed'
            m['attachments']=[{'id':str(20000+i),'filename':'recording_%'+str(i)+('.mp3' if i%2 else '.png'),'size':20}]
            rows.append(m)
        self.store.upsert(CID,rows)

    def test_combined_filters_phrases_literal_filename_and_renamed_names(self):
        self.seed()
        self.assertEqual(self.store.search('hello world',person='Alice',attachment='recording_',media_type='image',phrase=True)['total'],90)
        self.assertEqual(self.store.search(person=UID,media_type='audio')['total'],90)
        self.assertEqual(self.store.search(person='Old Alice')['total'],180)
        self.assertEqual(self.store.search(attachment='%1',media_type='image')['total'],45)
        self.assertEqual(self.store.search('"hello world"')['total'],90)
        self.assertEqual(self.store.search('" : OR - *')['total'],0)
        with self.store.db() as db:db.execute('DELETE FROM message_facets')
        self.assertEqual(self.store.search(person='Old Alice',media_type='audio')['total'],90)

    def test_stable_cursor_does_not_duplicate_when_new_messages_arrive(self):
        self.seed();first=self.store.search(limit=80)
        newest=message(9999);newest['timestamp']='2026-05-01T00:00:00Z';self.store.upsert(CID,[newest])
        second=self.store.search(limit=80,cursor=first['messages'][-1]['_cursor'])
        self.assertFalse(set(m['id'] for m in first['messages'])&set(m['id'] for m in second['messages']))
        self.assertEqual(len(second['messages']),80)

    def test_canonical_and_zip_search_scope_and_boundaries_agree(self):
        self.seed();output=Exporter(self.store).publish(SID,options({'formats':['json']}),self.root/'Exports')
        reader=ZipReader(self.store,scan_parent=False);zipkey=next(e['id'] for e in reader.catalogue() if e['source']=='export')
        for key in (library_id(SID),zipkey):
            query={'channel':CID,'author':UID,'attachment':'recording','type':'image','q':'hello world','phrase':'1','limit':80}
            first=reader.query(key,'messages',query);self.assertEqual(first['total'],90);self.assertFalse(first['before']);self.assertTrue(first['after'])
            second=reader.query(key,'messages',dict(query,after=first['last']));self.assertEqual(len(second['messages']),10);self.assertFalse(second['after']);self.assertTrue(second['before'])
            third=reader.query(key,'messages',dict(query,before=second['first']));self.assertEqual([m['id'] for m in third['messages']],[m['id'] for m in first['messages']])

    def test_ranges_and_media_types(self):
        for name,kind in [('clip.mp4','video/mp4'),('sound.mp3','audio/mpeg'),('sound.ogg','audio/ogg'),('sound.m4a','audio/mp4'),('song.mid','audio/midi'),('song.midi','audio/midi')]:self.assertEqual(mime(name),kind)
        self.assertEqual(bounds('bytes=2-5',10),(206,2,6));self.assertEqual(bounds('bytes=-3',10),(206,7,10))
        self.assertEqual(bounds('bytes=7-',10),(206,7,10));self.assertEqual(bounds('bytes=99-',10),(416,0,0));self.assertEqual(bounds('bytes=0-1,4-5',10),(416,0,0))


class MediaHTTP(unittest.TestCase):
    setUp=test_http.LocalHTTPTests.setUp
    tearDown=test_http.LocalHTTPTests.tearDown
    # Only these new HTTP checks are collected; inherited baseline tests have
    # their own class and are intentionally not duplicated here.
    def test_stream_seek_head_and_all_chat_surfaces_are_local(self):
        self.browser.open(self.url+'/').close();store=self.server.store
        store.catalog([{'id':SID,'name':'Fixture'}],[{'id':CID,'name':'chat'}],SID)
        payload=b'local media fixture';digest=hashlib.sha256(payload).hexdigest();(store.root/'media'/digest).write_bytes(payload)
        m=message(9001);m['attachments']=[{'id':'777','filename':'sound.m4a','size':len(payload)}];store.upsert(CID,[m])
        with store.db() as db:db.execute('INSERT INTO media VALUES(?,?,?,?,?)',('777',digest,'sound.m4a',len(payload),'media/'+digest))
        Exporter(store).publish(SID,options({'formats':['json']}),store.root/'Exports')
        zipkey=next(e['id'] for e in self.server.reader.catalogue() if e['source']=='export')
        zipped=self.server.reader.query(zipkey,'messages',{'channel':CID})['messages'][0]['attachments'][0]['_asset']
        for endpoint in ('/media/'+digest,'/api/reader/asset?archive='+library_id(SID)+'&id='+digest,'/api/reader/asset?archive='+zipkey+'&id='+zipped):
            with self.browser.open(Request(self.url+endpoint,headers={'Range':'bytes=2-6'})) as response:
                self.assertEqual(response.status,206);self.assertEqual(response.read(),payload[2:7]);self.assertEqual(response.headers['Content-Type'],'audio/mp4');self.assertEqual(response.headers['Content-Range'],f'bytes 2-6/{len(payload)}')
            with self.browser.open(Request(self.url+endpoint,method='HEAD')) as response:self.assertEqual(response.read(),b'');self.assertEqual(int(response.headers['Content-Length']),len(payload))
            with self.assertRaises(HTTPError) as caught:self.browser.open(Request(self.url+endpoint,headers={'Range':'bytes=9999-'}))
            self.assertEqual(caught.exception.code,416)
        for endpoint in ('/api/search','/api/preview?channel='+CID,'/api/message?id=9001'):
            with self.browser.open(self.url+endpoint) as response:result=json.load(response)
            self.assertEqual(result['media']['777'],'/media/'+digest)
