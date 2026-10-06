import asyncio
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
import websockets
from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient
from backend import browser_login
from backend.app import create_app
from backend.browser_login import BrowserLogin, Platform, PLATFORMS, find_chrome

CHROME=find_chrome()
LOCAL={'douyin':Platform('抖音','about:blank',('douyin.com',),('sessionid','sessionid_ss'))}   # never touch the real site in tests


def cookie(name,value,domain):
    return {'name':name,'value':value,'domain':domain,'path':'/','secure':True}


@unittest.skipUnless(CHROME,'需要本机安装 Chrome')
class RealChromeTests(unittest.TestCase):
    """Drives a real headless Chrome through the DevTools port with an isolated profile."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.patch=mock.patch.dict(PLATFORMS,LOCAL);self.patch.start()
        self.app=create_app(self.temp.name,browser_options={'headless':True},scheduler_options={'startup_delay':3600})
        self.client=TestClient(self.app).__enter__()
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
        self.browser=self.app.state.browser

    def tearDown(self):
        self.client.portal.call(self.browser.close)
        self.client.__exit__(None,None,None);self.patch.stop();self.temp.cleanup()

    def put_cookies(self,*cookies):
        self.client.portal.call(self.browser.cdp,'Storage.setCookies',{'cookies':list(cookies)})

    def test_login_flow_isolated_profile_save_and_restart(self):
        status=self.client.get('/api/browser').json()
        self.assertEqual((status['mode'],status['running'],status['chrome_found']),('desktop',False,True))
        self.assertEqual(self.client.post('/api/browser/douyin/save').status_code,409)      # nothing running yet
        started=self.client.post('/api/browser/douyin/login')
        self.assertEqual(started.status_code,200,started.text)
        self.assertTrue(started.json()['running']);self.assertFalse(started.json()['logged_in'])
        profile=Path(self.temp.name)/'browser'/'chrome-profile'
        self.assertTrue((profile/'Default').is_dir())                                        # own user directory, not the daily profile
        self.assertEqual(self.client.post('/api/browser/douyin/save').status_code,409)       # running but not logged in yet
        self.assertIn('尚未检测到',self.client.post('/api/browser/douyin/save').json()['detail'])
        self.put_cookies(cookie('sessionid','secret-session','.douyin.com'),cookie('ttwid','tw1','.douyin.com'),
                         cookie('other','must-not-leak','.example.com'),cookie('','nameless-value','.douyin.com'))
        self.assertTrue(self.client.get('/api/browser').json()['logged_in'])
        saved=self.client.post('/api/browser/douyin/save').json()
        self.assertEqual((saved['saved'],saved['cookie_count'],saved['skipped']),(True,2,1))   # nameless cookie skipped, save still works
        self.assertTrue(saved['network']['cookies']['douyin']['exists'])
        self.assertNotIn('secret-session',str(saved))
        stored=self.app.state.store.one("SELECT content FROM platform_cookies WHERE platform='douyin'")['content']
        self.assertIn('sessionid=secret-session',stored);self.assertIn('ttwid=tw1',stored);self.assertNotIn('must-not-leak',stored)
        self.assertEqual(self.app.state.catalog.network.for_url('https://www.douyin.com/')['cookie_content'],stored)
        self.assertEqual(self.client.post('/api/browser/close').json(),{'running':False})
        self.assertFalse(self.client.get('/api/browser').json()['running'])
        # the login survives in the dedicated profile; stale singleton files from a crash must not block a restart
        (profile/'SingletonLock').write_text('stale')
        again=self.client.post('/api/browser/douyin/login')
        self.assertEqual(again.status_code,200,again.text);self.assertTrue(again.json()['running'])

    def test_errors_and_auth(self):
        self.assertEqual(self.client.post('/api/browser/youtube/login').status_code,422)
        self.assertEqual(self.client.post('/api/browser/heartbeat').status_code,409)
        with mock.patch('backend.browser_login.find_chrome',return_value=None):
            response=self.client.post('/api/browser/douyin/login')
        self.assertEqual(response.status_code,409);self.assertIn('HARBOR_CHROME',response.json()['detail'])
        self.client.post('/api/auth/logout')
        for method,path in (('get','/api/browser'),('post','/api/browser/douyin/login'),('post','/api/browser/close')):
            self.assertEqual(getattr(self.client,method)(path).status_code,401)

    def test_user_closing_the_window_is_reported(self):
        self.client.post('/api/browser/douyin/login')
        self.client.portal.call(self.browser.terminate)
        status=self.client.get('/api/browser').json()
        self.assertFalse(status['running']);self.assertIsNone(status['platform'])


@unittest.skipUnless(CHROME,'需要本机安装 Chrome')
class DockerModeIdleTests(unittest.TestCase):
    def test_heartbeat_keeps_alive_and_silence_closes_the_browser(self):
        temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.addCleanup(temp.cleanup)
        ticks=[0.0]
        class Network:
            def save_cookie(self,*a):pass
        manager=BrowserLogin(temp.name,Network(),mode='docker',headless=True,idle_timeout=2,clock=lambda:ticks[0])
        async def scenario():
            with mock.patch.dict(PLATFORMS,LOCAL):
                await manager.start('douyin')
                self.assertTrue(manager.running())
                self.assertEqual((await manager.status())['idle_timeout'],2)
                ticks[0]=1.0;manager.heartbeat();ticks[0]=2.5            # 1.5 s since the heartbeat: still alive
                await asyncio.sleep(1.4);self.assertTrue(manager.running())
                ticks[0]=10.0                                              # silence beyond the timeout
                for _ in range(40):
                    if not manager.running():break
                    await asyncio.sleep(0.25)
                self.assertFalse(manager.running())
        try:asyncio.run(scenario())
        finally:asyncio.run(manager.close())

    def test_work_in_progress_prevents_idle_close(self):
        temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.addCleanup(temp.cleanup)
        ticks=[0.0]
        manager=BrowserLogin(temp.name,None,mode='docker',headless=True,idle_timeout=2,clock=lambda:ticks[0],busy=lambda:1)
        async def scenario():
            with mock.patch.dict(PLATFORMS,LOCAL):
                await manager.start('douyin');ticks[0]=100.0
                await asyncio.sleep(2.2);self.assertTrue(manager.running())
            await manager.close()
        asyncio.run(scenario())


class ConfigTests(unittest.TestCase):
    def test_mode_validation_and_defaults(self):
        with self.assertRaises(ValueError):BrowserLogin('.',None,mode='vnc')
        with mock.patch.dict(os.environ,{'HARBOR_BROWSER_MODE':'docker'}):self.assertEqual(BrowserLogin('.',None).mode,'docker')
        self.assertEqual(BrowserLogin('.',None).mode,'desktop')
        with mock.patch.dict(os.environ,{'HARBOR_CHROME':__file__}):self.assertEqual(find_chrome(),__file__)

    def test_command_uses_dedicated_profile_local_debug_port_and_container_flags(self):
        manager=BrowserLogin('/data',None,chrome=__file__);manager.port=9333
        desktop=manager.command(PLATFORMS['douyin'])
        self.assertIn(f'--user-data-dir={Path("/data")/"browser"/"chrome-profile"}',desktop)
        self.assertIn('--remote-debugging-address=127.0.0.1',desktop);self.assertNotIn('--no-sandbox',desktop)
        container=BrowserLogin('/data',None,chrome=__file__,mode='docker');container.port=9333
        self.assertIn('--no-sandbox',container.command(PLATFORMS['douyin']))

    def test_desktop_mode_does_not_expose_embedded_browser_routes(self):
        temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.addCleanup(temp.cleanup)
        app=create_app(temp.name,scheduler_options={'startup_delay':3600});client=TestClient(app)
        client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
        self.assertEqual(client.get('/novnc/vnc_lite.html').status_code,404)
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect('/websockify'):pass


class NoVncProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        novnc=Path(self.temp.name)/'novnc';novnc.mkdir();(novnc/'vnc_lite.html').write_text('<html>novnc</html>')
        (Path(self.temp.name)/'secret.txt').write_text('outside')
        ready=threading.Event();self.loop=asyncio.new_event_loop()
        async def echo(connection):
            async for message in connection:await connection.send(b'echo:'+(message if isinstance(message,bytes) else message.encode()))
        def serve():
            asyncio.set_event_loop(self.loop)
            async def start():
                self.server=await websockets.serve(echo,'127.0.0.1',0,subprotocols=['binary'])
                self.port=self.server.sockets[0].getsockname()[1];ready.set()
            self.loop.run_until_complete(start());self.loop.run_forever()
        self.thread=threading.Thread(target=serve,daemon=True);self.thread.start();ready.wait(5)
        env={'HARBOR_NOVNC_DIR':str(novnc),'HARBOR_VNC_WS':f'ws://127.0.0.1:{self.port}'}
        self.env=mock.patch.dict(os.environ,env);self.env.start()
        self.app=create_app(self.temp.name,browser_options={'mode':'docker'},scheduler_options={'startup_delay':3600})
        self.client=TestClient(self.app)

    def tearDown(self):
        self.client.close();self.env.stop()
        self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join(5);self.temp.cleanup()

    def login(self):
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def test_static_files_need_a_session_and_stay_inside_the_directory(self):
        self.assertEqual(self.client.get('/novnc/vnc_lite.html').status_code,401)
        self.login()
        self.assertEqual(self.client.get('/novnc/vnc_lite.html').text,'<html>novnc</html>')
        for hostile in ('/novnc/../secret.txt','/novnc/%2e%2e/secret.txt','/novnc/..%2fsecret.txt','/novnc/%2e%2e%2fsecret.txt'):
            self.assertNotIn('outside',self.client.get(hostile).text)
        self.assertEqual(self.client.get('/novnc/missing.js').status_code,404)

    def test_websocket_requires_session_and_same_origin_then_relays_both_ways(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/websockify',subprotocols=['binary']):pass
        self.login()
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/websockify',headers={'origin':'http://evil.example'}):pass
        with self.client.websocket_connect('/websockify',subprotocols=['binary'],headers={'origin':'http://testserver'}) as socket:
            socket.send_bytes(b'RFB 003.008\n')
            self.assertEqual(socket.receive_bytes(),b'echo:RFB 003.008\n')


if __name__=='__main__':unittest.main()
