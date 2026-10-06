import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.subscription_downloads import DownloadConflict,queue_video
from tests.test_subscription_catalog import CatalogInspector
from tests.test_task_lifecycle import until

WORKER=Path(__file__).parent/'fixtures/task_worker.py'


class SubscriptionDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(self.temp.name,inspector=CatalogInspector())
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[{'platform':'youtube','user_id':'UCexample','nickname':'频道'}]})
        self.subscription=self.client.get('/api/subscriptions').json()['items'][0]
        self.base='/api/subscriptions/'+self.subscription['id']
        self.client.post(self.base+'/sync')
        self.video=self.client.get(self.base+'/videos').json()['videos'][0]
        self.url=self.base+'/videos/'+self.video['id']+'/download'
        self.manager=self.app.state.manager

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def current(self):
        return next(v for v in self.client.get(self.base+'/videos').json()['videos'] if v['id']==self.video['id'])

    def test_scope_options_duplicate_submission_and_auth(self):
        self.client.patch(self.base,json={'quality':'1080'})
        response=self.client.post(self.url,json={})
        self.assertEqual(response.status_code,201,response.text)
        task=response.json()
        self.assertEqual(task['subscription_id'],self.subscription['id'])
        self.assertEqual(task['source'],'youtube');self.assertEqual(task['author'],'频道')
        self.assertIn('height<=1080',task['format_id'])
        self.assertEqual(self.current()['status'],'downloading')
        self.assertEqual(self.client.post(self.url,json={'redownload':True}).status_code,409)
        self.assertEqual(self.client.post('/api/subscriptions/'+str(uuid.uuid4())+'/videos/'+self.video['id']+'/download',json={}).status_code,404)
        self.assertEqual(self.client.get('/api/tasks?subscription_id='+self.subscription['id']).json()['total'],1)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post(self.url,json={}).status_code,401)

    def test_actual_child_processing_completion_file_keep_and_redownload(self):
        task=self.client.post(self.url,json={}).json()
        self.manager.command_builder=lambda task,folder:[sys.executable,'-X','utf8','-u',str(WORKER),str(folder),'complete']
        async def exercise():
            running=asyncio.create_task(self.manager.run(task))
            await until(lambda:self.manager.get(task['id'])['status']=='PROCESSING')
            state=self.app.state.catalog.list(self.subscription['id'])['videos'][0]
            self.assertEqual(state['task_status'],'PROCESSING');self.assertEqual(state['status'],'downloading')
            (self.manager.root/task['id']/'release').touch()
            await running
        asyncio.run(exercise())
        self.assertEqual(self.current()['status'],'downloaded');self.assertTrue(self.current()['downloaded'])
        self.assertEqual(self.client.post(self.url,json={}).status_code,409)
        self.assertEqual(self.client.delete('/api/tasks/'+task['id']+'?delete_file=false').status_code,200)
        self.assertEqual(self.current()['status'],'downloaded')
        old_file=self.manager.root/task['id']/'complete.mp4'
        old_file.unlink()
        self.assertEqual(self.current()['status'],'orphaned');self.assertFalse(self.current()['file_available'])
        new=self.client.post(self.url,json={})
        self.assertEqual(new.status_code,201,new.text)
        self.assertNotEqual(new.json()['id'],task['id'])

    def test_failure_retry_cancel_and_restart_writeback(self):
        task=self.client.post(self.url,json={}).json()
        self.manager.command_builder=lambda task,folder:[sys.executable,'-X','utf8','-u',str(WORKER),str(folder),'error']
        asyncio.run(self.manager.run(task))
        self.assertEqual(self.current()['status'],'failed');self.assertIn('失败',self.current()['error_message'])
        self.assertTrue(self.manager.retry(task['id']))
        self.assertEqual(self.current()['status'],'downloading');self.assertIsNone(self.current()['error_message'])
        asyncio.run(self.manager.cancel(task['id']))
        self.assertEqual(self.current()['status'],'cancelled')
        replacement=self.client.post(self.url,json={}).json()
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET status=? WHERE id=?',('PROCESSING',replacement['id']))
        async def restart():
            await self.manager.start();await self.manager.stop()
        asyncio.run(restart())
        self.assertEqual(self.current()['status'],'failed')
        self.assertIn('退出',self.current()['error_message'])

    def test_explicit_redownload_retains_original_file_and_ignores_old_events(self):
        task=self.client.post(self.url,json={}).json()
        folder=self.manager.root/task['id'];folder.mkdir()
        (folder/'original.mp4').write_bytes(b'original-media')
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET status=?,file_path=? WHERE id=?',('COMPLETED',task['id']+'/original.mp4',task['id']))
            self.manager.event(db,task['id'],'COMPLETED','fixture completed')
        self.assertEqual(self.client.post(self.url,json={}).status_code,409)
        replacement=self.client.post(self.url,json={'redownload':True})
        self.assertEqual(replacement.status_code,201,replacement.text)
        self.assertNotEqual(replacement.json()['id'],task['id'])
        self.assertTrue((folder/'original.mp4').is_file())
        with self.app.state.store.connect() as db:
            self.manager.event(db,task['id'],'ERROR','late old event')
        self.assertEqual(self.current()['download_task_id'],replacement.json()['id'])
        self.assertIsNone(self.current()['error_message'])

    def test_concurrent_submission_only_enqueues_one(self):
        def submit():
            try:return queue_video(self.app.state.store,self.manager,self.subscription['id'],self.video['id'])['id']
            except DownloadConflict:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:submit(),range(2)))
        self.assertEqual(sum(value is not None for value in results),1)
        self.assertEqual(self.app.state.store.one('SELECT COUNT(*) AS n FROM tasks')['n'],1)

    def test_failed_association_rolls_back_task_and_event(self):
        with self.app.state.store.connect() as db:
            db.executescript("CREATE TRIGGER fail_association BEFORE UPDATE ON subscription_videos BEGIN SELECT RAISE(ABORT,'fixture failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            queue_video(self.app.state.store,self.manager,self.subscription['id'],self.video['id'])
        self.assertEqual(self.app.state.store.one('SELECT COUNT(*) AS n FROM tasks')['n'],0)
        self.assertEqual(self.app.state.store.one('SELECT COUNT(*) AS n FROM task_events')['n'],0)
        self.assertIsNone(self.current()['download_task_id'])
