import asyncio
import tempfile
import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.live_config import LiveSubscriptions


class LiveConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create_app(self.temp.name)
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
        self.url='/api/backup/live_subscriptions/import'

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def test_defaults_duplicate_partial_failure_and_string_false(self):
        payload={'subscriptions':[
            {'platform':'douyin','room_url':' https://live.douyin.com/100 '},
            {'platform':'douyin','room_url':'https://live.douyin.com/100'},
            {'platform':'','room_url':'missing'},
            {'platform':'bilibili','room_url':'https://live.bilibili.com/200','auto_record':'false',
             'monitor_enabled':False,'split_enabled':'false','notification_enabled':'false'}]}
        result=self.client.post(self.url,json=payload).json()
        self.assertEqual((result['total'],result['success'],result['failed']),(4,2,2))
        self.assertEqual(len(result['monitor_warnings']),2)
        items=self.client.get('/api/live/subscriptions').json()['items']
        defaults=next(item for item in items if item['platform']=='douyin')
        self.assertEqual((defaults['quality'],defaults['check_interval'],defaults['output_format']),('原画',60,'ts'))
        self.assertEqual(defaults['split_duration'],3600)
        self.assertTrue(defaults['auto_record']);self.assertFalse(defaults['split_enabled'])
        self.assertFalse(defaults['notification_end_enabled'])
        disabled=next(item for item in items if item['platform']=='bilibili')
        self.assertFalse(disabled['auto_record']);self.assertFalse(disabled['monitor_enabled'])
        self.assertFalse(disabled['notification_enabled'])

    def test_backup_roundtrip_keeps_credentials_extra_data_and_false_across_restart(self):
        config={'platform':'twitch','room_url':'https://twitch.tv/channel','cookies':'fixture-cookie',
                'proxy':'http://user:pass@localhost:9999','auto_record':False,'monitor_enabled':True,
                'extra_data':'{"danmu_enabled":false,"unknown_setting":42}',
                'record_windows':[{'weekdays':[1],'start':'23:00','end':'01:00'}]}
        self.assertEqual(self.client.post(self.url,json={'subscriptions':[config]}).json()['success'],1)
        public=self.client.get('/api/live/subscriptions').json()['items'][0]
        self.assertNotIn('cookies',public);self.assertNotIn('proxy',public)
        self.assertTrue(public['has_cookies']);self.assertTrue(public['has_proxy'])
        backup=self.client.get('/api/backup/live_subscriptions').json()
        for key,value in config.items():self.assertEqual(backup['subscriptions'][0][key],value)
        self.client.close();self.app=create_app(self.temp.name);self.client=TestClient(self.app)
        self.client.post('/api/auth/login',json={'username':'admin','password':'test-password-123'})
        self.assertEqual(self.client.get('/api/backup/live_subscriptions').json()['subscriptions'],backup['subscriptions'])
        with tempfile.TemporaryDirectory() as other:
            copied=create_app(other);destination=TestClient(copied)
            destination.post('/api/setup',json={'username':'admin','password':'test-password-123'})
            self.assertEqual(destination.post(self.url,json=backup).json()['success'],1)
            self.assertFalse(destination.get('/api/live/subscriptions').json()['items'][0]['auto_record'])
            destination.close()

    def test_registration_failure_occurs_after_commit_and_does_not_rollback(self):
        called=[]
        async def register(scope,url,platform,interval):
            self.assertIsNotNone(self.app.state.store.one('SELECT * FROM live_subscriptions WHERE id=?',(scope,)))
            called.append((url,platform,interval));raise RuntimeError('fixture monitor failure')
        service=LiveSubscriptions(self.app.state.store,register)
        result=asyncio.run(service.import_config([{'platform':'douyin','room_url':'https://live.douyin.com/100'}]))
        self.assertEqual(result['success'],1);self.assertEqual(result['failed'],0)
        self.assertEqual(len(result['monitor_warnings']),1)
        self.assertEqual(called,[('https://live.douyin.com/100','douyin',60)])
        self.assertEqual(len(service.list()),1)

    def test_edit_independent_switches_unknown_scope_validation_and_auth(self):
        self.client.post(self.url,json={'subscriptions':[{'platform':'douyin','room_url':'https://live.douyin.com/100'}]})
        scope=self.client.get('/api/live/subscriptions').json()['items'][0]['id']
        path='/api/live/subscriptions/'+scope
        response=self.client.patch(path,json={'auto_record':False,'monitor_enabled':True})
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['auto_record']);self.assertTrue(response.json()['monitor_enabled'])
        self.assertEqual(self.client.patch(path,json={'check_interval':0}).status_code,422)
        self.assertEqual(self.client.patch(path,json={'auto_record':None}).status_code,422)
        self.assertEqual(self.client.patch('/api/live/subscriptions/'+str(uuid4()),json={}).status_code,404)
        self.assertEqual(self.client.post(self.url,json={'subscriptions':[]}).status_code,422)
        self.client.post('/api/auth/logout')
        for method,target in [('get','/api/live/subscriptions'),('get','/api/backup/live_subscriptions')]:
            self.assertEqual(getattr(self.client,method)(target).status_code,401)
        self.assertEqual(self.client.post(self.url,json={'subscriptions':[{'platform':'douyin','room_url':'x'}]}).status_code,401)
