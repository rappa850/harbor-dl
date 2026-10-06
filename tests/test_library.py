import io
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.imagesize import image_ratio, image_size


def png(w, h):
    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IEND', b'')


def gif(w, h):
    return b'GIF89a' + struct.pack('<HH', w, h) + b'\x00\x00\x00;'


def jpeg(w, h):
    return b'\xff\xd8' + b'\xff\xe0\x00\x04ab' + b'\xff\xc0\x00\x0b\x08' + struct.pack('>HH', h, w) + b'\x01\x01\x11\x00' + b'\xff\xd9'


def webp_extended(w, h):
    return b'RIFF' + struct.pack('<I', 22) + b'WEBPVP8X' + struct.pack('<I', 10) + b'\x00\x00\x00\x00' + (w - 1).to_bytes(3, 'little') + (h - 1).to_bytes(3, 'little')


def webp_lossless(w, h):
    bits = (w - 1) | ((h - 1) << 14)
    return b'RIFF' + struct.pack('<I', 17) + b'WEBPVP8L' + struct.pack('<I', 5) + b'\x2f' + bits.to_bytes(4, 'little')


class ImageSizeTests(unittest.TestCase):
    def test_reads_each_format(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, data in (('a.png', png(300, 400)), ('a.gif', gif(300, 400)), ('a.jpg', jpeg(300, 400)),
                               ('a.webp', webp_extended(300, 400)), ('b.webp', webp_lossless(300, 400))):
                path = Path(folder) / name
                path.write_bytes(data)
                self.assertEqual(image_size(path), (300, 400), name)
            self.assertEqual(image_ratio(Path(folder) / 'a.png'), 0.75)

    def test_unknown_or_missing_files_have_no_size(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.mp4'
            path.write_bytes(b'not an image')
            self.assertIsNone(image_size(path))
            self.assertIsNone(image_size(Path(folder) / 'missing.png'))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = TestClient(self.app)
        self.client.post('/api/setup', json={'username': 'admin', 'password': 'test-password-123'})

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def post(self):
        manager = self.app.state.manager
        task = manager.create('https://example.org/note/1', '图集')
        folder = manager.root / task['id']
        folder.mkdir()
        (folder / 'p_01.png').write_bytes(png(900, 1200))
        (folder / 'p_02.png').write_bytes(png(1200, 900))
        (folder / 'p_bgm.mp3').write_bytes(b'ID3music')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path=? WHERE id=?", (f"{task['id']}/p_01.png", task['id']))
            manager.assets.register(db, dict(db.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone()))
        return task

    def test_files_report_picture_ratio(self):
        self.post()
        items = {i['name']: i for i in self.client.get('/api/files').json()['items']}
        self.assertEqual(items['p_01.png']['ratio'], 0.75)
        self.assertEqual(items['p_02.png']['ratio'], 1.3333)
        self.assertIsNone(items['p_bgm.mp3']['ratio'])

    def test_archive_bundles_the_whole_post(self):
        self.post()
        first = next(i for i in self.client.get('/api/files').json()['items'] if i['name'] == 'p_02.png')
        response = self.client.get(f"/api/files/{first['id']}/archive")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'application/zip')
        self.assertEqual(sorted(zipfile.ZipFile(io.BytesIO(response.content)).namelist()), ['p_01.png', 'p_02.png', 'p_bgm.mp3'])
        self.assertEqual(self.client.get('/api/files/missing/archive').status_code, 404)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get(f"/api/files/{first['id']}/archive").status_code, 401)


if __name__ == '__main__':
    unittest.main()
