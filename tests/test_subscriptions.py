import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app import create_app


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create_app(self.temp.name);self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def test_import_roundtrip_types_and_false_strings(self):
        items=[{'platform':'youtube','user_id':'UC-example','nickname':'频道','auto_download':'false','nickname_locked':'false'},
               {'platform':'youtube','user_id':'UC-example','youtube_tab_type':'shorts'},
               {'platform':'bilibili_collection','user_id':'123','collection_id':'456'}]
        response=self.client.post('/api/backup/subscriptions/import',json={'subscriptions':items})
        self.assertEqual(response.json()['success'],3)
        records=self.client.get('/api/subscriptions').json()['items']
        channel=next(r for r in records if r['nickname']=='频道')
        self.assertFalse(channel['auto_download']);self.assertFalse(channel['nickname_locked'])
        self.assertEqual(channel['storage_name'],'频道')
        self.assertFalse(channel['runtime']['sync_available'])
        exported=self.client.get('/api/backup/subscriptions').json()
        self.assertEqual(exported['total_subscriptions'],3)
        collection=next(r for r in exported['subscriptions'] if r['platform']=='bilibili_collection')
        self.assertEqual(collection['subscription_type'],'collection')

    def test_duplicate_partial_failures_and_empty_import(self):
        items=[{'platform':'x','user_id':'author'},{'platform':'x','user_id':'author'},{'platform':'invalid','user_id':'bad'}]
        result=self.client.post('/api/backup/subscriptions/import',json={'subscriptions':items}).json()
        self.assertEqual((result['total'],result['success'],result['failed']),(3,1,2))
        self.assertEqual(len(result['errors']),2)
        self.assertEqual(self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[]}).status_code,422)

    def test_nickname_pause_resume_and_storage_name_preserved(self):
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[{'platform':'bilibili','user_id':'123','nickname':'原昵称','storage_name':'自定义目录'}]})
        item=self.client.get('/api/subscriptions').json()['items'][0];url='/api/subscriptions/'+item['id']
        changed=self.client.patch(url,json={'nickname':'新昵称','update_interval':0,'auto_download':'false'}).json()
        self.assertEqual(changed['storage_name'],'自定义目录');self.assertTrue(changed['nickname_locked'])
        self.assertEqual(changed['status'],'paused');self.assertFalse(changed['auto_download'])
        changed=self.client.patch(url,json={'update_interval':60}).json()
        self.assertEqual(changed['update_interval'],3600);self.assertEqual(changed['status'],'active')
        self.assertEqual(self.client.patch(url,json={'update_interval':None}).status_code,422)
        task=self.app.state.manager.create('https://example.org/video')
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET subscription_id=? WHERE id=?',(item['id'],task['id']))
        self.assertEqual(self.client.delete(url).status_code,200)
        self.assertIsNotNone(self.app.state.manager.get(task['id']))
        self.assertEqual(self.client.get(url).status_code,404)

    def test_export_import_persistence_and_auth(self):
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[{'platform':'netease','user_id':'playlist','subscription_type':'playlist','update_interval':0}]})
        exported=self.client.get('/api/backup/subscriptions').json()
        another=create_app(self.temp.name)
        self.assertEqual(len(another.state.store.all('SELECT * FROM subscriptions')),1)
        self.assertEqual(exported['subscriptions'][0]['status'],'paused')
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/subscriptions').status_code,401)
