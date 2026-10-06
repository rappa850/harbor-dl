import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.subscription_nfo import MAX_BYTES
from tests.test_subscription_catalog import CatalogInspector


class NfoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create_app(self.temp.name,inspector=CatalogInspector())
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[{'platform':'youtube','user_id':'UCexample'}]})
        subscription=self.client.get('/api/subscriptions').json()['items'][0]
        self.base='/api/subscriptions/'+subscription['id'];self.client.post(self.base+'/sync')
        self.video=self.client.get(self.base+'/videos').json()['videos'][0]
        self.url=self.base+'/videos/'+self.video['id']+'/nfo'
        self.manager=self.app.state.manager
        self.task=self.client.post(self.base+'/videos/'+self.video['id']+'/download',json={}).json()
        self.folder=self.manager.root/self.task['id'];self.folder.mkdir()
        (self.folder/'media.mp4').write_bytes(b'media')
        self.path=self.folder/'media.nfo';self.path.write_bytes('<movie><title>原名</title></movie>\r\n'.encode())
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET status=?,file_path=? WHERE id=?',('COMPLETED',self.task['id']+'/media.mp4',self.task['id']))
            self.manager.event(db,self.task['id'],'COMPLETED','fixture complete')

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def test_existing_nfo_roundtrip_and_asset_id_preserved(self):
        self.assertTrue(self.client.get(self.url+'/exists').json()['has_nfo'])
        original=self.client.get(self.url).json()
        self.assertEqual(original['content'],'<movie><title>原名</title></movie>\r\n')
        content='<movie>\n  <title>新名 &amp; 更多</title>\n</movie>\n'
        response=self.client.put(self.url,json={'content':content,'expected_etag':original['etag'],'expected_task_id':original['task_id']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.path.read_bytes(),content.encode())
        self.assertEqual(self.client.get(self.url).json()['content'],content)
        assets=self.client.get('/api/files?attachments=true').json()['items'];self.assertEqual(len(assets),1)
        asset_id=assets[0]['id']
        self.client.put(self.url,json={'content':'<movie />'})
        self.assertEqual(self.client.get('/api/files?attachments=true').json()['items'][0]['id'],asset_id)
        self.assertFalse(list(self.folder.glob('.harbor-nfo-*')))

    def test_conflicting_content_and_task_does_not_overwrite(self):
        original=self.client.get(self.url).json()
        self.path.write_text('external edit',encoding='utf-8')
        self.assertEqual(self.client.put(self.url,json={'content':'stale edit','expected_etag':original['etag']}).status_code,409)
        self.assertEqual(self.path.read_text(),'external edit')
        fresh=self.client.get(self.url).json()
        self.assertEqual(self.client.put(self.url,json={'content':'edit','expected_etag':fresh['etag'],'expected_task_id':str(uuid.uuid4())}).status_code,409)
        self.assertEqual(self.path.read_text(),'external edit')

    def test_missing_media_or_nfo_and_scope_auth(self):
        self.path.unlink()
        self.assertFalse(self.client.get(self.url+'/exists').json()['has_nfo'])
        self.assertEqual(self.client.get(self.url).status_code,404)
        self.assertEqual(self.client.put(self.url,json={'content':'new'}).status_code,404)
        self.path.write_text('nfo',encoding='utf-8');(self.folder/'media.mp4').unlink()
        self.assertFalse(self.client.get(self.url+'/exists').json()['has_nfo'])
        self.assertEqual(self.client.get(self.url).status_code,409)
        self.assertEqual(self.client.get('/api/subscriptions/'+str(uuid.uuid4())+'/videos/'+self.video['id']+'/nfo').status_code,404)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get(self.url).status_code,401)
        self.assertEqual(self.client.put(self.url,json={'content':'x'}).status_code,401)

    def test_limits_invalid_encoding_and_replace_failure_preserves_file(self):
        self.path.write_bytes(b'\xff')
        self.assertEqual(self.client.get(self.url).status_code,422)
        self.path.write_bytes(b'x'*(MAX_BYTES+1))
        self.assertEqual(self.client.get(self.url).status_code,422)
        self.path.write_text('original',encoding='utf-8')
        self.assertEqual(self.client.put(self.url,json={'content':'字'*(MAX_BYTES//2)}).status_code,422)
        with patch('backend.subscription_nfo.os.replace',side_effect=OSError('fixture failed')):
            self.assertEqual(self.client.put(self.url,json={'content':'changed'}).status_code,409)
        self.assertEqual(self.path.read_text(),'original')
        self.assertFalse(list(self.folder.glob('.harbor-nfo-*')))

    def test_retained_file_after_task_deletion_and_live_worker_guard(self):
        self.manager.running[self.task['id']]=object()
        self.assertEqual(self.client.get(self.url).status_code,409)
        self.manager.running.clear()
        self.assertEqual(self.client.delete('/api/tasks/'+self.task['id']+'?delete_file=false').status_code,200)
        self.assertTrue(self.client.get(self.url+'/exists').json()['has_nfo'])
        self.assertEqual(self.client.put(self.url,json={'content':'retained edit'}).status_code,200)
        self.assertIsNone(self.client.get('/api/files?attachments=true').json()['items'][0]['task_id'])

    def test_foreign_task_or_file_path_does_not_allow_edit(self):
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET subscription_id=? WHERE id=?',(str(uuid.uuid4()),self.task['id']))
        self.assertEqual(self.client.put(self.url,json={'content':'foreign edit'}).status_code,422)
        self.assertIn('原名',self.path.read_text(encoding='utf-8'))
        outside=Path(self.temp.name)/'outside.mp4';outside.write_bytes(b'outside media')
        sidecar=outside.with_suffix('.nfo');sidecar.write_text('outside nfo',encoding='utf-8')
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET file_path=? WHERE id=?',('../outside.mp4',self.task['id']))
        self.assertEqual(self.client.put(self.url,json={'content':'overwrite'}).status_code,409)
        self.assertEqual(sidecar.read_text(),'outside nfo')
