import http.cookiejar
import json
from pathlib import Path
import argparse
from urllib.request import build_opener, HTTPCookieProcessor, Request

browser=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]/'Data'
info={}
try:info=json.loads((root/'service.json').read_text(encoding='utf-8'))
except (OSError,ValueError):pass
port=args.port or int(info.get('port',8765))
base='http://127.0.0.1:%s'%port
try:
    with browser.open(base+'/api/health',timeout=3) as response:
        health=json.load(response)
        if health.get('app')!='Discord Archive Studio' or (not args.port and info and health.get('library_id')!=info.get('library_id')):
            print('Another service uses this port; nothing was stopped.')
            raise SystemExit(0)
    browser.open(base+'/',timeout=3).close()
    browser.open(Request(base+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Studio-Action':'local'}),timeout=3).close()
    print('Archive service stopped; captured data is preserved.')
except OSError:
    print('Archive service is not running at its saved local address.')
