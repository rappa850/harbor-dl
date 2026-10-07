import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.covers import key_for

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32
JPEG = b'\xff\xd8\xff' + b'0' * 32
CREDS = {'username': 'admin', 'password': 'test-password-123'}


class BloggerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = TestClient(self.app)
        self.client.post('/api/setup', json=CREDS)

    def tearDown(self):
        self.client.close(); self.temp.cleanup()

    def add(self, name, author, stamp):
        manager = self.app.state.manager
        task = manager.create(f'https://example.org/{name}', name)
        folder = manager.root / task['id']; folder.mkdir()
        media = folder / f'{name}.mp4'; media.write_bytes(b'0123456789')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path=?,author=?,updated_at=? WHERE id=?",
                       (media.relative_to(manager.root).as_posix(), author, stamp, task['id']))
            manager.assets.register(db, dict(db.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone()))

    def subscribe(self, nickname, **extra):
        config = {'nickname': nickname, 'platform': 'douyin', **extra}
        with self.app.state.store.connect() as db:
            db.execute("INSERT INTO subscriptions VALUES (?,?,?,?,?)",
                       (f'sub-{nickname}', f'douyin:{nickname}', json.dumps(config), 'now', 'now'))

    def items(self, **params):
        response = self.client.get('/api/bloggers', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['items']

    def test_list_groups_counts_and_sorts(self):
        self.add('a1', 'alice', '2026-01-01T00:00:00+00:00')
        self.add('a2', 'alice', '2026-01-05T00:00:00+00:00')
        self.add('b1', 'bob', '2026-02-01T00:00:00+00:00')
        self.add('c1', 'Carol', '2026-01-03T00:00:00+00:00')
        self.add('n1', '', '2026-03-01T00:00:00+00:00')
        names = lambda **p: [i['author'] for i in self.items(**p)]
        self.assertEqual(names(), ['bob', 'alice', 'Carol'])
        self.assertEqual(names(sort='count'), ['alice', 'Carol', 'bob'])
        self.assertEqual(names(sort='name'), ['alice', 'bob', 'Carol'])
        self.assertEqual({i['author']: i['count'] for i in self.items()}, {'alice': 2, 'bob': 1, 'Carol': 1})
        self.assertEqual(names(q='  CAR '), ['Carol'])
        self.assertEqual(self.client.get('/api/bloggers', params={'sort': 'x'}).status_code, 422)

    def test_profile_comes_from_the_matching_subscription(self):
        self.add('a1', 'alice', '2026-01-01T00:00:00+00:00')
        self.add('b1', 'bob', '2026-01-02T00:00:00+00:00')
        self.subscribe('alice', signature='hello', follower_count=1234, avatar_url='https://img.example.org/a.jpg')
        alice = next(i for i in self.items() if i['author'] == 'alice')
        bob = next(i for i in self.items() if i['author'] == 'bob')
        self.assertEqual((alice['signature'], alice['followers'], alice['platform']), ('hello', 1234, 'douyin'))
        self.assertEqual((bob['signature'], bob['followers'], bob['avatar']), ('', None, None))

    def test_avatar_is_fetched_in_the_background_then_served_from_cache(self):
        self.add('a1', 'alice', '2026-01-01T00:00:00+00:00')
        url = 'https://img.example.org/a.jpg'
        self.subscribe('alice', avatar_url=url)
        requested = []
        covers = self.app.state.covers
        covers.fetch_later = lambda work, cover, net=None: requested.append((work, cover))
        self.assertIsNone(self.items()[0]['avatar'])
        self.assertEqual(requested, [(url, url)])
        folder = covers.folder(key_for(url)); folder.mkdir(parents=True)
        (folder / f'{key_for(url)}.jpg').write_bytes(JPEG)
        requested.clear()
        self.assertEqual(self.items()[0]['avatar'], f'/api/covers/{key_for(url)}')
        self.assertEqual(requested, [])

    def test_detail_and_missing(self):
        self.add('a1', 'alice', '2026-01-01T00:00:00+00:00')
        self.subscribe('alice', signature='hi')
        found = self.client.get('/api/blogger', params={'author': 'alice'})
        self.assertEqual((found.status_code, found.json()['count'], found.json()['signature']), (200, 1, 'hi'))
        self.assertEqual(self.client.get('/api/blogger', params={'author': 'nobody'}).status_code, 404)
        self.assertEqual(self.client.get('/api/blogger').status_code, 422)

    def test_requires_login(self):
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.get('/api/bloggers').status_code, 401)
            self.assertEqual(anonymous.get('/api/blogger', params={'author': 'x'}).status_code, 401)


class AppProfileTests(unittest.TestCase):
    """The profile tab authenticates with a bearer token, not a cookie."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        with TestClient(self.app) as setup:
            setup.post('/api/setup', json=CREDS)
        self.phone = TestClient(self.app)
        token = self.phone.post('/api/auth/app-login', json=CREDS).json()['token']
        self.phone.cookies.clear()
        self.phone.headers['Authorization'] = f'Bearer {token}'

    def tearDown(self):
        self.phone.close(); self.temp.cleanup()

    def test_avatar_and_background_lifecycle_with_a_token(self):
        self.assertEqual(self.phone.get('/api/auth/background').status_code, 404)
        self.assertEqual(self.phone.get('/api/app/me').json()['background'], None)
        version = self.phone.put('/api/auth/background', content=JPEG).json()['background']
        self.assertTrue(version)
        got = self.phone.get('/api/auth/background')
        self.assertEqual((got.status_code, got.headers['content-type'], got.content), (200, 'image/jpeg', JPEG))
        self.assertEqual(self.phone.put('/api/auth/avatar', content=PNG).status_code, 200)
        me = self.phone.get('/api/app/me').json()
        self.assertEqual((me['username'], me['background'], bool(me['avatar'])), ('admin', version, True))
        self.assertEqual(self.phone.delete('/api/auth/background').json(), {'background': None})
        self.assertEqual(self.phone.get('/api/auth/background').status_code, 404)
        self.assertTrue(self.phone.get('/api/auth/avatar').status_code == 200)

    def test_background_validation(self):
        self.assertEqual(self.phone.put('/api/auth/background', content=b'<svg/>').status_code, 415)
        self.assertEqual(self.phone.put('/api/auth/background', content=JPEG + b'0' * (6 * 1024 * 1024)).status_code, 413)
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.put('/api/auth/background', content=JPEG).status_code, 401)
            self.assertEqual(anonymous.get('/api/app/me').status_code, 401)

    def test_me_counts_only_playable_videos(self):
        manager = self.app.state.manager
        task = manager.create('https://example.org/x', 'x')
        folder = manager.root / task['id']; folder.mkdir()
        media = folder / 'x.mp4'; media.write_bytes(b'0123456789')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path=?,author='a' WHERE id=?",
                       (media.relative_to(manager.root).as_posix(), task['id']))
            manager.assets.register(db, dict(db.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone()))
        asset = self.phone.get('/api/feed').json()['items'][0]['id']
        self.phone.put(f'/api/favorites/{asset}'); self.phone.post('/api/history', json={'asset_id': asset, 'position': 4})
        self.assertEqual({k: v for k, v in self.phone.get('/api/app/me').json().items() if k in ('favorites', 'history', 'videos')},
                         {'favorites': 1, 'history': 1, 'videos': 1})
        media.unlink()
        self.assertEqual({k: v for k, v in self.phone.get('/api/app/me').json().items() if k in ('favorites', 'history', 'videos')},
                         {'favorites': 0, 'history': 0, 'videos': 0})


if __name__ == '__main__':
    unittest.main()
