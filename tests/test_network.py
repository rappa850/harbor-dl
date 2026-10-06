import asyncio
import io
import json
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.downloads import DownloadManager
from backend.media import MediaInspector
from backend.network import NetworkConfig, cookie_file, redact
from backend.store import Store


class NetworkTests(unittest.TestCase):
    def test_authenticated_config_redaction_and_platform_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory)
            client = TestClient(app)
            self.assertEqual(client.get('/api/network').status_code, 401)
            client.post('/api/setup', json={'username':'admin', 'password':'test-password-123'})
            proxy = 'http://user:secret-proxy@127.0.0.1:9000'
            response = client.put('/api/network/proxy', json={'enabled':True, 'proxy':proxy, 'no_proxy':'.local,localhost'})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('secret-proxy', response.text)
            self.assertEqual(response.json()['proxy_display'], 'http://127.0.0.1:9000')
            response = client.put('/api/network/cookies/youtube', json={'cookie_content':'session=secret-cookie'})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('secret-cookie', response.text)
            network = NetworkConfig(app.state.store)
            self.assertEqual(network.for_url('https://youtube.com/video')['cookie_content'], 'session=secret-cookie')
            self.assertEqual(network.for_url('https://bilibili.com/video')['cookie_content'], '')
            self.assertEqual(network.for_url('http://service.local/video')['proxy'], '')
            self.assertEqual(network.for_url('http://example.org/video')['proxy'], proxy)
            self.assertNotIn('secret-proxy', redact('bad ' + proxy, network.for_url('https://youtube.com')))
            self.assertNotIn('secret-cookie', redact('bad secret-cookie', network.for_url('https://youtube.com')))
            # Empty proxy input keeps existing credentials without reflecting them.
            self.assertEqual(client.put('/api/network/proxy', json={'enabled':False}).status_code, 200)
            self.assertEqual(network.for_url('http://example.org')['proxy'], '')
            self.assertEqual(client.delete('/api/network/cookies/youtube').status_code, 200)
            self.assertEqual(network.for_url('https://youtube.com')['cookie_content'], '')
            self.assertEqual(client.put('/api/network/proxy', json={'proxy':'http://wrong', 'enabled':True}).status_code, 422)
            self.assertEqual(client.put('/api/network/cookies/youtube', json={'cookie_content':'bad value'}).status_code, 422)

    def test_cookie_file_cleanup_and_netscape_validation(self):
        with cookie_file('session=sample-secret', 'https://example.org/') as path:
            text = Path(path).read_text()
            self.assertIn('example.org\tFALSE', text)
            self.assertIn('session\tsample-secret', text)
        self.assertFalse(Path(path).exists())
        message = redact('private-cookie decoded-password', {
            'proxy': 'http://name:decoded%2Dpassword@localhost:9000',
            'cookie_content': '# Netscape HTTP Cookie File\n#HttpOnly_example.org\tFALSE\t/\tTRUE\t0\tsession\tprivate-cookie'})
        self.assertNotIn('private-cookie', message)
        self.assertNotIn('decoded-password', message)
        with self.assertRaises(ValueError):
            with cookie_file('# Netscape HTTP Cookie File\nbad-line', 'https://example.org/'):
                pass

    def test_real_cookie_and_proxy_reach_inspector_and_downloader(self):
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(8000)
            output.writeframes(bytes(16000))
        body = buffer.getvalue()
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def reply(self, send_body):
                requests.append((self.path, self.headers.get('Cookie', '')))
                if 'session=test-cookie' not in self.headers.get('Cookie', ''):
                    self.send_error(403); return
                self.send_response(200)
                self.send_header('Content-Type', 'audio/wav')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                if send_body:
                    self.wfile.write(body)
            def do_GET(self): self.reply(True)
            def do_HEAD(self): self.reply(False)
            def log_message(self, *_): pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store = Store(root / 'test.sqlite')
                network = NetworkConfig(store)
                network.save_proxy(True, f'http://127.0.0.1:{server.server_port}', '')
                network.save_cookie('universal', 'session=test-cookie')
                # This hostname cannot resolve directly: a successful transfer proves proxy use.
                url = 'http://media.invalid/sample.wav'
                async def exercise():
                    parsed = await MediaInspector().inspect(url, network.for_url(url))
                    manager = DownloadManager(store, root / 'downloads')
                    task = manager.create(url, parsed['title'], parsed['formats'][0]['id'], False, False)
                    await manager.run(task)
                    final = manager.get(task['id'])
                    self.assertEqual(final['status'], 'COMPLETED', final['error'])
                    self.assertEqual((manager.root / final['file_path']).read_bytes(), body)
                asyncio.run(exercise())
                self.assertTrue(len(requests) >= 2)
                self.assertTrue(all(path.startswith('http://media.invalid/') for path, _ in requests))
                self.assertTrue(all('test-cookie' in cookie for _, cookie in requests))
        finally:
            server.shutdown(); server.server_close(); thread.join()
