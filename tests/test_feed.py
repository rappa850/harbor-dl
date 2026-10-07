import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from backend.api_tokens import ApiTokens
from backend.app import create_app


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = TestClient(self.app)
        self.client.post('/api/setup', json={'username': 'admin', 'password': 'test-password-123'})

    def tearDown(self):
        self.client.close(); self.temp.cleanup()

    def add(self, name, author='', stamp='2026-01-01T00:00:00+00:00'):
        manager = self.app.state.manager
        task = manager.create(f'https://example.org/{name}', name)
        folder = manager.root / task['id']; folder.mkdir()
        media = folder / f'{name}.mp4'; media.write_bytes(b'0123456789')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path=?,author=?,updated_at=? WHERE id=?",
                       (media.relative_to(manager.root).as_posix(), author, stamp, task['id']))
            manager.assets.register(db, dict(db.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone()))
        return task, media

    def feed(self, **params):
        response = self.client.get('/api/feed', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_requires_login(self):
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.get('/api/feed').status_code, 401)

    def test_latest_first_and_cursor_pages_without_overlap(self):
        for n in range(5):
            self.add(f'v{n}', 'alice', f'2026-01-0{n + 1}T00:00:00+00:00')
        first = self.feed(limit=2)
        self.assertEqual((first['total'], [i['title'] for i in first['items']]), (5, ['v4', 'v3']))
        second = self.feed(limit=2, cursor=first['next'])
        last = self.feed(limit=2, cursor=second['next'])
        self.assertEqual([i['title'] for i in second['items'] + last['items']], ['v2', 'v1', 'v0'])
        self.assertIsNone(last['next'])
        item = first['items'][0]
        self.assertEqual((item['author'], item['kind'], item['stream']), ('alice', 'video', f"/api/files/{item['id']}/stream"))

    def test_random_is_stable_per_seed_and_complete(self):
        for n in range(8):
            self.add(f'v{n}')
        pages = lambda seed: [i['id'] for p in (self.feed(mode='random', seed=seed, limit=50),) for i in p['items']]
        a = self.feed(mode='random', seed='s1', limit=5)
        b = self.feed(mode='random', seed='s1', limit=5, cursor=a['next'])
        ids = [i['id'] for i in a['items'] + b['items']]
        self.assertEqual((len(ids), len(set(ids))), (8, 8))
        self.assertEqual(pages('s1'), pages('s1'))
        self.assertEqual(sorted(pages('s1')), sorted(pages('s2')))

    def test_author_filter_and_missing_file_skipped(self):
        self.add('a1', 'alice'); self.add('b1', 'bob')
        _, gone = self.add('a2', 'alice')
        gone.unlink()
        self.assertEqual([i['title'] for i in self.feed(author='alice')['items']], ['a1'])
        self.assertEqual(self.feed()['total'], 2)

    def test_app_login_issues_bearer_token_without_cookie(self):
        creds = {'username': 'admin', 'password': 'test-password-123'}
        with TestClient(self.app) as phone:
            bad = phone.post('/api/auth/app-login', json={**creds, 'password': 'wrong-password-1'})
            self.assertEqual(bad.status_code, 401)
            ok = phone.post('/api/auth/app-login', json={**creds, 'device': 'Pixel'})
            self.assertEqual(ok.status_code, 200)
            self.assertNotIn('set-cookie', ok.headers)
            token = ok.json()['token']
            self.assertTrue(token.startswith('harbor_'))
            phone.cookies.clear()
            self.assertEqual(phone.get('/api/feed').status_code, 401)
            self.assertEqual(phone.get('/api/feed', headers={'Authorization': f'Bearer {token}'}).status_code, 200)
        names = [t['name'] for t in self.client.get('/api/auth/tokens').json()['items']]
        self.assertEqual(names, ['Pixel'])

    def test_stream_is_cacheable_but_api_stays_no_store(self):
        self.add('v')
        item = self.feed()['items'][0]
        stream = self.client.get(item['stream'])
        self.assertEqual(stream.headers['cache-control'], 'private, max-age=86400')
        self.assertEqual(self.client.get('/api/feed').headers['cache-control'], 'no-store')

    def test_poster_falls_back_to_a_cut_frame(self):
        import subprocess
        from backend.live_recording import ffmpeg_executable
        ffmpeg = ffmpeg_executable()
        if not ffmpeg:
            self.skipTest('ffmpeg not available')
        _, media = self.add('real')
        made = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                               'color=c=red:s=64x96:d=2', '-pix_fmt', 'yuv420p', str(media)], capture_output=True)
        self.assertEqual(made.returncode, 0, made.stderr)
        item = self.feed()['items'][0]
        self.assertEqual(item['cover'], f"/api/files/{item['id']}/poster")
        poster = self.client.get(item['cover'])
        self.assertEqual((poster.status_code, poster.headers['content-type'], poster.content[:2]), (200, 'image/jpeg', b'\xff\xd8'))
        self.assertIn('max-age=604800', poster.headers['cache-control'])
        self.assertEqual(self.client.get(item['cover']).content, poster.content)

    def test_poster_404_for_unreadable_video_and_unknown_id(self):
        self.add('broken')
        item = self.feed()['items'][0]
        self.assertEqual(self.client.get(item['cover']).status_code, 404)
        self.assertEqual(self.client.get('/api/files/nope/poster').status_code, 404)

    def test_favorites_flow_and_order(self):
        for n in range(3):
            self.add(f'v{n}', 'alice', f'2026-01-0{n + 1}T00:00:00+00:00')
        ids = {i['title']: i['id'] for i in self.feed()['items']}
        self.assertEqual(self.feed(mode='favorites')['items'], [])
        for title in ('v0', 'v2'):
            self.assertEqual(self.client.put(f'/api/favorites/{ids[title]}').json(), {'favorite': True})
        self.assertEqual(self.client.put(f'/api/favorites/{ids["v0"]}').status_code, 200)  # idempotent
        mine = self.feed(mode='favorites')
        self.assertEqual([i['title'] for i in mine['items']], ['v2', 'v0'])
        self.assertEqual({i['title']: i['favorite'] for i in self.feed()['items']}, {'v0': True, 'v1': False, 'v2': True})
        self.client.delete(f'/api/favorites/{ids["v2"]}')
        self.assertEqual([i['title'] for i in self.feed(mode='favorites')['items']], ['v0'])
        self.assertEqual(self.client.put('/api/favorites/nope').status_code, 404)

    def test_history_records_position_and_orders_by_recency(self):
        self.add('a'); self.add('b')
        ids = {i['title']: i['id'] for i in self.feed()['items']}
        self.assertEqual(self.client.post('/api/history', json={'asset_id': ids['a'], 'position': 12.5}).status_code, 200)
        self.client.post('/api/history', json={'asset_id': ids['b'], 'position': 3})
        self.client.post('/api/history', json={'asset_id': ids['a'], 'position': 20})
        seen = self.feed(mode='history')['items']
        self.assertEqual([(i['title'], i['position']) for i in seen], [('a', 20), ('b', 3)])
        self.assertEqual(self.client.post('/api/history', json={'asset_id': ids['a'], 'position': -1}).status_code, 422)
        self.assertEqual(self.client.post('/api/history', json={'asset_id': 'nope'}).status_code, 404)
        self.assertEqual(self.client.delete('/api/history').json(), {'removed': 2})
        self.assertEqual(self.feed(mode='history')['items'], [])

    def test_state_is_per_user(self):
        self.add('a')
        asset = self.feed()['items'][0]['id']
        self.client.put(f'/api/favorites/{asset}')
        self.client.post('/api/history', json={'asset_id': asset, 'position': 5})
        with self.app.state.store.connect() as db:
            db.execute("INSERT INTO users(username,password,created_at) VALUES ('second','x','now')")
            second = db.execute("SELECT id FROM users WHERE username='second'").fetchone()['id']
        token = ApiTokens(self.app.state.store).create(second, 'phone', None)['token']
        with TestClient(self.app) as other:
            other.headers['Authorization'] = f'Bearer {token}'
            self.assertEqual(other.get('/api/feed', params={'mode': 'favorites'}).json()['items'], [])
            self.assertEqual(other.get('/api/feed', params={'mode': 'history'}).json()['items'], [])
            self.assertFalse(other.get('/api/feed').json()['items'][0]['favorite'])
        self.assertTrue(self.feed()['items'][0]['favorite'])

    def test_authors_counts(self):
        self.add('a1', 'alice'); self.add('a2', 'alice'); self.add('b1', 'bob'); self.add('n1', '')
        self.assertEqual(self.client.get('/api/authors').json()['items'],
                         [{'author': 'alice', 'count': 2}, {'author': 'bob', 'count': 1}])

    def test_validation(self):
        self.assertEqual(self.client.get('/api/feed', params={'cursor': '!!'}).status_code, 422)
        self.assertEqual(self.client.get('/api/feed', params={'mode': 'x'}).status_code, 422)
        self.assertEqual(len(self.feed(limit=9999)['items']), 0)


if __name__ == '__main__':
    unittest.main()
