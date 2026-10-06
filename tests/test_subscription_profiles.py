import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app import create_app


class ProfileInspector:
    def __init__(self):
        self.calls=[]
        self.info={'_type':'playlist','id':'UCexample','channel_id':'UCexample','channel':'示例频道'}

    async def raw_info(self,url,network=None,profile=False):
        self.calls.append((url,network,profile))
        return self.info


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.inspector=ProfileInspector()
        self.app=create_app(self.temp.name,inspector=self.inspector)
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_channel_tabs_and_duplicate_identity(self):
        payload={'platform':'youtube','profile_url':'https://www.youtube.com/@example','nickname':'自定义','auto_download':False}
        response=self.client.post('/api/subscriptions',json=payload)
        self.assertEqual(response.status_code,201,response.text)
        item=response.json()
        self.assertEqual(item['user_id'],'UCexample')
        self.assertTrue(item['nickname_locked'])
        self.assertFalse(item['auto_download'])
        self.assertFalse(item['runtime']['sync_available'])
        self.assertEqual(self.inspector.calls[0][0],'https://www.youtube.com/@example/videos')
        self.assertTrue(self.inspector.calls[0][2])
        self.assertEqual(self.client.post('/api/subscriptions',json=payload).status_code,409)
        payload['youtube_tab_type']='shorts'
        self.assertEqual(self.client.post('/api/subscriptions',json=payload).status_code,201)

    def test_playlist_and_bilibili_author(self):
        self.inspector.info={'_type':'playlist','id':'PL12345678','title':'歌单'}
        response=self.client.post('/api/subscriptions',json={'platform':'youtube_playlist','profile_url':'PL12345678'})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['subscription_type'],'playlist')
        self.assertEqual(response.json()['nickname'],'歌单')
        self.inspector.info={'_type':'playlist','id':'123','uploader':'作者'}
        response=self.client.post('/api/subscriptions',json={'platform':'bilibili','profile_url':'https://space.bilibili.com/123'})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['user_id'],'123')
        self.assertEqual(self.inspector.calls[-1][0],'https://space.bilibili.com/123/video')

    def test_invalid_links_results_and_auth_do_not_save(self):
        for url in ['https://www.youtube.com/watch?v=example','https://youtube.com.evil.example/@author']:
            response=self.client.post('/api/subscriptions',json={'platform':'youtube','profile_url':url})
            self.assertEqual(response.status_code,422)
        self.assertEqual(len(self.inspector.calls),0)
        for url in ['https://space.bilibili.com/123?fid=456','https://space.bilibili.com/123/favlist?fid=456']:
            self.assertEqual(self.client.post('/api/subscriptions',json={'platform':'bilibili','profile_url':url}).status_code,422)
        self.assertEqual(len(self.inspector.calls),0)
        self.inspector.info={'_type':'playlist','id':'alias'}
        self.assertEqual(self.client.post('/api/subscriptions',json={'platform':'youtube','profile_url':'https://www.youtube.com/@example'}).status_code,422)
        self.inspector.info={'_type':'playlist','id':'456'}
        self.assertEqual(self.client.post('/api/subscriptions',json={'platform':'bilibili','profile_url':'https://space.bilibili.com/123'}).status_code,422)
        self.assertEqual(self.client.get('/api/subscriptions').json()['items'],[])
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post('/api/subscriptions',json={'platform':'youtube','profile_url':'https://www.youtube.com/@example'}).status_code,401)
