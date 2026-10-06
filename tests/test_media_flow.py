import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.downloads import DownloadManager
from backend.media import format_choices, platform_for, share_url
from backend.store import Store


class Inspector:
    async def inspect(self, url, network=None):
        if 'broken' in url:
            raise ValueError('没有可用媒体')
        return {'url': url, 'title': '测试视频', 'formats': [{'id': 'v+a', 'label': '1080p'}]}


class MediaFlowTests(unittest.TestCase):
    def test_share_text_and_hostname(self):
        self.assertEqual(share_url('分享 https://youtu.be/abcdef 。更多内容'), 'https://youtu.be/abcdef')
        self.assertEqual(platform_for('https://www.youtube.com/watch?v=abcdef'), 'youtube')
        self.assertEqual(platform_for('https://youtube.com.example.org/watch'), 'universal')
        with self.assertRaises(ValueError):
            share_url('https://name:password@example.com/video')

    def test_formats_pair_audio_and_exclude_drm(self):
        choices = format_choices({'formats': [
            {'format_id': 'a', 'vcodec': 'none', 'acodec': 'aac', 'ext': 'm4a'},
            {'format_id': 'v', 'height': 1080, 'vcodec': 'avc', 'acodec': 'none', 'ext': 'mp4'},
            {'format_id': 'd', 'height': 2160, 'vcodec': 'avc', 'has_drm': True},
        ]})
        self.assertEqual([f['id'] for f in choices], ['v+a', 'a'])
        self.assertTrue(choices[0]['requires_merge'])

    def test_parse_create_retry_preserve_user_options(self):
        with tempfile.TemporaryDirectory() as directory:
            # Without lifespan the queue stays pending; no external network is used.
            app = create_app(directory, inspector=Inspector())
            client = TestClient(app)
            self.assertEqual(client.post('/api/media/parse', json={'text': 'https://youtu.be/abcdef'}).status_code, 401)
            self.assertEqual(client.post('/api/setup', json={'username': 'admin', 'password': 'test-password-123'}).status_code, 201)
            parsed = client.post('/api/media/parse', json={'text': '分享 https://youtu.be/abcdef！'}).json()
            self.assertEqual(parsed['url'], 'https://youtu.be/abcdef')
            response = client.post('/api/tasks', json={'url': parsed['url'], 'title': parsed['title'],
                'format_id': 'v+a', 'subtitles': False, 'thumbnail': True})
            self.assertEqual(response.status_code, 201)
            task = response.json()
            self.assertEqual((task['format_id'], task['subtitles'], task['thumbnail'], task['source']), ('v+a', 0, 1, 'youtube'))
            self.assertEqual(client.post(f"/api/tasks/{task['id']}/cancel").status_code, 200)
            retry = client.post(f"/api/tasks/{task['id']}/retry").json()
            self.assertEqual(retry['format_id'], 'v+a')
            self.assertEqual(retry['subtitles'], 0)
            self.assertEqual(client.post('/api/media/parse', json={'text': 'https://example.org/broken'}).status_code, 422)
            command = app.state.manager.command(retry, Path(directory))
            self.assertIn('backend.download_worker', command)
            self.assertNotIn(retry['url'], command)

    def test_schema_upgrade_keeps_existing_tasks(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'store.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,url TEXT,title TEXT,status TEXT,created_at TEXT,updated_at TEXT)')
                db.execute("INSERT INTO tasks VALUES ('old','https://example.org/video','已有任务','PENDING','now','now')")
            db.close()
            store = Store(path)
            old = store.one("SELECT * FROM tasks WHERE id='old'")
            self.assertEqual(old['title'], '已有任务')
            self.assertEqual(old['status'], 'PENDING')
            self.assertEqual(old['subtitles'], 1)
            self.assertEqual(old['format_id'], 'bestvideo+bestaudio/best')

    def test_real_local_media_inspection_and_download(self):
        import asyncio
        import functools
        import threading
        import wave
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        from backend.media import MediaInspector

        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with wave.open(str(root / 'sample.wav'), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b'\0\0' * 8000)
            server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}/sample.wav'

            async def exercise():
                parsed = await MediaInspector().inspect(url)
                self.assertTrue(parsed['formats'])
                manager = DownloadManager(Store(root / 'store.sqlite'), root / 'downloads')
                task = manager.create(url, parsed['title'], parsed['formats'][0]['id'], False, False)
                await manager.run(task)
                final = manager.get(task['id'])
                self.assertEqual(final['status'], 'COMPLETED', final['error'])
                self.assertEqual((manager.root / final['file_path']).read_bytes(), (root / 'sample.wav').read_bytes())

            try:
                asyncio.run(exercise())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
