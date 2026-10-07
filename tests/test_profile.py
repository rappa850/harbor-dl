import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app import create_app


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.a = TestClient(self.app)
        self.b = TestClient(self.app)
        self.a.post('/api/setup', json={'username': 'admin', 'password': 'test-password-123'})
        self.b.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password-123'})

    def tearDown(self):
        self.a.close(); self.b.close(); self.temp.cleanup()

    def test_profile_summary(self):
        data = self.a.get('/api/auth/profile').json()
        self.assertEqual((data['username'], data['active_sessions'], data['api_tokens']), ('admin', 2, 0))

    def test_profile_requires_login(self):
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.get('/api/auth/profile').status_code, 401)

    def test_rename(self):
        self.assertEqual(self.a.patch('/api/auth/profile', json={'username': '  captain  '}).json(), {'username': 'captain'})
        self.assertEqual(self.b.get('/api/auth/me').json()['username'], 'captain')
        self.assertEqual(self.a.patch('/api/auth/profile', json={'username': 'ab'}).status_code, 422)

    def test_password_change_keeps_current_session_only(self):
        wrong = self.a.post('/api/auth/password', json={'current_password': 'nope', 'new_password': 'another-password-1'})
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(self.a.post('/api/auth/password', json={'current_password': 'test-password-123',
                                                               'new_password': 'another-password-1'}).status_code, 200)
        self.assertEqual(self.a.get('/api/auth/me').status_code, 200)
        self.assertEqual(self.b.get('/api/auth/me').status_code, 401)
        with TestClient(self.app) as fresh:
            self.assertEqual(fresh.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password-123'}).status_code, 401)
            self.assertEqual(fresh.post('/api/auth/login', json={'username': 'admin', 'password': 'another-password-1'}).status_code, 200)

    def test_revoke_other_sessions(self):
        self.assertEqual(self.a.post('/api/auth/sessions/revoke-others').json(), {'revoked': 1})
        self.assertEqual(self.a.get('/api/auth/me').status_code, 200)
        self.assertEqual(self.b.get('/api/auth/me').status_code, 401)

    PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32

    def test_avatar_lifecycle(self):
        self.assertEqual(self.a.get('/api/auth/avatar').status_code, 404)
        self.assertIsNone(self.a.get('/api/auth/me').json()['avatar'])
        version = self.a.put('/api/auth/avatar', content=self.PNG, headers={'Content-Type': 'image/png'}).json()['avatar']
        self.assertTrue(version)
        self.assertEqual(self.a.get('/api/auth/me').json()['avatar'], version)
        fetched = self.a.get('/api/auth/avatar')
        self.assertEqual((fetched.status_code, fetched.headers['content-type'], fetched.content), (200, 'image/png', self.PNG))
        self.assertEqual(self.a.get('/api/auth/profile').json()['avatar'], version)
        self.assertEqual(self.a.delete('/api/auth/avatar').json(), {'avatar': None})
        self.assertEqual(self.a.get('/api/auth/avatar').status_code, 404)

    def test_avatar_rejects_non_images_and_oversize(self):
        self.assertEqual(self.a.put('/api/auth/avatar', content=b'<svg onload=alert(1)>').status_code, 415)
        self.assertEqual(self.a.put('/api/auth/avatar', content=self.PNG + b'0' * (2 * 1024 * 1024)).status_code, 413)

    def test_avatar_requires_login(self):
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.get('/api/auth/avatar').status_code, 401)
            self.assertEqual(anonymous.put('/api/auth/avatar', content=self.PNG).status_code, 401)

    def test_remember_login_controls_cookie_and_session_lifetime(self):
        import time
        creds = {'username': 'admin', 'password': 'test-password-123'}
        keep, temp = TestClient(self.app), TestClient(self.app)
        self.addCleanup(keep.close); self.addCleanup(temp.close)
        if True:
            kept = keep.post('/api/auth/login', json=creds)
            dropped = temp.post('/api/auth/login', json={**creds, 'remember': False})
            self.assertIn('Max-Age=2592000', kept.headers['set-cookie'])
            self.assertNotIn('Max-Age', dropped.headers['set-cookie'])
            self.assertNotIn('expires', dropped.headers['set-cookie'].lower())
            lifetimes = sorted(round((row['expires'] - time.time()) / 86400) for row in
                               self.app.state.store.all('SELECT expires FROM sessions'))
            self.assertEqual((lifetimes.count(1), lifetimes.count(30)), (1, len(lifetimes) - 1))
            self.assertEqual(temp.get('/api/auth/me').status_code, 200)


if __name__ == '__main__':
    unittest.main()
