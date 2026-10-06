import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from backend.app import create_app


class ApiTokenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(self.temp.name)
        self.owner=TestClient(self.app);self.external=TestClient(self.app)
        self.owner.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def tearDown(self):
        self.owner.close();self.external.close();self.temp.cleanup()

    def create(self):
        response=self.owner.post('/api/auth/tokens',json={'name':'automation','expires_in_days':3})
        self.assertEqual(response.status_code,201)
        return response.json()

    def test_one_time_visibility_hash_storage_and_both_headers(self):
        record=self.create();value=record['token']
        self.assertNotIn(value,self.owner.get('/api/auth/tokens').text)
        stored=self.app.state.store.one('SELECT * FROM api_tokens WHERE id=?',(record['id'],))
        self.assertNotIn(value,str(stored))
        self.assertEqual(stored['token_suffix'],value[-8:])
        self.assertEqual(self.external.get('/api/tasks',headers={'X-API-Token':value}).status_code,200)
        self.assertEqual(self.external.get('/api/dashboard',headers={'Authorization':'Bearer '+value}).status_code,200)
        listing=self.owner.get('/api/auth/tokens').json()['items'][0]
        self.assertIsNotNone(listing['last_used_at'])
        self.assertEqual(self.external.get('/api/auth/tokens',headers={'X-API-Token':value}).status_code,401)

    def test_disable_expire_rotate_delete_immediate_effect(self):
        record=self.create();token_id=record['id'];value=record['token']
        url='/api/auth/tokens/'+token_id
        self.owner.patch(url,json={'is_active':False})
        self.assertEqual(self.external.get('/api/tasks',headers={'X-API-Token':value}).status_code,401)
        self.owner.patch(url,json={'is_active':True,'expires_at':'2000-01-01T00:00:00+00:00'})
        self.assertEqual(self.external.get('/api/tasks',headers={'X-API-Token':value}).status_code,401)
        self.owner.patch(url,json={'expires_at':None,'name':'renamed'})
        rotated=self.owner.post(url+'/regenerate').json()['token']
        self.assertNotEqual(rotated,value)
        self.assertEqual(self.external.get('/api/tasks',headers={'X-API-Token':value}).status_code,401)
        self.assertEqual(self.external.get('/api/tasks',headers={'X-API-Token':rotated}).status_code,200)
        self.owner.delete(url)
        self.assertEqual(self.external.get('/api/tasks',headers={'X-API-Token':rotated}).status_code,401)

    def test_invalid_header_does_not_fall_back_and_validation(self):
        record=self.create()
        self.assertEqual(self.owner.get('/api/tasks',headers={'X-API-Token':'invalid'}).status_code,401)
        self.assertEqual(self.external.get('/api/tasks',headers={'X-API-Token':'invalid','Authorization':'Bearer '+record['token']}).status_code,401)
        self.assertEqual(self.owner.post('/api/auth/tokens',json={'name':'   '}).status_code,422)
        self.assertEqual(self.owner.post('/api/auth/tokens',json={'name':'test','expires_in_days':0}).status_code,422)
        self.assertEqual(self.owner.patch('/api/auth/tokens/'+record['id'],json={'is_active':None}).status_code,422)
        self.assertEqual(self.owner.patch('/api/auth/tokens/'+record['id'],json={'expires_at':'2026-12-31T00:00:00'}).status_code,422)

    def test_token_ownership(self):
        record=self.create()
        with self.app.state.store.connect() as db:
            db.execute("INSERT INTO users(username,password,created_at) VALUES ('other','unused','now')")
            other=db.execute("SELECT id FROM users WHERE username='other'").fetchone()[0]
        from backend.api_tokens import ApiTokens
        tokens=ApiTokens(self.app.state.store)
        self.assertEqual(tokens.list(other),[])
        self.assertIsNone(tokens.rotate(record['id'],other))
        self.assertFalse(tokens.delete(record['id'],other))
