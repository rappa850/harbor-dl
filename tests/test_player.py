import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from backend.app import create_app


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(self.temp.name)
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def media(self):
        manager=self.app.state.manager
        task=manager.create('https://example.org/video')
        folder=manager.root/task['id'];folder.mkdir()
        (folder/'film.mp4').write_bytes(b'video')
        (folder/'film.en.srt').write_text('1\n00:00:01,500 --> 00:00:03,000\nHello\n',encoding='utf-8')
        (folder/'other.en.vtt').write_text('WEBVTT\n\n',encoding='utf-8')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path=? WHERE id=?",(f"{task['id']}/film.mp4",task['id']))
            manager.assets.register(db,dict(db.execute('SELECT * FROM tasks WHERE id=?',(task['id'],)).fetchone()))
        return task

    def test_subtitle_matching_conversion_and_retained_files(self):
        task=self.media()
        tracks=self.client.get(f"/api/files/{task['id']}/subtitles").json()['subtitles']
        self.assertEqual(len(tracks),1)
        self.assertEqual(tracks[0]['language'],'en')
        response=self.client.get(tracks[0]['path'])
        self.assertTrue(response.headers['content-type'].startswith('text/vtt'))
        self.assertIn('00:00:01.500 --> 00:00:03.000',response.text)
        self.assertTrue(response.text.startswith('WEBVTT'))
        asset=self.app.state.manager.assets.get(task['id'])
        self.client.delete(f"/api/tasks/{task['id']}?delete_file=false")
        self.assertEqual(len(self.client.get(f"/api/files/{asset['id']}/subtitles").json()['subtitles']),1)

    def test_subscription_scoped_record_roundtrip_and_invalid_progress(self):
        scope=str(uuid4());other=str(uuid4())
        self.assertIsNone(self.client.get(f'/api/playback/record/{scope}').json())
        payload={'current_index':3,'playback_mode':'random','video_progress':{'video-one':16.5}}
        response=self.client.put(f'/api/playback/record/{scope}',json=payload)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['video_progress'],payload['video_progress'])
        self.assertIsNone(self.client.get(f'/api/playback/record/{other}').json())
        payload['video_progress']={'video-one':-1}
        self.assertEqual(self.client.put(f'/api/playback/record/{scope}',json=payload).status_code,422)
        payload['video_progress']={};payload['playback_mode']='invalid'
        self.assertEqual(self.client.put(f'/api/playback/record/{scope}',json=payload).status_code,422)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get(f'/api/playback/record/{scope}').status_code,401)

    def test_missing_probe_returns_explicit_unavailability(self):
        task=self.media()
        with patch('backend.player.shutil.which',return_value=None):
            result=self.client.get(f"/api/files/{task['id']}/metadata")
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json()['success'])
