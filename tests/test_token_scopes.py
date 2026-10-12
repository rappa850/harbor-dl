import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.token_scopes import allows, required

SUB='00000000-0000-4000-8000-000000000001'


class RuleTests(unittest.TestCase):
    def test_required_levels(self):
        cases=[('GET','/api/feed','read'),('GET','/api/subscriptions','read'),('PUT','/api/favorites/abc','read'),
               ('DELETE','/api/favorites/abc','read'),('POST','/api/history','read'),('PUT',f'/api/playback/record/{SUB}','read'),
               ('POST','/api/tasks','download'),('POST','/api/tasks/x/retry','download'),('POST','/api/tasks/x/cancel','download'),
               ('POST','/api/media/parse','download'),('POST',f'/api/subscriptions/{SUB}/check','download'),
               ('POST',f'/api/subscriptions/{SUB}/sync','download'),('POST',f'/api/subscriptions/{SUB}/videos/download','download'),
               ('POST',f'/api/subscriptions/{SUB}/videos/{SUB}/download','download'),
               ('DELETE','/api/tasks/x','manage'),('POST','/api/subscriptions','manage'),('PATCH',f'/api/subscriptions/{SUB}','manage'),
               ('DELETE',f'/api/subscriptions/{SUB}','manage'),('PUT','/api/settings','manage'),('PUT','/api/network/cookies/douyin','manage'),
               ('POST','/api/library/export','manage'),('POST',f'/api/subscriptions/{SUB}/videos/orphan/cleanup','manage'),
               ('GET','/api/network','manage'),('GET','/api/backup/subscriptions','manage'),('GET','/api/logs','manage'),
               ('POST','/api/live/subscriptions/x/record/start','manage'),('POST','/api/browser/douyin/login','manage')]
        for method,path,expected in cases:
            self.assertEqual(required(method,path),expected,(method,path))

    def test_levels_are_ordered_and_unknown_scope_gets_nothing(self):
        self.assertTrue(allows('manage','DELETE','/api/tasks/x'))
        self.assertTrue(allows('download','GET','/api/feed'));self.assertFalse(allows('download','DELETE','/api/tasks/x'))
        self.assertFalse(allows('read','POST','/api/tasks'));self.assertFalse(allows('bogus','GET','/api/feed'))


class ScopeApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.app=create_app(self.temp.name)
        self.owner=TestClient(self.app);self.external=TestClient(self.app)
        self.owner.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def tearDown(self):
        self.owner.close();self.external.close();self.temp.cleanup()

    def token(self,scope=None):
        body={'name':'t'};
        if scope:body['scope']=scope
        return self.owner.post('/api/auth/tokens',json=body).json()

    def headers(self,record):return {'X-API-Token':record['token']}

    def test_default_and_listed_scope_and_invalid_scope(self):
        self.assertEqual(self.token()['scope'],'manage')
        self.assertEqual(self.token('read')['scope'],'read')
        self.assertEqual(self.owner.get('/api/auth/tokens').json()['items'][0]['scope'],'read')
        self.assertEqual(self.owner.post('/api/auth/tokens',json={'name':'x','scope':'root'}).status_code,422)

    def test_read_token_can_browse_but_not_change(self):
        headers=self.headers(self.token('read'))
        self.assertEqual(self.external.get('/api/tasks',headers=headers).status_code,200)
        self.assertEqual(self.external.get('/api/auth/me',headers=headers).json()['scope'],'read')
        denied=self.external.post('/api/tasks',json={'url':'https://example.org/v'},headers=headers)
        self.assertEqual(denied.status_code,403);self.assertIn('download',denied.json()['detail'])
        self.assertEqual(self.external.delete('/api/tasks/x',headers=headers).status_code,403)
        self.assertEqual(self.external.get('/api/network',headers=headers).status_code,403)
        self.assertEqual(self.external.put('/api/settings',json={'concurrency':3},headers=headers).status_code,403)
        self.assertNotEqual(self.external.post('/api/history',json={'asset_id':'a','position':1},headers=headers).status_code,403)

    def test_download_token_queues_but_cannot_delete_or_edit(self):
        headers=self.headers(self.token('download'))
        self.assertNotEqual(self.external.post(f'/api/subscriptions/{SUB}/check',headers=headers).status_code,403)
        self.assertEqual(self.external.delete(f'/api/subscriptions/{SUB}',headers=headers).status_code,403)
        self.assertEqual(self.external.patch(f'/api/subscriptions/{SUB}',json={'auto_download':False},headers=headers).status_code,403)

    def test_manage_token_and_scope_change_apply_immediately(self):
        record=self.token('read');headers=self.headers(record)
        self.assertEqual(self.external.get('/api/network',headers=headers).status_code,403)
        self.assertEqual(self.owner.patch('/api/auth/tokens/'+record['id'],json={'scope':'manage'}).json()['scope'],'manage')
        self.assertEqual(self.external.get('/api/network',headers=headers).status_code,200)
        self.assertEqual(self.owner.patch('/api/auth/tokens/'+record['id'],json={'scope':None}).status_code,422)

    def test_owner_session_is_never_restricted_and_old_tokens_become_manage(self):
        self.assertEqual(self.owner.get('/api/network').status_code,200)
        self.assertEqual(self.owner.get('/api/auth/me').json()['scope'],'manage')
        with self.app.state.store.connect() as db:      # a row written before scopes existed has the column default
            db.execute("INSERT INTO api_tokens(id,user_id,name,token_hash,token_suffix,created_at,is_active) VALUES ('old',1,'old','h','xxxxxxxx',1,1)")
        self.assertEqual(self.app.state.store.one("SELECT scope FROM api_tokens WHERE id='old'")['scope'],'manage')

    def test_app_login_defaults_to_download_and_can_ask_for_more(self):
        creds={'username':'admin','password':'test-password-123'}
        first=self.external.post('/api/auth/app-login',json=creds).json()
        self.assertEqual(first['scope'],'download')
        second=self.external.post('/api/auth/app-login',json={**creds,'scope':'manage'}).json()
        self.assertEqual(second['scope'],'manage')
        self.assertEqual(self.external.get('/api/network',headers={'X-API-Token':first['token']}).status_code,403)
        self.assertEqual(self.external.get('/api/network',headers={'X-API-Token':second['token']}).status_code,200)
