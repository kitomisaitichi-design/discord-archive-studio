import argparse
import os
from pathlib import Path
import subprocess
import threading
import urllib.request
import json
import webbrowser
import sys
import traceback
import ctypes
from studio.store import Store
from studio.runtime import Connection, Worker
from studio.server import Server
from studio.launching import LibraryLock, running_port, bind_server, save_address, preferred_port


def open_app(port):
    url = 'http://127.0.0.1:%s/' % port
    if os.name == 'nt':
        candidates = [Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'Microsoft/Edge/Application/msedge.exe',
                      Path(os.environ.get('PROGRAMFILES', '')) / 'Microsoft/Edge/Application/msedge.exe',
                      Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Edge/Application/msedge.exe',
                      Path(os.environ.get('PROGRAMFILES', '')) / 'Google/Chrome/Application/chrome.exe']
        for browser in candidates:
            if browser.is_file():
                subprocess.Popen([str(browser), '--app='+url, '--new-window', '--window-size=1480,960','--window-position=40,40'])
                return
    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description='Discord Archive Studio: local read-only archive client')
    parser.add_argument('--port', type=int, default=None, help='Optional fixed port; automatic free-port selection is the default.')
    parser.add_argument('--data', type=Path, default=Path(__file__).resolve().parent / 'Data')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--no-connect', action='store_true')
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    args.data=args.data.resolve()
    with LibraryLock(args.data) as lock:
        if not lock.acquired:
            port=running_port(args.data)
            if not args.no_browser:
                open_app(port)
            return
        run_service(args)


def run_service(args):
    store = Store(args.data)
    if args.demo:
        from studio.demo import seed
        seed(store)
        args.no_connect = True
    connection = Connection(store)
    worker = Worker(store, connection)
    server = bind_server(lambda address:Server(address,store,connection,worker),args.port,preferred_port(args.data))
    port=server.server_port
    save_address(args.data,port)
    server.native_window_enabled = not args.no_browser
    if not args.no_connect:
        threading.Thread(target=connection.monitor, daemon=True).start()
    worker_thread = threading.Thread(target=worker.run, daemon=True)
    worker_thread.start()
    if not args.no_browser:
        open_app(port)
    print('Discord Archive Studio listening locally on port', port, flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop.set()
        worker.signal()
        connection.stop.set()
        connection.reconnect.set()
        # Let a bounded network read finish and ZIP/media finally blocks clean up.
        worker_thread.join(timeout=50)
        server.server_close()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        root=Path(__file__).resolve().parent/'Data'
        root.mkdir(parents=True,exist_ok=True)
        log=root/'startup-error.txt'
        log.write_text(traceback.format_exc(),encoding='utf-8')
        if os.name=='nt' and '--no-browser' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None,'The archive could not start:\n\n'+str(error)+'\n\nDetails: '+str(log),'Discord Archive Studio — startup error',0x10)
        if sys.stderr is not None:
            traceback.print_exc()
        raise SystemExit(1)
