import asyncio
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from backend.app import create_app
from tests.test_subscription_catalog import CatalogInspector


class SubscriptionDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(self.temp.name,inspector=CatalogInspector())
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[
            {'platform':'youtube','user_id':'UCexample'}]})
        self.scope=self.client.get('/api/subscriptions').json()['items'][0]['id']
        self.base=f'/api/subscriptions/{self.scope}'
        self.client.post(self.base+'/sync')
        self.work=self.client.get(self.base+'/videos').json()['videos'][0]
        self.url=self.base+'/videos/'+self.work['id']

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def test_completed_record_deletion_preserves_task_events_files_assets_and_progress(self):
        task=self.client.post(self.url+'/download',json={}).json()
        manager=self.app.state.manager
        folder=manager.root/task['id'];folder.mkdir()
        for name in ('film.mp4','film.en.srt','film.nfo','film.jpg'):
            (folder/name).write_bytes(name.encode())
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET status=?,file_path=? WHERE id=?',('COMPLETED',task['id']+'/film.mp4',task['id']))
            manager.event(db,task['id'],'COMPLETED','fixture')
            manager.assets.register(db,dict(db.execute('SELECT * FROM tasks WHERE id=?',(task['id'],)).fetchone()))
        progress={'current_index':0,'playback_mode':'order','video_progress':{self.work['id']:12}}
        self.client.put('/api/playback/record/'+self.scope,json=progress)
        store=self.app.state.store
        tasks=store.all('SELECT * FROM tasks');events=store.all('SELECT * FROM task_events')
        assets=store.all('SELECT * FROM media_assets');record=store.all('SELECT * FROM playback_records')
        self.assertEqual(self.client.delete(self.url).status_code,200)
        self.assertEqual(store.all('SELECT * FROM tasks'),tasks)
        self.assertEqual(store.all('SELECT * FROM task_events'),events)
        self.assertEqual(store.all('SELECT * FROM media_assets'),assets)
        self.assertEqual(store.all('SELECT * FROM playback_records'),record)
        for asset in assets:
            self.assertEqual(self.client.get(f'/api/files/{asset["id"]}/stream').content,
                             (manager.root/asset['path']).read_bytes())
        self.assertEqual(self.client.get(self.base+'/videos/stats').json()['total'],24)
        self.assertEqual(self.client.get(self.base+'/playable').json()['total'],0)
        self.assertEqual({item['path'] for item in self.client.get('/api/files').json()['items']},
                         {task['id']+'/film.mp4',task['id']+'/film.jpg'})

    def test_active_task_is_retained_and_late_events_do_not_recreate_record(self):
        task=self.client.post(self.url+'/download',json={}).json()
        self.assertEqual(self.client.delete(self.url).status_code,200)
        self.assertEqual(self.app.state.manager.get(task['id'])['status'],'PENDING')
        asyncio.run(self.app.state.manager.cancel(task['id']))
        self.assertIsNone(self.app.state.store.one('SELECT * FROM subscription_videos WHERE id=?',(self.work['id'],)))
        self.assertEqual(self.app.state.manager.get(task['id'])['status'],'CANCELLED')

    def test_missing_wrong_scope_repeat_and_unauthenticated_deletions(self):
        wrong=f'/api/subscriptions/{uuid4()}/videos/{self.work["id"]}'
        self.assertEqual(self.client.delete(wrong).status_code,404)
        self.assertEqual(self.client.get(self.base+'/videos').json()['total'],25)
        self.assertEqual(self.client.delete(self.base+'/videos/'+str(uuid4())).status_code,404)
        self.assertEqual(self.client.delete(self.url).status_code,200)
        self.assertEqual(self.client.delete(self.url).status_code,404)
        remaining=self.client.get(self.base+'/videos').json()['videos'][0]
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.delete(self.base+'/videos/'+remaining['id']).status_code,401)

    def test_sync_rediscovery_is_explicit_current_behavior_not_a_blacklist(self):
        self.assertEqual(self.client.delete(self.url).status_code,200)
        result=self.client.post(self.base+'/sync')
        self.assertEqual(result.json()['new_videos_count'],1)
        restored=self.app.state.store.one('SELECT * FROM subscription_videos WHERE subscription_id=? AND video_id=?',
                                          (self.scope,self.work['video_id']))
        self.assertNotEqual(restored['id'],self.work['id'])
        self.assertIsNone(restored['download_task_id'])
