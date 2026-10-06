import tempfile
import unittest
import uuid
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.subscription_downloads import format_for_quality
from tests.test_subscription_catalog import CatalogInspector


class SubscriptionQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create_app(self.temp.name,inspector=CatalogInspector())
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[{'platform':'youtube','user_id':'UCexample'}]})
        self.subscription=self.client.get('/api/subscriptions').json()['items'][0]
        self.base='/api/subscriptions/'+self.subscription['id']
        self.client.post(self.base+'/sync')
        self.videos=self.client.get(self.base+'/videos?page_size=100').json()['videos']

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def seed_states(self):
        manager=self.app.state.manager
        statuses=['PENDING','DOWNLOADING','PROCESSING','COMPLETED','COMPLETED','ERROR','CANCELLED','COMPLETED','COMPLETED']
        for index,status in enumerate(statuses):
            video=self.videos[index]
            task=self.client.post(self.base+'/videos/'+video['id']+'/download',json={}).json()
            folder=manager.root/task['id'];folder.mkdir()
            if index in (3,7,8):(folder/'media.mp4').write_bytes(b'test-media')
            with self.app.state.store.connect() as db:
                db.execute('UPDATE tasks SET status=?,file_path=?,error=? WHERE id=?',
                           (status,task['id']+'/media.mp4' if status=='COMPLETED' else None,'download error' if status=='ERROR' else '',task['id']))
                manager.event(db,task['id'],status,'download error' if status=='ERROR' else 'fixture event')
            if index==7:self.client.delete('/api/tasks/'+task['id']+'?delete_file=false')
            if index==8:self.client.delete('/api/tasks/'+task['id'])
        with self.app.state.store.connect() as db:
            db.execute('UPDATE subscription_videos SET downloaded=1 WHERE id=?',(self.videos[9]['id'],))

    def test_stats_and_filters_partition_saved_works(self):
        self.seed_states()
        stats=self.client.get(self.base+'/videos/stats').json()
        expected={'downloaded':2,'downloading':3,'not_downloaded':15,'failed':1,'cancelled':1,'orphaned':3}
        self.assertEqual(stats['total'],25)
        self.assertEqual(set(stats['supported_statuses']),set(expected))
        for status,count in expected.items():
            self.assertEqual(stats[status+'_count'],count)
            response=self.client.get(self.base+'/videos?status='+status).json()
            self.assertEqual(response['total'],count)
            self.assertTrue(all(item['status']==status for item in response['videos']))
        self.assertEqual(sum(stats[s+'_count'] for s in expected),25)

    def test_file_missing_filter_before_pagination_and_live_recheck(self):
        self.seed_states()
        first=self.client.get(self.base+'/videos?status=orphaned&page_size=2').json()
        second=self.client.get(self.base+'/videos?status=orphaned&page_size=2&page=2').json()
        self.assertEqual(first['total'],3);self.assertEqual(second['total'],3)
        self.assertEqual(len(first['videos']),2);self.assertEqual(len(second['videos']),1)
        self.assertEqual(len({v['id'] for v in first['videos']+second['videos']}),3)
        downloaded=self.client.get(self.base+'/videos?status=downloaded').json()['videos']
        self.assertEqual(len(downloaded),2)
        task=next(v for v in downloaded if v['task_status']=='COMPLETED')
        path=self.app.state.store.one('SELECT download_file_path FROM subscription_videos WHERE id=?',(task['id'],))['download_file_path']
        (self.app.state.manager.root/path).unlink()
        stats=self.client.get(self.base+'/videos/stats').json()
        self.assertEqual(stats['downloaded_count'],1);self.assertEqual(stats['orphaned_count'],4)

    def test_query_validation_auth_and_quality_expression(self):
        self.assertEqual(self.client.get(self.base+'/videos?status=removed').status_code,422)
        self.assertEqual(self.client.get(self.base+'/videos?status=charging').status_code,422)
        self.assertEqual(self.client.get('/api/subscriptions/'+str(uuid.uuid4())+'/videos/stats').status_code,404)
        for quality in ['bestvideo+bestaudio','bestvideo[height<=4320]+bestaudio','bestvideo[height<=1080]+bestaudio']:
            self.assertEqual(format_for_quality(quality),quality)
        self.client.patch(self.base,json={'quality':'bestvideo[height<=720]+bestaudio'})
        response=self.client.post(self.base+'/videos/'+self.videos[0]['id']+'/download',json={})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['format_id'],'bestvideo[height<=720]+bestaudio')
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get(self.base+'/videos/stats').status_code,401)
