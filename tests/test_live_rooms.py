import tempfile
import unittest
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.live_rooms import BilibiliRooms


class LiveRoomTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.requests=[];self.options=[];self.status=1;self.invalid=False
        def respond(request):
            self.requests.append(request)
            if self.invalid:return httpx.Response(200,json={'code':-400,'message':'fixture failure'})
            data={'room_id':900,'uid':123,'live_status':self.status} if request.url.path.endswith('room_init') else {'info':{'uname':'主播','face':'https://example.org/avatar'}}
            return httpx.Response(200,json={'code':0,'data':data})
        def client(**kwargs):
            self.options.append(dict(kwargs))
            kwargs.pop('proxy',None)
            return httpx.AsyncClient(**kwargs,transport=httpx.MockTransport(respond))
        self.app=create_app(self.temp.name,live_detector=BilibiliRooms(client))
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def tearDown(self):self.client.close();self.temp.cleanup()

    def add(self,**fields):
        payload={'platform':'bilibili','room_url':'https://live.bilibili.com/12',**fields}
        response=self.client.post('/api/backup/live_subscriptions/import',json={'subscriptions':[payload]})
        self.assertEqual(response.json()['success'],1)
        return self.client.get('/api/live/subscriptions').json()['items'][0]['id']

    def test_canonical_identity_live_offline_and_loop_are_explicit(self):
        scope=self.add(monitor_enabled=False,auto_record=False)
        for status,is_live in [(1,True),(0,False),(2,False)]:
            self.status=status
            response=self.client.post(f'/api/live/subscriptions/{scope}/check')
            self.assertEqual(response.status_code,200,response.text)
            result=response.json();self.assertEqual(result['room_id'],'900')
            self.assertEqual(result['is_live'],is_live);self.assertEqual(result['anchor_name'],'主播')
            self.assertEqual(result['room_url'],'https://live.bilibili.com/900')
        self.assertEqual(self.requests[0].url.params['id'],'12')
        self.assertEqual(self.requests[1].url.params['uid'],'123')
        config=self.client.get('/api/backup/live_subscriptions').json()['subscriptions'][0]
        self.assertEqual(config['room_url'],'https://live.bilibili.com/12')
        self.assertFalse(config['auto_record'])
        self.assertEqual(self.app.state.store.all('SELECT * FROM tasks'),[])
        snapshot=self.client.get('/api/live/subscriptions').json()['items'][0]['last_detection']
        self.assertEqual(snapshot['live_status'],2)
        self.assertNotIn('last_detection',config)

    def test_error_keeps_previous_state_and_does_not_claim_offline(self):
        scope=self.add();path=f'/api/live/subscriptions/{scope}/check'
        self.assertEqual(self.client.post(path).status_code,200)
        state=self.app.state.store.all('SELECT * FROM live_room_states')
        self.invalid=True
        self.assertEqual(self.client.post(path).status_code,502)
        self.assertEqual(self.app.state.store.all('SELECT * FROM live_room_states'),state)

    def test_room_credentials_override_global_and_are_not_in_response(self):
        self.assertEqual(self.client.put('/api/network/proxy',json={'enabled':True,'proxy':'http://global:secret@localhost:8001','no_proxy':''}).status_code,200)
        scope=self.add(cookies='SESSDATA=local-secret',proxy='http://room:password@localhost:8002')
        response=self.client.post(f'/api/live/subscriptions/{scope}/check')
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.requests[0].headers['cookie'],'SESSDATA=local-secret')
        self.assertEqual(self.options[0]['proxy'],'http://room:password@localhost:8002')
        self.assertNotIn('local-secret',response.text);self.assertNotIn('password',response.text)

    def test_unknown_scope_unsupported_host_and_unauthenticated_requests(self):
        self.assertEqual(self.client.post(f'/api/live/subscriptions/{uuid4()}/check').status_code,404)
        scope=self.add(room_url='https://live.bilibili.com.attacker.test/12')
        self.assertEqual(self.client.post(f'/api/live/subscriptions/{scope}/check').status_code,422)
        self.assertEqual(self.requests,[])
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post(f'/api/live/subscriptions/{scope}/check').status_code,401)
