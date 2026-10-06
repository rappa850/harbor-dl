import json
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.covers import key_for
from backend.library_covers import PosterResolver
from backend.library_names import clean_name, split_description, truncate_bytes
from backend.library_nfo import build_movie_nfo
from backend.live_recording import ffmpeg_executable
from tests.test_library import jpeg, png


class NameTests(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(clean_name('a/b\\c:d*e?f"g<h>i|j'), 'a_b_c_d_e_f_g_h_i_j')
        self.assertEqual(clean_name('  title. .  '), 'title')
        self.assertEqual(clean_name('CON'), '_CON')
        self.assertEqual(clean_name('nul.txt'), '_nul.txt')
        self.assertEqual(clean_name('???'), 'untitled')
        self.assertEqual(clean_name('', fallback='x'), 'x')

    def test_truncation_never_splits_a_character(self):
        text = '猫' * 100
        cut = truncate_bytes(text, 20)
        self.assertEqual(cut, '猫' * 6)
        self.assertLessEqual(len(clean_name(text, 120).encode()), 120)

    def test_split_description(self):
        title, plot, tags = split_description('今天的穿搭 #原神 #cos #原神', '123')
        self.assertEqual((title, tags), ('今天的穿搭', ['原神', 'cos']))
        self.assertIn('#cos', plot)
        self.assertEqual(split_description('#只有话题', '987')[0], '987')
        self.assertEqual(split_description(None, '5')[0], '5')
        long_title = split_description('字' * 200, '1')[0]
        self.assertEqual(len(long_title), 61)


class NfoTests(unittest.TestCase):
    def test_document_is_well_formed_and_complete(self):
        xml = build_movie_nfo({'title': 'A & B <c>', 'plot': '多行\n"引号"\x01\x0b', 'premiered': '2026-10-06', 'dateadded': '2026-10-07 08:09:10',
                               'runtime_minutes': 2, 'duration_seconds': 95.5, 'author': '作者', 'platform': 'douyin', 'platform_name': '抖音',
                               'work_id': '769', 'source_url': 'https://www.douyin.com/video/769?a=1&b=2', 'tags': ['话题', 'x&y'], 'poster': 'poster.jpg'})
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="utf-8" standalone="yes"?>'))
        root = ET.fromstring(xml.encode('utf-8'))
        self.assertEqual(root.tag, 'movie')
        self.assertEqual(root.findtext('title'), 'A & B <c>')
        self.assertEqual(root.findtext('plot'), '多行\n"引号"')
        self.assertEqual(root.findtext('year'), '2026')
        self.assertEqual(root.findtext('director'), '作者')
        self.assertEqual([t.text for t in root.findall('tag')], ['话题', 'x&y'])
        uid = root.find('uniqueid')
        self.assertEqual((uid.get('type'), uid.get('default'), uid.text), ('douyin', 'true', '769'))
        self.assertEqual(root.find('thumb').get('aspect'), 'poster')
        self.assertEqual(root.findtext('thumb'), 'poster.jpg')
        self.assertEqual(root.findtext('lockdata'), 'true')
        self.assertEqual(root.findtext('fileinfo/streamdetails/video/durationinseconds'), '95')
        self.assertEqual(root.findtext('website'), 'https://www.douyin.com/video/769?a=1&b=2')

    def test_minimal_document(self):
        root = ET.fromstring(build_movie_nfo({'title': 't'}).encode())
        self.assertIsNone(root.find('premiered'))
        self.assertIsNone(root.find('thumb'))


class PosterTests(unittest.TestCase):
    def test_png_and_jpeg_are_kept_other_formats_need_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            (temp / 'a.png').write_bytes(png(10, 20))
            (temp / 'b.jpeg').write_bytes(jpeg(10, 20))
            (temp / 'c.avif').write_bytes(b'not really')
            out = temp / 'out'
            out.mkdir()
            resolver = PosterResolver(None, ffmpeg=None)
            self.assertEqual(resolver.place(temp / 'a.png', out).name, 'poster.png')
            self.assertEqual(resolver.place(temp / 'b.jpeg', out).name, 'poster.jpg')
            self.assertEqual([p.name for p in out.iterdir()], ['poster.jpg'])      # the older poster.png was replaced
            self.assertIsNone(resolver.place(temp / 'c.avif', out))                 # cannot convert without ffmpeg


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.app = create_app(self.base / 'data')
        self.client = TestClient(self.app)
        self.client.post('/api/setup', json={'username': 'admin', 'password': 'test-password-123'})
        self.library = self.base / 'media'
        self.enable()

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def enable(self, **extra):
        body = {'concurrency': 2, 'library': {'enabled': True, 'auto': False, 'root': str(self.library), **extra}}
        return self.client.put('/api/settings', json=body)

    def work(self, title='今天的穿搭 #原神', source='douyin', video=b'video-bytes', name='clip [769].mp4', author='作者A'):
        manager = self.app.state.manager
        task = manager.create(f'https://www.douyin.com/video/{name}', title, source=source, author=author)
        folder = manager.root / task['id']
        folder.mkdir()
        (folder / name).write_bytes(video)
        (folder / 'clip [769].zh.vtt').write_text('WEBVTT')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path=? WHERE id=?", (f"{task['id']}/{name}", task['id']))
            manager.assets.register(db, dict(db.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone()))
        return task

    def cache_cover(self, url, data=None, ext='.jpg'):
        key = key_for(url)
        folder = self.base / 'data' / 'covers' / key[:2] / key[2:4]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{key}{ext}').write_bytes(data or jpeg(300, 400))

    def export(self, task, **query):
        suffix = '?' + '&'.join(f'{k}={v}' for k, v in query.items()) if query else ''
        return self.client.post(f"/api/library/export/tasks/{task['id']}{suffix}")

    def test_settings_validate_the_root(self):
        self.assertEqual(self.client.get('/api/settings').json()['library']['root'], str(self.library))
        self.assertEqual(self.enable(root='relative/path').status_code, 400)
        self.assertEqual(self.enable(root=str(self.base / 'data' / 'downloads')).status_code, 400)
        self.assertEqual(self.enable(root=str(self.base / 'data' / 'covers' / 'x')).status_code, 400)
        self.assertEqual(self.enable(root=str(self.base / 'data')).status_code, 400)       # a parent of the download tree
        self.assertTrue(self.enable(root=str(self.library)).json()['library']['enabled'])

    def test_exports_video_nfo_poster_and_manifest_in_one_folder(self):
        task = self.work()
        self.cache_cover(task['url'])
        result = self.export(task)
        self.assertEqual(result.status_code, 200, result.text)
        folder = Path(result.json()['folder'])
        self.assertEqual(folder.parent, self.library / '作者A')
        self.assertEqual(folder.name, '今天的穿搭 [769]')
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ['.harbor.json', 'poster.jpg', '今天的穿搭 [769].mp4', '今天的穿搭 [769].nfo', '今天的穿搭 [769].zh.vtt'])
        self.assertEqual((folder / '今天的穿搭 [769].mp4').read_bytes(), b'video-bytes')
        root = ET.parse(folder / '今天的穿搭 [769].nfo').getroot()
        self.assertEqual(root.findtext('title'), '今天的穿搭')
        self.assertEqual(root.findtext('thumb'), 'poster.jpg')
        self.assertEqual(root.findtext('director'), '作者A')
        manifest = json.loads((folder / '.harbor.json').read_text(encoding='utf-8'))
        self.assertEqual((manifest['schema'], manifest['work_id'], manifest['platform'], manifest['cover_source']), (1, '769', 'douyin', 'cache'))
        self.assertEqual(manifest['task_id'], task['id'])
        self.assertTrue(any(f['role'] == 'video' for f in manifest['files']))
        # the download tree is untouched
        self.assertTrue((self.app.state.manager.root / task['id'] / 'clip [769].mp4').is_file())
        self.assertEqual(self.client.get('/api/files').status_code, 200)

    def test_video_is_hard_linked_when_possible(self):
        task = self.work()
        folder = Path(self.export(task).json()['folder'])
        source = self.app.state.manager.root / task['id'] / 'clip [769].mp4'
        try:
            import os
            self.assertTrue(os.path.samefile(source, folder / '今天的穿搭 [769].mp4'))
        except OSError:
            self.skipTest('file system without hard links')

    def test_second_export_changes_nothing_and_hand_edits_are_protected(self):
        task = self.work()
        self.cache_cover(task['url'])
        folder = Path(self.export(task).json()['folder'])
        self.assertEqual(self.export(task).json()['status'], 'unchanged')
        nfo = folder / '今天的穿搭 [769].nfo'
        nfo.write_text('<movie><title>我改的</title></movie>', encoding='utf-8')
        again = self.export(task).json()
        self.assertTrue(again['nfo_kept'])
        self.assertEqual(nfo.read_text(encoding='utf-8'), '<movie><title>我改的</title></movie>')
        forced = self.export(task, overwrite='true').json()
        self.assertFalse(forced['nfo_kept'])
        self.assertEqual(ET.parse(nfo).getroot().findtext('title'), '今天的穿搭')

    def test_nfo_editor_works_on_the_library_copy(self):
        self.client.post('/api/backup/subscriptions/import', json={'subscriptions': [{'platform': 'youtube', 'user_id': 'UCexample'}]})
        sub = self.client.get('/api/subscriptions').json()['items'][0]
        task = self.work()
        with self.app.state.store.connect() as db:
            db.execute('INSERT INTO subscription_videos(id,subscription_id,video_id,metadata,downloaded,download_task_id,created_at,updated_at) '
                       'VALUES (?,?,?,?,1,?,?,?)', ('11111111-1111-4111-8111-111111111111', sub['id'], '769', '{"title":"x"}', task['id'], 'now', 'now'))
            db.execute('UPDATE tasks SET subscription_id=? WHERE id=?', (sub['id'], task['id']))
        url = f"/api/subscriptions/{sub['id']}/videos/11111111-1111-4111-8111-111111111111/nfo"
        self.assertFalse(self.client.get(url + '/exists').json()['has_nfo'])             # nothing exported yet
        folder = Path(self.export(task).json()['folder'])
        self.assertTrue(self.client.get(url + '/exists').json()['has_nfo'])
        opened = self.client.get(url).json()
        self.assertIn('<movie>', opened['content'])
        edited = opened['content'].replace('<lockdata>true</lockdata>', '<lockdata>true</lockdata><tag>手改</tag>')
        saved = self.client.put(url, json={'content': edited, 'expected_etag': opened['etag'], 'expected_task_id': opened['task_id']})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(next(folder.glob('*.nfo')).read_text(encoding='utf-8'), edited)
        self.assertFalse([a for a in self.client.get('/api/files?attachments=true').json()['items'] if a['name'].endswith('.nfo')])
        self.assertTrue(self.export(task).json()['nfo_kept'])                              # and the edit survives the next export

    def test_gallery_and_audio_are_not_exported(self):
        task = self.work(name='pic [1].jpg', video=png(4, 4))
        self.assertEqual(self.export(task).status_code, 422)
        self.assertIn('图集', self.export(task).json()['detail'] if 'detail' in self.export(task).json() else self.export(task).text)
        audio = self.work(name='song [2].mp3', video=b'ID3')
        self.assertEqual(self.export(audio).status_code, 422)
        self.assertEqual(self.client.post('/api/library/export/tasks/nope').status_code, 422)

    def test_poster_fallbacks(self):
        task = self.work()
        # no cached cover, no thumbnail, and no usable video: no poster, but the export itself still works
        result = self.export(task).json()
        self.assertIsNone(result['cover_source'])
        folder = Path(result['folder'])
        self.assertIsNone(ET.parse(next(folder.glob('*.nfo'))).getroot().find('thumb'))
        # a thumbnail that yt-dlp left next to the video is used
        thumb = self.app.state.manager.root / task['id'] / 'clip [769].jpg'
        thumb.write_bytes(jpeg(100, 100))
        with self.app.state.store.connect() as db:
            self.app.state.manager.assets.register(db, dict(db.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone()))
        self.assertEqual(self.export(task).json()['cover_source'], 'thumbnail')
        # a cached cover takes over only when the poster came from a frame; a real poster is kept
        self.cache_cover(task['url'], png(30, 40), '.png')
        self.assertEqual(self.export(task).json()['cover_source'], 'thumbnail')

    @unittest.skipUnless(ffmpeg_executable(), 'ffmpeg not available')
    def test_frame_poster_is_replaced_by_a_real_cover_later(self):
        movie = self.base / 'real.mp4'
        done = subprocess.run([ffmpeg_executable(), '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=64x48:rate=5', '-t', '2',
                               '-pix_fmt', 'yuv420p', str(movie)], capture_output=True)
        if done.returncode:
            self.skipTest('ffmpeg cannot synthesize a test video')
        task = self.work(video=movie.read_bytes())
        first = self.export(task).json()
        self.assertEqual(first['cover_source'], 'frame')
        self.assertTrue((Path(first['folder']) / 'poster.jpg').is_file())
        self.cache_cover(task['url'], png(30, 40), '.png')
        later = self.export(task).json()
        self.assertEqual(later['cover_source'], 'cache')
        self.assertEqual(sorted(p.name for p in Path(later['folder']).glob('poster.*')), ['poster.png'])

    def test_title_change_moves_the_managed_files(self):
        task = self.work()
        old = Path(self.export(task).json()['folder'])
        with self.app.state.store.connect() as db:
            row = db.execute('SELECT config FROM subscriptions').fetchall()
        self.assertEqual(row, [])
        with self.app.state.store.connect() as db:
            db.execute('UPDATE tasks SET author=? WHERE id=?', ('新作者', task['id']))
        new = Path(self.export(task).json()['folder'])
        self.assertNotEqual(old, new)
        self.assertFalse(old.exists())
        self.assertFalse(old.parent.exists())                        # emptied author folder is removed
        self.assertTrue((new / '今天的穿搭 [769].mp4').is_file())

    def test_deleting_a_task_removes_its_folder_only_when_asked(self):
        task = self.work()
        folder = Path(self.export(task).json()['folder'])
        (folder / 'my-notes.txt').write_text('keep me')
        self.assertEqual(self.client.delete(f"/api/tasks/{task['id']}").status_code, 200)
        self.assertTrue((folder / '今天的穿搭 [769].mp4').is_file())
        other = self.work(name='other [8].mp4', title='另一个')
        folder2 = Path(self.export(other).json()['folder'])
        self.enable(delete_with_work=True)
        self.assertEqual(self.client.delete(f"/api/tasks/{other['id']}").status_code, 200)
        self.assertFalse(folder2.exists())

    def test_batch_export_reports_progress(self):
        for n in range(3):
            self.work(name=f'v{n} [{n}].mp4', title=f'作品{n}')
        self.work(name='pic [9].jpg', video=png(4, 4), title='图')
        self.assertEqual(self.client.get('/api/library/export/progress').json()['state'], 'idle')
        with self.client:                                   # one event loop for the whole job
            started = self.client.post('/api/library/export')
            self.assertEqual(started.status_code, 200, started.text)
            import time
            for _ in range(100):
                state = self.client.get('/api/library/export/progress').json()
                if state['state'] == 'done':
                    break
                time.sleep(0.05)
            self.assertEqual(state['state'], 'done')
            self.assertEqual((state['total'], state['exported'], state['galleries'], state['failed']), (4, 3, 1, 0))
            self.assertEqual(len(list(self.library.glob('*/*/.harbor.json'))), 3)
            self.assertEqual(self.client.post('/api/library/export').status_code, 200)         # a finished job can be run again

    def test_auto_export_after_download_when_enabled(self):
        self.enable(auto=True)
        manager = self.app.state.manager
        task = self.work()
        import asyncio

        async def finish():
            manager.on_completed(task['id'])
            for _ in range(100):
                if list(self.library.glob('*/*/.harbor.json')):
                    break
                await asyncio.sleep(0.05)
        asyncio.run(finish())
        self.assertEqual(len(list(self.library.glob('*/*/.harbor.json'))), 1)

    def test_auth_required(self):
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post('/api/library/export').status_code, 401)
        self.assertEqual(self.client.get('/api/library/export/progress').status_code, 401)


if __name__ == '__main__':
    unittest.main()
