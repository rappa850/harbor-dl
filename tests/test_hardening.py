import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.login_limit import LoginLimit
from backend.probe import PER_PAGE, Probe

CREDS = {'username': 'admin', 'password': 'test-password-123'}
WRONG = {'username': 'admin', 'password': 'wrong-password-123'}


class LoginLimitTests(unittest.TestCase):
    def test_pauses_after_the_allowed_failures_and_recovers_with_time(self):
        now = [0.0]
        limit = LoginLimit(attempts=3, window=100, clock=lambda: now[0])
        for _ in range(3):
            self.assertEqual(limit.wait('1.1.1.1', 'Admin'), 0)
            limit.fail('1.1.1.1', 'Admin')
        self.assertGreater(limit.wait('1.1.1.1', 'admin'), 0)  # name is case-insensitive
        self.assertEqual(limit.wait('2.2.2.2', 'admin'), 0)  # another address is unaffected
        self.assertEqual(limit.wait('1.1.1.1', 'other'), 0)
        now[0] = 101
        self.assertEqual(limit.wait('1.1.1.1', 'admin'), 0)

    def test_success_clears_the_count(self):
        limit = LoginLimit(attempts=2)
        limit.fail('a', 'u'); limit.succeed('a', 'u'); limit.fail('a', 'u')
        self.assertEqual(limit.wait('a', 'u'), 0)


class LoginEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = TestClient(self.app)
        self.client.post('/api/setup', json=CREDS)
        self.client.cookies.clear()

    def tearDown(self):
        self.client.close(); self.temp.cleanup()

    def test_repeated_wrong_passwords_are_throttled_on_both_logins(self):
        for path in ('/api/auth/login', '/api/auth/app-login'):
            with self.subTest(path=path):
                self.app.state.login_limit.failures.clear()
                for _ in range(5):
                    self.assertEqual(self.client.post(path, json=WRONG).status_code, 401)
                blocked = self.client.post(path, json=CREDS)  # even the right password waits
                self.assertEqual(blocked.status_code, 429)
                self.assertGreater(int(blocked.headers['Retry-After']), 0)

    def test_a_good_login_resets_the_count(self):
        for _ in range(4):
            self.client.post('/api/auth/app-login', json=WRONG)
        self.assertEqual(self.client.post('/api/auth/app-login', json=CREDS).status_code, 200)
        for _ in range(4):
            self.assertEqual(self.client.post('/api/auth/app-login', json=WRONG).status_code, 401)


class LibraryHousekeepingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.client = TestClient(self.app)
        self.client.post('/api/setup', json=CREDS)

    def tearDown(self):
        self.client.close(); self.temp.cleanup()

    def add(self, name):
        manager = self.app.state.manager
        task = manager.create(f'https://example.org/{name}', name)
        folder = manager.root / task['id']; folder.mkdir()
        media = folder / f'{name}.mp4'; media.write_bytes(b'0123456789')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path=?,author='a' WHERE id=?",
                       (media.relative_to(manager.root).as_posix(), task['id']))
            manager.assets.register(db, dict(db.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone()))

    def test_probe_fills_missing_durations_once(self):
        self.add('manual')
        calls = []
        self.app.state.probe.reader = lambda path: calls.append(path) or 42.5
        first = self.client.get('/api/feed').json()['items'][0]
        again = self.client.get('/api/feed').json()['items'][0]
        self.assertEqual((first['duration'], again['duration']), (42.5, 42.5))
        self.assertEqual(len(calls), 1)

    def test_unknown_durations_are_not_probed_again(self):
        self.add('broken')
        calls = []
        self.app.state.probe.reader = lambda path: calls.append(path)
        for _ in range(2):
            self.assertIsNone(self.client.get('/api/feed').json()['items'][0]['duration'])
        self.assertEqual(len(calls), 1)

    def test_subscription_duration_wins_and_skips_probing(self):
        store = self.app.state.store
        rows = [{'id': 'a', 'path': 'x', 'duration': 9}]
        calls = []
        probe = Probe(store, self.app.state.manager.assets, reader=lambda path: calls.append(path))
        self.assertEqual(probe.durations(rows), {})
        self.assertEqual(calls, [])

    def test_probing_is_bounded_per_page(self):
        for n in range(PER_PAGE + 3):
            self.add(f'v{n}')
        calls = []
        self.app.state.probe.reader = lambda path: calls.append(path) or 5.0
        self.client.get('/api/feed', params={'limit': 50})
        self.assertEqual(len(calls), PER_PAGE)
        self.client.get('/api/feed', params={'limit': 50})
        self.assertEqual(len(calls), PER_PAGE + 3)

    def test_startup_forgets_favorites_and_history_of_deleted_media(self):
        self.add('kept')
        kept = self.client.get('/api/feed').json()['items'][0]['id']
        self.client.put(f'/api/favorites/{kept}')
        self.client.post('/api/history', json={'asset_id': kept, 'position': 5})
        store = self.app.state.store
        with store.connect() as db:
            for table, columns in (('favorites', "(1,'ghost',1.0)"), ('watch_history', "(1,'ghost',3.0,1.0)"),
                                   ('media_probe', "('ghost',9.0,'now')")):
                db.execute(f'INSERT INTO {table} VALUES {columns}')
        self.client.close()
        self.app = create_app(self.root)
        self.client = TestClient(self.app)
        count = lambda table: self.app.state.store.one(f'SELECT COUNT(*) AS n FROM {table}')['n']
        self.assertEqual((count('favorites'), count('watch_history')), (1, 1))
        self.assertEqual(self.app.state.store.one("SELECT COUNT(*) AS n FROM media_probe WHERE asset_id='ghost'")['n'], 0)


if __name__ == '__main__':
    unittest.main()
