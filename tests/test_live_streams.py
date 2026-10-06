import tempfile
import unittest
import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.live_rooms import BilibiliRooms


class LiveStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.requests=[];self.status=1;self.v2=False;self.reject_cookie=False;self.invalid_url=False
        def respond(request):
            self.requests.append(request)
            path=request.url.path
            if path.endswith('room_init'):data={'room_id':900,'uid':123,'live_status':self.status}
            elif path.endswith('/info'):data={'info':{'uname':'fixture'}}
            elif path.endswith('playUrl'):
                if self.reject_cookie and request.headers.get('cookie'):return httpx.Response(403)
                if self.v2:return httpx.Response(200,json={'code':-1})
                data={'quality':250,'durl':[{'url':'https://cdn.example/first.flv'},
                    {'url':'file:///outside' if self.invalid_url else 'https://d1--cn-gotcha.example/selected.flv?token=signed'}]}
            else:
                data={'live_status':1,'playurl_info':{'playurl':{'stream':[{'format':[{'codec':[
                    {'current_qn':10000,'base_url':'/highest.m3u8','url_info':[{'host':'https://cdn.example','extra':'?a=1'}]},
                    {'current_qn':250,'base_url':'/lower.m3u8','url_info':[{'host':'https://cdn.example','extra':'?a=2'}]}]}]}]}}}
            return httpx.Response(200,json={'code':0,'data':data})
        def factory(**kwargs):
            kwargs.pop('proxy',None)
            return httpx.AsyncClient(**kwargs,transport=httpx.MockTransport(respond))
        self.app=create_app(self.temp.name,live_detector=BilibiliRooms(factory));self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def tearDown(self):self.client.close();self.temp.cleanup()

    def add(self,quality='原画',cookies=None):
        self.client.post('/api/backup/live_subscriptions/import',json={'subscriptions':[
            {'platform':'bilibili','room_url':'https://live.bilibili.com/12','quality':quality,'cookies':cookies}]})
        scope=self.client.get('/api/live/subscriptions').json()['items'][0]['id']
        return '/api/live/subscriptions/'+scope+'/stream'

    def test_quality_mapping_selected_cdn_and_no_persistence(self):
        response=self.client.post(self.add('4K'))
        self.assertEqual(response.status_code,200,response.text)
        result=response.json()
        self.assertEqual(result['requested_qn'],20000);self.assertEqual(result['actual_qn'],250)
        self.assertEqual(self.requests[-1].url.params['qn'],'20000')
        self.assertEqual(self.requests[-1].url.params['cid'],'900')
        self.assertIn('d1--cn-gotcha',result['url']);self.assertEqual(result['format'],'flv')
        self.assertEqual(result['headers']['Referer'],'https://live.bilibili.com/')
        self.assertEqual(self.app.state.store.all('SELECT * FROM tasks'),[])
        self.assertNotIn('signed',self.client.get('/api/backup/live_subscriptions').text)

    def test_offline_and_loop_do_not_request_stream(self):
        path=self.add()
        for status in (0,2):
            self.status=status;self.requests=[]
            response=self.client.post(path)
            self.assertEqual(response.status_code,200);self.assertFalse(response.json()['is_live'])
            self.assertIsNone(response.json()['url']);self.assertEqual(len(self.requests),2)

    def test_v2_fallback_reports_actual_quality_and_combines_host_path_query(self):
        self.v2=True
        response=self.client.post(self.add('蓝光'))
        self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertEqual(result['requested_qn'],400);self.assertEqual(result['actual_qn'],250)
        self.assertEqual(result['url'],'https://cdn.example/lower.m3u8?a=2')
        self.assertEqual(result['format'],'m3u8')

    def test_failed_cookie_stream_retries_as_guest_without_exposing_cookie(self):
        self.reject_cookie=True
        response=self.client.post(self.add(cookies='SESSDATA=fixture-secret'))
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['guest_fallback'])
        stream_requests=[request for request in self.requests if request.url.path.endswith('playUrl')]
        self.assertEqual(len(stream_requests),2)
        self.assertIn('fixture-secret',stream_requests[0].headers['cookie'])
        self.assertNotIn('cookie',stream_requests[1].headers)
        self.assertNotIn('fixture-secret',response.text)

    def test_invalid_stream_scheme_and_authentication(self):
        self.invalid_url=True
        path=self.add()
        self.assertEqual(self.client.post(path).status_code,502)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post(path).status_code,401)
