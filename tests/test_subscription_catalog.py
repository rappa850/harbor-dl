import asyncio
import functools
import tempfile
import threading
import unittest
import uuid
import wave
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.media import MediaInspector
from backend.subscriptions import SubscriptionConfig
from backend.subscription_catalog import SyncBusy


class CatalogInspector:
    def __init__(self):
        self.info={'_type':'playlist','id':'UCexample','entries':[
            {'id':f'video_{i}','title':f'作品 {i}','duration':10,'upload_date':'20261003'} for i in range(25)]}
        self.info['entries'][0]['upload_date']='20261004'
        self.calls=[]

    async def raw_info(self,url,network=None,catalog=False):
        self.calls.append((url,network,catalog));return self.info


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.inspector=CatalogInspector()
        self.app=create_app(self.temp.name,inspector=self.inspector);self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[{'platform':'youtube','user_id':'UCexample'}]})
        self.item=self.client.get('/api/subscriptions').json()['items'][0]
        self.url='/api/subscriptions/'+self.item['id']

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def test_full_sync_paging_resync_preserves_download_association(self):
        self.assertTrue(self.item['runtime']['manual_sync_available'])
        response=self.client.post(self.url+'/sync')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['new_videos_count'],25)
        self.assertTrue(self.inspector.calls[0][2])
        self.assertEqual(self.inspector.calls[0][0],'https://www.youtube.com/channel/UCexample/videos')
        first=self.client.get(self.url+'/videos').json()
        last=self.client.get(self.url+'/videos?page=3').json()
        self.assertEqual(first['total'],25);self.assertEqual(len(first['videos']),10)
        self.assertEqual(len(last['videos']),5)
        item=first['videos'][0]
        self.assertEqual(item['video_id'],'video_0')
        self.assertEqual(item['publish_time'],'2026-10-04T00:00:00+00:00')
        with self.app.state.store.connect() as db:
            db.execute('UPDATE subscription_videos SET downloaded=1,download_task_id=? WHERE id=?',('existing-task',item['id']))
        self.inspector.info['entries'].append(self.inspector.info['entries'][0])
        for entry in self.inspector.info['entries']:entry['title']='更新的标题'
        self.assertEqual(self.client.post(self.url+'/sync').json()['new_videos_count'],0)
        changed=next(v for v in self.client.get(self.url+'/videos').json()['videos'] if v['id']==item['id'])
        self.assertEqual(changed['title'],'更新的标题');self.assertTrue(changed['downloaded'])
        self.assertEqual(changed['download_task_id'],'existing-task')
        self.assertEqual(self.app.state.store.one('SELECT COUNT(*) AS n FROM tasks')['n'],0)
        persisted=create_app(self.temp.name)
        self.assertEqual(persisted.state.catalog.list(self.item['id'])['total'],25)

    def test_failure_does_not_replace_existing_catalog_and_auth(self):
        self.client.post(self.url+'/sync')
        self.inspector.info['entries'].append(None)
        self.assertEqual(self.client.post(self.url+'/sync').status_code,422)
        self.assertEqual(self.client.get(self.url+'/videos').json()['total'],25)
        self.inspector.info['id']='different-channel'
        self.assertEqual(self.client.post(self.url+'/sync').status_code,422)
        self.assertEqual(self.client.get(self.url+'/videos?page=0').status_code,422)
        self.assertEqual(self.client.post('/api/subscriptions/'+str(uuid.uuid4())+'/sync').status_code,404)
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[{'platform':'x','user_id':'author'}]})
        unsupported=next(x for x in self.client.get('/api/subscriptions').json()['items'] if x['platform']=='x')
        self.assertFalse(unsupported['runtime']['manual_sync_available'])
        self.assertEqual(self.client.post('/api/subscriptions/'+unsupported['id']+'/sync').status_code,422)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post(self.url+'/sync').status_code,401)
        self.assertEqual(self.client.get(self.url+'/videos').status_code,401)

    def test_active_sync_duplicate_cancellation_and_deleted_subscription(self):
        async def exercise():
            service=self.app.state.catalog
            started=asyncio.Event();finish=asyncio.Event()
            async def blocked(*args,**kwargs):
                started.set();await finish.wait();return self.inspector.info
            self.inspector.raw_info=blocked
            task=asyncio.create_task(service.sync(self.item['id']));await started.wait()
            with self.assertRaises(SyncBusy):await service.sync(self.item['id'])
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertFalse(service.active)
            started.clear()
            task=asyncio.create_task(service.sync(self.item['id']));await started.wait()
            with self.app.state.store.connect() as db:db.execute('DELETE FROM subscriptions WHERE id=?',(self.item['id'],))
            finish.set()
            with self.assertRaises(LookupError):await task
            self.assertEqual(self.app.state.store.one('SELECT COUNT(*) AS n FROM subscription_videos')['n'],0)
        asyncio.run(exercise())

    def test_real_worker_catalog_does_not_keep_identity_lookup_limit(self):
        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('one.wav','two.wav'):
                with wave.open(str(root/name),'wb') as media:
                    media.setnchannels(1);media.setsampwidth(2);media.setframerate(8000)
                    media.writeframes(b'\0\0'*800)
            (root/'index.html').write_text('<html><title>Catalog fixture</title><video src="one.wav"></video><video src="two.wav"></video></html>')
            server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=directory))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                info=asyncio.run(MediaInspector().raw_info(f'http://127.0.0.1:{server.server_port}/index.html',catalog=True))
                self.assertEqual(info['_type'],'playlist');self.assertEqual(len(info['entries']),2)
            finally:server.shutdown();server.server_close();thread.join()
