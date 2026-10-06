import tempfile
import unittest
import uuid
import os
import subprocess
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.subscription_cleanup import cleanup_orphans
from tests.test_subscription_catalog import CatalogInspector


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create_app(self.temp.name,inspector=CatalogInspector())
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[{'platform':'youtube','user_id':'UCexample'}]})
        self.subscription=self.client.get('/api/subscriptions').json()['items'][0]
        self.base='/api/subscriptions/'+self.subscription['id']
        self.client.post(self.base+'/sync')
        self.videos=self.client.get(self.base+'/videos?page_size=100').json()['videos']
        self.manager=self.app.state.manager

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def complete(self,index,missing=True):
        task=self.client.post(self.base+'/videos/'+self.videos[index]['id']+'/download',json={}).json()
        folder=self.manager.root/task['id'];folder.mkdir()
        media=folder/'media.mp4';media.write_bytes(b'media')
        (folder/'media.zh.vtt').write_text('WEBVTT')
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET status=?,file_path=? WHERE id=?',('COMPLETED',task['id']+'/media.mp4',task['id']))
            self.manager.assets.register(db,dict(db.execute('SELECT * FROM tasks WHERE id=?',(task['id'],)).fetchone()))
            self.manager.event(db,task['id'],'COMPLETED','fixture event')
        if missing:media.unlink()
        return task,folder

    def cleanup(self,**payload):
        response=self.client.post(self.base+'/videos/orphan/cleanup',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_default_cleanup_resets_only_missing_works_and_removes_residuals(self):
        orphan,folder=self.complete(0);healthy,healthy_folder=self.complete(1,False)
        active=self.client.post(self.base+'/videos/'+self.videos[2]['id']+'/download',json={}).json()
        result=self.cleanup()
        self.assertEqual((result['matched'],result['reset_videos'],result['deleted_tasks'],result['deleted_paths_count']),(1,1,1,1))
        self.assertFalse(folder.exists());self.assertTrue(healthy_folder.exists())
        self.assertIsNone(self.manager.get(orphan['id']));self.assertIsNotNone(self.manager.get(healthy['id']))
        self.assertEqual(self.manager.get(active['id'])['status'],'PENDING')
        stats=self.client.get(self.base+'/videos/stats').json()
        self.assertEqual(stats['orphaned_count'],0);self.assertEqual(stats['downloaded_count'],1)
        self.assertEqual(self.app.state.store.one('SELECT COUNT(*) AS n FROM task_events WHERE task_id=?',(orphan['id'],))['n'],0)
        self.assertEqual(self.app.state.store.one('SELECT COUNT(*) AS n FROM media_assets WHERE task_id=?',(orphan['id'],))['n'],0)
        response=self.client.post(self.base+'/videos/'+self.videos[0]['id']+'/download',json={})
        self.assertEqual(response.status_code,201)
        self.assertEqual(self.cleanup()['matched'],0)

    def test_preserve_residual_assets_and_task_already_removed(self):
        task,folder=self.complete(0)
        result=self.cleanup(delete_residual=False)
        self.assertEqual(result['deleted_paths_count'],0);self.assertTrue((folder/'media.zh.vtt').is_file())
        self.assertIsNone(self.manager.get(task['id']))
        assets=self.client.get('/api/files?attachments=true').json()['items']
        self.assertEqual(len(assets),1);self.assertIsNone(assets[0]['task_id'])
        second,second_folder=self.complete(1)
        self.client.delete('/api/tasks/'+second['id']+'?delete_file=false')
        result=self.cleanup()
        self.assertEqual(result['reset_videos'],1);self.assertEqual(result['deleted_tasks'],0)
        self.assertFalse(second_folder.exists())

    def test_live_and_shared_task_protection(self):
        task,folder=self.complete(0)
        self.manager.running[task['id']]=object()
        result=self.cleanup()
        self.assertEqual(result['reset_videos'],0);self.assertTrue(folder.exists())
        self.manager.running.clear()
        with self.app.state.store.connect() as db:
            db.execute('UPDATE subscription_videos SET download_task_id=? WHERE id=?',(task['id'],self.videos[1]['id']))
        result=self.cleanup()
        self.assertEqual(result['reset_videos'],0);self.assertTrue(result['errors'])
        self.assertIsNotNone(self.manager.get(task['id']))

    def test_restored_file_rechecked_and_sql_failure_does_not_remove_folder(self):
        task,folder=self.complete(0)
        stale=self.app.state.catalog.records(self.subscription['id'])
        (folder/'media.mp4').write_bytes(b'restored')
        with patch.object(self.app.state.catalog,'records',return_value=stale):
            result=cleanup_orphans(self.app.state.store,self.app.state.catalog,self.manager,self.subscription['id'])
        self.assertEqual(result['matched'],1);self.assertEqual(result['reset_videos'],0)
        self.assertTrue((folder/'media.mp4').is_file())
        (folder/'media.mp4').unlink()
        with self.app.state.store.connect() as db:
            db.executescript("CREATE TRIGGER prevent_reset BEFORE UPDATE ON subscription_videos BEGIN SELECT RAISE(ABORT,'fixture failure'); END;")
        result=self.cleanup()
        self.assertEqual(result['reset_videos'],0);self.assertTrue(folder.exists())
        self.assertIsNotNone(self.manager.get(task['id']))

    def test_path_ownership_auth_and_unknown_subscription(self):
        task,folder=self.complete(0)
        outside=Path(self.temp.name)/'outside.mp4';outside.write_bytes(b'keep')
        with self.app.state.store.connect() as db:
            db.execute('UPDATE media_assets SET path=? WHERE task_id=? AND is_primary=1',('../outside.mp4',task['id']))
        result=self.cleanup()
        self.assertEqual(result['reset_videos'],0);self.assertTrue(outside.is_file());self.assertTrue(folder.exists())
        self.assertEqual(self.client.post('/api/subscriptions/'+str(uuid.uuid4())+'/videos/orphan/cleanup',json={}).status_code,404)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post(self.base+'/videos/orphan/cleanup',json={}).status_code,401)

    def test_linked_residual_directory_is_not_followed(self):
        task,folder=self.complete(0)
        with tempfile.TemporaryDirectory() as other:
            target=Path(other);(target/'keep.txt').write_text('keep')
            link=folder/'linked'
            if os.name=='nt':
                made=subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],capture_output=True)
                self.assertEqual(made.returncode,0,made.stderr.decode(errors='replace'))
            else:link.symlink_to(target,target_is_directory=True)
            try:
                result=self.cleanup()
                self.assertEqual(result['reset_videos'],0)
                self.assertTrue((target/'keep.txt').is_file())
                self.assertIsNotNone(self.manager.get(task['id']))
            finally:
                if os.name=='nt':os.rmdir(link)
                else:link.unlink()
