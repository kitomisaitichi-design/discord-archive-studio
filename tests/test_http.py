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

    def post(self,path,data,headers=None):
        return self.browser.open(Request(self.url+'/api/'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Studio-Action':'local',**(headers or {})}),timeout=3)

    def test_health_html_js_css_and_state(self):
        with self.browser.open(self.url+'/api/health') as response:
            self.assertEqual(json.load(response)['app'],'Discord Archive Studio')
        with self.browser.open(self.url+'/') as response:
            self.assertIn('SameSite=Strict',response.headers['Set-Cookie'])
            self.assertIn(b'Keep the conversation.',response.read())
        for resource in ('app.js','style.css','server-picker.js','queue.js','people.js'):
            with self.browser.open(self.url+'/'+resource) as response:self.assertGreater(len(response.read()),100)
        with self.browser.open(self.url+'/api/state') as response:
            self.assertNotIn('token',json.load(response)['connection'])
        with self.browser.open(self.url+'/api/people') as response:self.assertEqual(json.load(response)['contacts'],[])
        with self.browser.open(self.url+'/api/preview?channel=1') as response:self.assertEqual(json.load(response)['messages'],[])

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
