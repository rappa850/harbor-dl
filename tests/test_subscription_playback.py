import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from backend.app import create_app
from tests.test_subscription_catalog import CatalogInspector


class SubscriptionPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name, inspector=CatalogInspector())
        self.client = TestClient(self.app)
        self.client.post('/api/setup', json={'username': 'admin', 'password': 'test-password-123'})
        self.client.post('/api/backup/subscriptions/import', json={'subscriptions': [
            {'platform': 'youtube', 'user_id': 'UCexample', 'youtube_tab_type': 'videos'},
            {'platform': 'youtube', 'user_id': 'UCexample', 'youtube_tab_type': 'shorts'}]})
        self.scopes = [item['id'] for item in self.client.get('/api/subscriptions').json()['items']]
        self.assertEqual(len(self.scopes), 2)
        for scope in self.scopes:
            self.assertEqual(self.client.post(f'/api/subscriptions/{scope}/sync').status_code, 200)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def works(self, scope):
        return self.client.get(f'/api/subscriptions/{scope}/videos').json()['videos']

    def complete(self, scope, work, registered=True, extension='wav'):
        task = self.client.post(f'/api/subscriptions/{scope}/videos/{work["id"]}/download', json={}).json()
        manager = self.app.state.manager
        folder = manager.root / task['id']
        folder.mkdir()
        path = folder / ('sample.' + extension)
        path.write_bytes(b'local fixture')
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET status=?,file_path=? WHERE id=?',
                       ('COMPLETED', path.relative_to(manager.root).as_posix(), task['id']))
            manager.event(db, task['id'], 'COMPLETED', 'fixture completed')
            if registered:
                manager.assets.register(db, dict(db.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone()))
        return task, path

    def playlist(self, scope):
        response = self.client.get(f'/api/subscriptions/{scope}/playable')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_playlist_uses_scoped_registered_existing_media(self):
        scope, other = self.scopes
        works = self.works(scope)
        self.complete(scope, works[0])
        _, missing = self.complete(scope, works[1])
        missing.unlink()
        self.complete(scope, works[2], registered=False)
        self.complete(scope, works[3], extension='txt')
        self.client.post(f'/api/subscriptions/{scope}/videos/{works[4]["id"]}/download', json={})
        self.complete(other, self.works(other)[0])
        playlist = self.playlist(scope)
        self.assertEqual(playlist['total'], 1)
        item = playlist['items'][0]
        self.assertEqual(item['work_id'], works[0]['id'])
        self.assertEqual(item['subscription_id'], scope)
        self.assertEqual(item['kind'], 'audio')
        record = next(work for work in self.works(scope) if work['id'] == item['work_id'])
        self.assertEqual(record['asset_id'], item['id'])
        self.assertEqual(self.client.get(f'/api/files/{item["id"]}/stream').content, b'local fixture')
        self.assertNotEqual(self.playlist(other)['items'][0]['work_id'], item['work_id'])

    def test_keep_files_retains_playlist_identity_delete_files_removes_entry(self):
        scope = self.scopes[0]
        task, path = self.complete(scope, self.works(scope)[0])
        original = self.playlist(scope)['items'][0]
        self.assertEqual(self.client.delete(f'/api/tasks/{task["id"]}?delete_file=false').status_code, 200)
        self.assertEqual(self.playlist(scope)['items'][0], original)
        path.unlink()
        self.assertEqual(self.playlist(scope)['total'], 0)
        task, _ = self.complete(scope, self.works(scope)[1])
        self.assertEqual(self.client.delete(f'/api/tasks/{task["id"]}').status_code, 200)
        self.assertEqual(self.playlist(scope)['total'], 0)

    def test_work_progress_survives_restart_and_resync_without_scope_leakage(self):
        scope, other = self.scopes
        work = self.works(scope)[0]
        self.complete(scope, work)
        payload = {'current_index': 0, 'playback_mode': 'random', 'video_progress': {work['id']: 12.5}}
        self.assertEqual(self.client.put(f'/api/playback/record/{scope}', json=payload).status_code, 200)
        self.client.close()
        self.app = create_app(self.temp.name, inspector=CatalogInspector())
        self.client = TestClient(self.app)
        self.client.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password-123'})
        self.client.post(f'/api/subscriptions/{scope}/sync')
        record = self.client.get(f'/api/playback/record/{scope}').json()
        self.assertEqual(record['video_progress'], payload['video_progress'])
        self.assertEqual(record['playback_mode'], 'random')
        self.assertEqual(self.playlist(scope)['items'][0]['work_id'], work['id'])
        self.assertIsNone(self.client.get(f'/api/playback/record/{other}').json())

    def test_unknown_scope_and_authentication(self):
        self.assertEqual(self.client.get(f'/api/subscriptions/{uuid4()}/playable').status_code, 404)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get(f'/api/subscriptions/{self.scopes[0]}/playable').status_code, 401)
