import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from backend.downloads import DownloadManager
from backend.store import Store

WORKER = Path(__file__).parent / 'fixtures/task_worker.py'


async def until(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def process_running(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    status = Path(f'/proc/{pid}/stat')
    if status.exists():
        return status.read_text().split(') ', 1)[1][:1] != 'Z'
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class TaskLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'test.sqlite')
        self.manager = DownloadManager(self.store, self.root / 'downloads',
            lambda task, folder: [sys.executable, '-X', 'utf8', '-u', str(WORKER), str(folder), 'normal'])

    async def asyncTearDown(self):
        await self.manager.stop()
        self.temp.cleanup()

    async def test_processing_success_has_ordered_events(self):
        task = self.manager.create('https://example.org/video')
        await self.manager.start()
        await until(lambda: self.manager.get(task['id'])['status'] == 'PROCESSING')
        (self.manager.root / task['id'] / 'release').touch()
        await until(lambda: self.manager.get(task['id'])['status'] == 'COMPLETED')
        events = self.store.all('SELECT status FROM task_events WHERE task_id=? ORDER BY id', (task['id'],))
        self.assertEqual([e['status'] for e in events], ['PENDING', 'DOWNLOADING', 'PROCESSING', 'COMPLETED'])

    async def test_cancel_processing_stops_child_and_prevents_completion(self):
        self.manager.command_builder = lambda task, folder: [sys.executable, '-X', 'utf8', '-u', str(WORKER), str(folder), 'tree']
        task = self.manager.create('https://example.org/video')
        await self.manager.start()
        await until(lambda: self.manager.get(task['id'])['status'] == 'PROCESSING')
        child = int((self.manager.root / task['id'] / 'child.pid').read_text())
        self.assertTrue(process_running(child))
        self.assertTrue(await self.manager.cancel(task['id']))
        await until(lambda: task['id'] not in self.manager.running)
        await until(lambda: not process_running(child))
        self.assertEqual(self.manager.get(task['id'])['status'], 'CANCELLED')
        self.assertFalse(await self.manager.cancel(task['id']))
        self.assertTrue(self.manager.retry(task['id']))
        # Pending cancellation is atomic even if scheduler is about to pick it.
        self.assertTrue(await self.manager.cancel(task['id']))

    async def test_processing_failure_and_retry_options(self):
        self.manager.command_builder = lambda task, folder: [sys.executable, '-X', 'utf8', '-u', str(WORKER), str(folder), 'error']
        task = self.manager.create('https://example.org/video', format_id='v+a', subtitles=False)
        await self.manager.start()
        await until(lambda: self.manager.get(task['id'])['status'] == 'ERROR')
        await until(lambda: task['id'] not in self.manager.running)
        self.assertIn('测试后处理失败', self.manager.get(task['id'])['error'])
        self.assertTrue(self.manager.retry(task['id']))
        self.assertEqual(self.manager.get(task['id'])['format_id'], 'v+a')
        self.assertEqual(self.manager.get(task['id'])['subtitles'], 0)
        await self.manager.cancel(task['id'])

    async def test_restart_marks_both_interrupted_phases(self):
        ids = []
        for status in ('DOWNLOADING', 'PROCESSING'):
            task = self.manager.create('https://example.org/video')
            ids.append(task['id'])
            with self.store.connect() as db:
                db.execute('UPDATE tasks SET status=? WHERE id=?', (status, task['id']))
        await self.manager.start()
        self.assertEqual([self.manager.get(i)['status'] for i in ids], ['ERROR', 'ERROR'])
        self.assertTrue(all('重试' in self.manager.get(i)['error'] for i in ids))

    async def test_concurrency_and_cancel_wakes_next_task(self):
        with self.store.connect() as db:
            db.execute("UPDATE settings SET value='1' WHERE key='concurrency'")
        first = self.manager.create('https://example.org/one')
        second = self.manager.create('https://example.org/two')
        await self.manager.start()
        await until(lambda: self.manager.get(first['id'])['status'] == 'PROCESSING')
        self.assertEqual(self.manager.get(second['id'])['status'], 'PENDING')
        await self.manager.cancel(first['id'])
        await until(lambda: self.manager.get(second['id'])['status'] == 'PROCESSING')
        self.assertEqual(len(self.manager.running), 1)
        await self.manager.cancel(second['id'])

    async def test_shutdown_stops_active_worker(self):
        task = self.manager.create('https://example.org/video')
        await self.manager.start()
        await until(lambda: self.manager.get(task['id'])['status'] == 'PROCESSING')
        process = self.manager.processes[task['id']]
        await self.manager.stop()
        self.assertIsNotNone(process.returncode)
        self.assertEqual(self.manager.get(task['id'])['status'], 'ERROR')
