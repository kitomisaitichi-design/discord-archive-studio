import http.cookiejar
import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request
from studio.store import Store
from studio.runtime import Connection, Worker
from studio.server import Server


class LocalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        store = Store(self.temp.name)
        connection = Connection(store)
        self.server = Server(('127.0.0.1',0),store,connection,Worker(store,connection))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url='http://127.0.0.1:%s' % self.server.server_port
        self.browser=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2);self.temp.cleanup()

    def test_emoji_endpoint_resolves_saved_refs_caps_repeated_request_and_fallback(self):
        from test_studio import SID,CID,message
        from studio.reader_library import library_id
        self.browser.open(self.url+'/reader.html').close()
        self.server.store.catalog([{'id':SID,'name':'Fixture'}],[{'id':CID,'name':'chat'}],SID)
        self.server.store.upsert(CID,[message(9001,'<:Clueless:123>')])
        for source in ({},{'archive':library_id(SID),'channel':CID}):
            with self.post('emojis/visible',dict(source,messages=['9001'])) as response:self.assertEqual(json.load(response)['emojis']['123']['status'],'queued')
        with self.server.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM emojis').fetchone()[0],1)
        with self.browser.open(self.url+'/api/emojis/library?q=Clueless') as response:self.assertEqual(len(json.load(response)['emojis']),1)
        with self.post('emojis/visible',{'messages':['9999']}) as response:self.assertEqual(json.load(response)['emojis'],{})
        for invalid in ([],['https://evil.test/emoji'],['9001']*81):
            with self.assertRaises(HTTPError):self.post('emojis/visible',{'messages':invalid})

    def test_visible_avatar_endpoint_resolves_saved_ids_and_rejects_arbitrary_urls(self):
        from test_studio import SID,CID,UID,message
        from studio.reader_library import library_id
        self.browser.open(self.url+'/reader.html').close()
        self.server.store.catalog([{'id':SID,'name':'Fixture'}],[{'id':CID,'name':'chat'}],SID)
        m=message(9001);m['author']['avatar']='a'*32;self.server.store.upsert(CID,[m])
        for source in ({},{'archive':library_id(SID),'channel':CID}):
            with self.post('avatars/visible',dict(source,messages=['9001','9999'])) as response:
                result=json.load(response);self.assertEqual(result['pictures']['9001']['status'],'queued');self.assertNotIn('9999',result['pictures'])
        self.assertEqual(len(self.server.worker.exporter.avatars.tasks()),1)
        for bad in ([],['https://evil.test/picture'],['9001']*81):
            with self.assertRaises(HTTPError):self.post('avatars/visible',{'messages':bad})

    def post(self,path,data,headers=None):
        return self.browser.open(Request(self.url+'/api/'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Studio-Action':'local',**(headers or {})}),timeout=3)

    def test_health_html_js_css_and_state(self):
        with self.browser.open(self.url+'/api/health') as response:
            self.assertEqual(json.load(response)['app'],'Discord Archive Studio')
        with self.browser.open(self.url+'/') as response:
            self.assertIn('SameSite=Strict',response.headers['Set-Cookie'])
            self.assertIn(b'Keep the conversation.',response.read())
        for resource in ('app.js','style.css','server-picker.js','queue.js','queue-settings.js','people.js','archives.js','reader.js','reader.css','avatar-cache.js','emoji-cache.js','emoji-library.js'):
            with self.browser.open(self.url+'/'+resource) as response:self.assertGreater(len(response.read()),100)
        with self.browser.open(self.url+'/api/state') as response:
            self.assertNotIn('token',json.load(response)['connection'])
        with self.browser.open(self.url+'/api/people') as response:self.assertEqual(json.load(response)['contacts'],[])
        with self.browser.open(self.url+'/api/preview?channel=1') as response:self.assertEqual(json.load(response)['messages'],[])

    def test_reader_tab_cookie_native_archive_routes_upload_and_asset_guard(self):
        from test_studio import SID,CID,message
        from studio.exporting import options
        self.server.store.catalog([{'id':SID,'name':'Fixture'}],[{'id':CID,'name':'general'}],SID)
        self.server.store.upsert(CID,[message(9001,'Local reader route')])
        result=self.server.worker.exporter.publish(SID,options(None),self.server.worker.destination())
        with self.browser.open(self.url+'/reader.html') as response:self.assertIn(b'Message explorer',response.read())
        with self.browser.open(self.url+'/api/reader/catalog') as response:key=json.load(response)['archives'][0]['id']
        with self.browser.open(self.url+'/api/reader/overview?archive='+key) as response:self.assertEqual(json.load(response)['channels'][0]['messages'],1)
        with self.browser.open(self.url+'/api/reader/messages?archive='+key+'&channel='+CID) as response:self.assertEqual(json.load(response)['messages'][0]['content'],'Local reader route')
        with self.assertRaises(HTTPError):self.browser.open(self.url+'/api/reader/asset?archive='+key+'&id=../../credentials')
        with self.assertRaises(HTTPError):self.post('avatars/select',{'channels':[]})
        with self.post('avatars/select',{'channels':[CID]}) as response:self.assertEqual(json.load(response)['queued'],0)

    def test_bulk_schedule_endpoint_remove_repeat_restore_and_owner_guard(self):
        self.browser.open(self.url+'/').close()
        store=self.server.store;self.server.connection.account={'id':'7','name':'Fixture'}
        store.catalog([{'id':'10','name':'Fixture'}],[{'id':'11','name':'One','type':0}],'10')
        from studio.exporting import DEFAULT_OPTIONS
        store.schedule('channel:11','7',True,'fixed',1440,DEFAULT_OPTIONS)
        for expected in (1,0):
            with self.post('schedules/manage',{'action':'remove','scopes':['channel:11']}) as response:self.assertEqual(json.load(response)['changed'],expected)
        with self.browser.open(self.url+'/api/state') as response:self.assertTrue(json.load(response)['schedule_recovery'])
        with self.post('schedules/manage',{'action':'restore'}) as response:self.assertEqual(json.load(response)['changed'],1)
        self.server.connection.account={'id':'8','name':'Other'}
        with self.assertRaises(HTTPError):self.post('schedule',{'scope':'channel:11','enabled':False})
        self.assertEqual(store.schedules()[0]['owner_id'],'7')

    def test_queue_settings_and_preferences_are_owner_scoped_and_return_in_state(self):
        self.browser.open(self.url+'/').close();store=self.server.store
        self.server.connection.account={'id':'7','name':'Fixture'}
        with self.post('queue/preferences',{'owner':'7','options':{'page_delay':10},'minutes':10080,'mode':'adaptive'}) as response:self.assertEqual(json.load(response)['options']['page_delay'],10)
        with self.post('queue/configure',{'owner':'7','target':'future','changes':{'cooldown_minutes':15}}) as response:self.assertTrue(json.load(response)['future'])
        with self.browser.open(self.url+'/api/state') as response:
            state=json.load(response);self.assertEqual(state['queue_defaults'],{'cooldown_minutes':15});self.assertEqual(state['queue_preferences']['minutes'],10080)
        self.server.connection.account={'id':'8','name':'Other'}
        with self.assertRaises(HTTPError):self.post('queue/preferences',{'owner':'7','options':{'page_delay':1}})
        with self.browser.open(self.url+'/api/state') as response:self.assertEqual(json.load(response)['queue_preferences'],{})

    def test_sensitive_api_requires_cookie_and_post_requires_origin(self):
        with self.assertRaises(HTTPError) as failure:self.browser.open(self.url+'/api/state')
        self.assertEqual(failure.exception.code,403)
        self.browser.open(self.url+'/').close()
        with self.assertRaises(HTTPError) as failure:self.post('settings',{'auto_connect':False},{'Origin':'https://unrelated.example'})
        self.assertEqual(failure.exception.code,403)

    def test_browser_pair_code_single_use_and_key_has_limited_scope(self):
        self.browser.open(self.url+'/').close()
        with self.post('pair-code',{}) as response:code=json.load(response)['code']
        extension={'Origin':'chrome-extension://'+'a'*32}
        with self.post('bridge/pair',{'code':code},extension) as response:key=json.load(response)['key']
        self.assertGreater(len(key),30)
        with self.assertRaises(HTTPError):self.post('bridge/pair',{'code':code},extension)
        # A connector key cannot change archive settings without a valid local browser session.
        outsider=build_opener()
        request=Request(self.url+'/api/settings',data=b'{"auto_connect":false}',headers={**extension,'X-Bridge-Key':key,'X-Studio-Action':'local','Content-Type':'application/json'})
        with self.assertRaises(HTTPError):outsider.open(request)

    def test_double_preset_submission_is_one_preset(self):
        self.browser.open(self.url+'/').close()
        for _ in range(2):self.post('preset',{'name':'Gentle','options':{'formats':['json']}}).close()
        with self.browser.open(self.url+'/api/state') as response:self.assertEqual(len(json.load(response)['presets']),1)

    def test_instances_on_different_ports_do_not_overwrite_each_others_cookie(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);connection=Connection(store)
            second=Server(('127.0.0.1',0),store,connection,Worker(store,connection))
            thread=threading.Thread(target=second.serve_forever,daemon=True);thread.start()
            try:
                self.browser.open(self.url+'/').close()
                self.browser.open('http://127.0.0.1:'+str(second.server_port)+'/').close()
                with self.post('settings',{'auto_connect':False}) as response:self.assertTrue(json.load(response)['ok'])
                with self.browser.open('http://127.0.0.1:'+str(second.server_port)+'/api/state') as response:self.assertIn('stats',json.load(response))
            finally:
                second.shutdown();second.server_close();thread.join(2)

    def test_privileged_extension_without_origin_still_needs_pair_secret(self):
        self.browser.open(self.url+'/').close()
        with self.post('pair-code',{}) as response:code=json.load(response)['code']
        with self.post('bridge/pair',{'code':code,'extension_id':'a'*32}) as response:key=json.load(response)['key']
        self.assertTrue(key)
        with self.assertRaises(HTTPError):self.post('bridge/connect',{'extension_id':'a'*32,'token':'fake'})
        with self.assertRaises(HTTPError):self.post('bridge/connect',{'extension_id':'b'*32,'token':'fake'},{'Origin':'chrome-extension://'+'a'*32,'X-Bridge-Key':key})


if __name__=='__main__':unittest.main()
