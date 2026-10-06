import asyncio
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from backend.browser_fetch import BrowserFetchError,fetch_in_page,proxy_argument
from backend.browser_login import find_chrome


class Handler(BaseHTTPRequestHandler):
    hits={'data':0}
    def log_message(self,*a):pass
    def do_GET(self):
        if self.path.startswith('/data'):
            Handler.hits['data']+=1
            # the "page SDK" is only ready from the third call on, like a signing script that loads late
            body=json.dumps({'ready':True,'value':42} if Handler.hits['data']>=3 else {'ready':False}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
        else:
            body=b'<html><title>page</title></html>';self.send_response(200);self.send_header('Content-Type','text/html')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)


@unittest.skipUnless(find_chrome(),'需要本机安装 Chrome')
class FetchInPageTests(unittest.TestCase):
    def setUp(self):
        Handler.hits['data']=0
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def run_fetch(self,judge,**kw):
        return asyncio.run(fetch_in_page(self.base+'/page',"fetch('/data').then(r=>r.text())",judge,interval=0.3,**kw))

    def test_retries_until_the_page_is_ready_then_returns_the_decision(self):
        def judge(value):
            data=json.loads(value) if value else {}
            return ('ok',data['value']) if data.get('ready') else ('retry',None)
        self.assertEqual(self.run_fetch(judge,timeout=30),42)
        self.assertGreaterEqual(Handler.hits['data'],3)

    def test_fail_decision_and_timeout_surface_as_errors(self):
        with self.assertRaisesRegex(BrowserFetchError,'不可访问'):self.run_fetch(lambda v:('fail','作品不可访问'),timeout=30)
        with self.assertRaisesRegex(BrowserFetchError,'超时'):self.run_fetch(lambda v:('retry',None),timeout=6)


class ProxyTests(unittest.TestCase):
    def test_proxy_flag_and_credentials_refused(self):
        self.assertEqual(proxy_argument(''),[])
        self.assertEqual(proxy_argument('http://127.0.0.1:7890'),['--proxy-server=http://127.0.0.1:7890'])
        with self.assertRaises(BrowserFetchError):proxy_argument('http://user:pw@127.0.0.1:7890')

    def test_missing_chrome_is_reported(self):
        from unittest import mock
        with mock.patch('backend.browser_fetch.find_chrome',return_value=None):
            with self.assertRaisesRegex(BrowserFetchError,'HARBOR_CHROME'):
                asyncio.run(fetch_in_page('about:blank','1',lambda v:('ok',v)))


if __name__=='__main__':unittest.main()
