import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from backend.app import create_app


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.client = TestClient(self.app)
        self.client.post('/api/setup', json={'username':'admin','password':'test-password-123'})

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def complete(self):
        manager = self.app.state.manager
        task = manager.create('https://example.org/video', '测试媒体')
        folder = manager.root / task['id']; folder.mkdir()
        media = folder / 'video.mp4'; media.write_bytes(b'0123456789')
        (folder / 'video.zh.vtt').write_text('WEBVTT')
        (folder / 'video.jpg').write_bytes(b'cover')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path=? WHERE id=?", (media.relative_to(manager.root).as_posix(),task['id']))
            current = dict(db.execute('SELECT * FROM tasks WHERE id=?',(task['id'],)).fetchone())
            manager.assets.register(db,current)
        return task, media

    def test_retained_file_remains_streamable_after_task_delete(self):
        task, media = self.complete()
        assets = self.client.get('/api/files').json()['items']
        asset = next(x for x in assets if x['is_primary'])
        response = self.client.delete(f"/api/tasks/{task['id']}?delete_file=false")
        self.assertEqual(response.status_code,200)
        self.assertTrue(media.exists())
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}").status_code,404)
        remaining = self.client.get('/api/files').json()['items']
        self.assertTrue(any(x['id']==asset['id'] and x['task_id'] is None for x in remaining))
        self.assertEqual(self.client.get(f"/api/files/{asset['id']}/download").content,b'0123456789')
        partial = self.client.get(f"/api/files/{asset['id']}/stream",headers={'Range':'bytes=2-5'})
        self.assertEqual(partial.status_code,206)
        self.assertEqual(partial.content,b'2345')

    def test_default_delete_removes_primary_and_attachments(self):
        task, media = self.complete()
        self.assertEqual(self.client.delete(f"/api/tasks/{task['id']}").status_code,200)
        self.assertFalse(media.parent.exists())
        self.assertEqual(self.client.get('/api/files?attachments=true').json()['items'],[])

    def test_primary_only_delete_keeps_related_assets(self):
        task, media = self.complete()
        self.assertEqual(self.client.delete(f"/api/tasks/{task['id']}?delete_related=false").status_code,200)
        self.assertFalse(media.exists())
        assets = self.client.get('/api/files?attachments=true').json()['items']
        self.assertEqual({x['extension'] for x in assets},{'.jpg','.vtt'})
        self.assertTrue(all(x['task_id'] is None for x in assets))

    def test_missing_and_escaping_paths_and_auth(self):
        task, media = self.complete()
        media.unlink()
        self.assertEqual(self.client.get(f"/api/files/{task['id']}/stream").status_code,404)
        with self.app.state.store.connect() as db:
            db.execute("INSERT INTO media_assets VALUES ('bad','../outside.mp4',NULL,'bad','video',1,'now')")
        (self.root / 'outside.mp4').write_bytes(b'private')
        self.assertEqual(self.client.get('/api/files/bad/download').status_code,404)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/files').status_code,401)

    def test_active_task_delete_rejected_and_backfill_id_stable(self):
        task, _ = self.complete()
        before = self.client.get('/api/files?attachments=true').json()['items']
        self.app.state.manager.assets.backfill()
        after = self.client.get('/api/files?attachments=true').json()['items']
        self.assertEqual([a['id'] for a in before],[a['id'] for a in after])
        pending = self.app.state.manager.create('https://example.org/next')
        self.assertEqual(self.client.delete(f"/api/tasks/{pending['id']}").status_code,409)
