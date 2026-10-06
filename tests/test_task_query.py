import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app import create_app


class TaskQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(self.temp.name)
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def test_paging_beyond_old_500_and_stable_ties(self):
        with self.app.state.store.connect() as db:
            db.executemany('INSERT INTO tasks(id,url,title,status,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                [(f't-{i:04}','https://example.org',f'title-{i}','PENDING','same','same') for i in range(530)])
        result=self.client.get('/api/tasks?limit=24&offset=504').json()
        self.assertEqual(result['total'],530)
        self.assertEqual(len(result['items']),24)
        self.assertEqual(result['items'][0]['id'],'t-0025')
        self.assertEqual(self.client.get('/api/tasks?limit=24&offset=528').json()['items'][-1]['id'],'t-0000')
        self.assertEqual(self.client.get('/api/tasks?offset=-1').status_code,422)
        self.assertEqual(self.client.get('/api/tasks?status=nonsense').status_code,422)

    def test_combined_filters_literal_search_and_orphan_semantics(self):
        manager=self.app.state.manager
        first=manager.create('https://youtube.com/one','Älbum 100%',source='youtube',author='Author')
        second=manager.create('https://example.org/two','other',author='Another Author')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path='missing.mp4',subscription_id='sub' WHERE id=?",(first['id'],))
            db.execute("UPDATE tasks SET status='PROCESSING' WHERE id=?",(second['id'],))
        self.assertEqual(self.client.get('/api/tasks?query=%C3%A4LBUM').json()['total'],1)
        self.assertEqual(self.client.get('/api/tasks?query=%25').json()['total'],1)
        self.assertEqual(self.client.get('/api/tasks?query=author').json()['total'],2)
        self.assertEqual(self.client.get('/api/tasks?status=active').json()['items'][0]['id'],second['id'])
        self.assertEqual(self.client.get('/api/tasks?orphan_only=true').json()['total'],1)
        self.assertEqual(self.client.get('/api/tasks?manual_only=true&orphan_only=true').json()['total'],0)
        self.assertEqual(self.client.get('/api/tasks?platform=youtube&subscription_id=sub&status=completed').json()['total'],1)
        (manager.root/'missing.mp4').write_bytes(b'media')
        self.assertEqual(self.client.get('/api/tasks?orphan_only=true').json()['total'],0)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/tasks').status_code,401)
