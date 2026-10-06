import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from .store import Store
from .network import NetworkConfig, redact
from .assets import Assets


def now():
    return datetime.now(timezone.utc).isoformat()


class DownloadManager:
    def __init__(self, store: Store, root: Path, command_builder=None):
        self.store, self.root = store, root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets = Assets(store, self.root)
        self.assets.backfill()
        self.command_builder = command_builder or self.command
        self.running = {}
        self.resolvers = {}   # task source -> async (task, network) -> direct download target or None
        self.processes = {}
        self.wake = asyncio.Event()
        self.stopping = False
        self.loop_task = None

    def command(self, task, folder):
        return [sys.executable, '-X', 'utf8', '-u', '-m', 'backend.download_worker']

    async def terminate(self, process):
        if process.returncode is not None:
            return
        try:
            if os.name == 'nt':
                killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F',
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                if os.name != 'nt':
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                await process.wait()
        except ProcessLookupError:
            pass

    def processing(self, task_id):
        with self.store.connect() as db:
            changed = db.execute('UPDATE tasks SET status="PROCESSING",speed="",updated_at=? '
                                 'WHERE id=? AND status="DOWNLOADING"', (now(), task_id)).rowcount
            if changed:
                self.event(db, task_id, 'PROCESSING', '正在合并或整理媒体文件')

    def event(self, db, task_id, status, message):
        db.execute('INSERT INTO task_events(task_id,status,message,created_at) VALUES (?,?,?,?)',
                   (task_id, status, message, now()))
        if status == 'COMPLETED':
            db.execute('UPDATE subscription_videos SET downloaded=1,error_message=NULL,'
                       'download_file_path=(SELECT file_path FROM tasks WHERE id=?),updated_at=? WHERE download_task_id=?',
                       (task_id,now(),task_id))
        elif status == 'ERROR':
            db.execute('UPDATE subscription_videos SET downloaded=0,error_message=?,updated_at=? WHERE download_task_id=?',
                       (message,now(),task_id))
        elif status in ('PENDING','CANCELLED'):
            db.execute('UPDATE subscription_videos SET downloaded=0,error_message=NULL,updated_at=? WHERE download_task_id=?',
                       (now(),task_id))

    def create(self, url, title='', format_id='bestvideo+bestaudio/best', subtitles=True, thumbnail=True, source='universal', author='',subscription_id=None,db=None):
        task_id, timestamp = str(uuid.uuid4()), now()
        owns_connection=db is None
        with self.store.connect() if owns_connection else nullcontext(db) as connection:
            connection.execute('INSERT INTO tasks(id,url,title,status,created_at,updated_at,format_id,subtitles,thumbnail,source,author,subscription_id) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                       (task_id, url, title or url, 'PENDING', timestamp, timestamp, format_id, int(subtitles), int(thumbnail), source, author,subscription_id))
            self.event(connection, task_id, 'PENDING', '任务已加入队列')
            result=dict(connection.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone())
        if owns_connection:self.wake.set()
        return result

    def get(self, task_id):
        return self.store.one('SELECT * FROM tasks WHERE id=?', (task_id,))

    def update(self, task_id, **fields):
        allowed = {'title','progress','downloaded','total','speed','error','file_path'}
        if not fields or not fields.keys() <= allowed:
            raise ValueError('Invalid task update')
        fields['updated_at'] = now()
        with self.store.connect() as db:
            db.execute('UPDATE tasks SET ' + ','.join(f'{key}=?' for key in fields) +
                       ' WHERE id=? AND status IN ("DOWNLOADING","PROCESSING")', (*fields.values(), task_id))

    async def start(self):
        with self.store.connect() as db:
            interrupted = db.execute('SELECT id FROM tasks WHERE status IN ("DOWNLOADING","PROCESSING")').fetchall()
            for row in interrupted:
                db.execute('UPDATE tasks SET status=?,error=?,speed="",updated_at=? WHERE id=?',
                           ('ERROR', '服务上次退出时任务尚未完成，请重试', now(), row['id']))
                self.event(db, row['id'], 'ERROR', '服务中断，任务等待手动重试')
        self.loop_task = asyncio.create_task(self.schedule())

    async def stop(self):
        self.stopping = True
        self.wake.set()
        if self.loop_task:
            await self.loop_task
        for process in list(self.processes.values()):
            if process.returncode is None:
                await self.terminate(process)
        if self.running:
            await asyncio.gather(*list(self.running.values()), return_exceptions=True)

    async def schedule(self):
        while not self.stopping:
            # Clear before observing state so notifications during a DB read are retained.
            self.wake.clear()
            limit = int(self.store.one('SELECT value FROM settings WHERE key="concurrency"')['value'])
            available = max(0, limit - len(self.running))
            queued = self.store.all('SELECT * FROM tasks WHERE status="PENDING" ORDER BY created_at LIMIT ?',
                                    (available,))
            for task in queued:
                task_id = task['id']
                if task_id in self.running:
                    continue
                self.running[task_id] = asyncio.create_task(self.run(task))
            await self.wake.wait()

    async def run(self, task):
        task_id = task['id']
        folder = self.root / task_id
        network = NetworkConfig(self.store).for_url(task['url'])
        try:
            with self.store.connect() as db:
                changed = db.execute('UPDATE tasks SET status="DOWNLOADING",updated_at=? WHERE id=? AND status="PENDING"',
                                     (now(), task_id)).rowcount
                if not changed:
                    return
                self.event(db, task_id, 'DOWNLOADING', '下载开始')
            folder.mkdir(exist_ok=True)
            direct = None
            resolver = self.resolvers.get(task['source'])
            if resolver and not self.stopping and self.get(task_id)['status'] != 'CANCELLED':
                direct = await resolver(task, network)
            process = await asyncio.create_subprocess_exec(*self.command_builder(task, folder),
                         stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                         cwd=Path(__file__).resolve().parents[1],
                         **({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}),
                         limit=1024 * 1024)
            self.processes[task_id] = process
            if self.command_builder == self.command:
                process.stdin.write(json.dumps({**task, 'network': network, 'output_folder': str(folder), 'direct': direct}, ensure_ascii=False).encode('utf-8'))
                await process.stdin.drain()
            process.stdin.close()
            current = self.get(task_id)
            if self.stopping or current['status'] == 'CANCELLED':
                if process.returncode is None:
                    await self.terminate(process)
            errors = []
            output_file = None
            async for raw in process.stdout:
                line = raw.decode('utf-8', 'replace').strip()
                if line.startswith('harbor-progress:'):
                    try:
                        progress = json.loads(line.partition(':')[2])
                        downloaded = int(progress.get('downloaded_bytes') or 0)
                        total = int(progress.get('total_bytes') or progress.get('total_bytes_estimate') or 0)
                        self.update(task_id, downloaded=downloaded, total=total,
                                    progress=min(99.9, downloaded / total * 100) if total else 0,
                                    speed=str(progress.get('_speed_str') or '').strip())
                    except (ValueError, TypeError, json.JSONDecodeError):
                        pass
                elif line.startswith('harbor-title:'):
                    try:
                        self.update(task_id, title=str(json.loads(line.partition(':')[2])))
                    except json.JSONDecodeError:
                        pass
                elif line.startswith('harbor-file:'):
                    try:
                        candidate = Path(json.loads(line.partition(':')[2])).resolve()
                        if candidate.is_relative_to(folder.resolve()) and candidate.is_file():
                            output_file = candidate
                    except (ValueError, TypeError, json.JSONDecodeError):
                        pass
                elif line.startswith('harbor-processing:'):
                    self.processing(task_id)
                elif line:
                    errors.append(redact(line, network)[:1000])
                    errors = errors[-8:]
            code = await process.wait()
            current = self.get(task_id)
            if current['status'] == 'CANCELLED':
                shutil.rmtree(folder, ignore_errors=True)
                return
            if self.stopping:
                raise RuntimeError('服务停止时任务尚未完成，请重试')
            if code or output_file is None:
                raise RuntimeError('\n'.join(errors) or f'下载器退出码 {code}，未获得完整媒体文件')
            size = output_file.stat().st_size
            with self.store.connect() as db:
                changed = db.execute('UPDATE tasks SET status="COMPLETED",progress=100,downloaded=?,total=?,speed="",'
                                    'file_path=?,updated_at=? WHERE id=? AND status IN ("DOWNLOADING","PROCESSING")',
                                    (size, size, output_file.relative_to(self.root).as_posix(), now(), task_id)).rowcount
                if changed:
                    completed = dict(db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())
                    self.assets.register(db, completed)
                    self.event(db, task_id, 'COMPLETED', '下载完成，媒体文件可用')
        except Exception as exc:
            with self.store.connect() as db:
                changed = db.execute('UPDATE tasks SET status=?,error=?,speed="",updated_at=? '
                                     'WHERE id=? AND status IN ("DOWNLOADING","PROCESSING")', ('ERROR', redact(exc, network)[-4000:], now(), task_id)).rowcount
                if changed:
                    self.event(db, task_id, 'ERROR', redact(exc, network)[-2000:])
        finally:
            process = self.processes.get(task_id)
            if process and process.returncode is None:
                await self.terminate(process)
            self.processes.pop(task_id, None)
            self.running.pop(task_id, None)
            self.wake.set()

    async def cancel(self, task_id):
        with self.store.connect() as db:
            changed = db.execute('UPDATE tasks SET status="CANCELLED",speed="",updated_at=? '
                                 'WHERE id=? AND status IN ("PENDING","DOWNLOADING","PROCESSING")', (now(), task_id)).rowcount
            if not changed:
                return False
            self.event(db, task_id, 'CANCELLED', '用户取消下载')
        process = self.processes.get(task_id)
        if process and process.returncode is None:
            await self.terminate(process)
        self.wake.set()
        return True

    def retry(self, task_id):
        if task_id in self.running:
            return False
        with self.store.connect() as db:
            changed = db.execute('UPDATE tasks SET status="PENDING",error="",progress=0,downloaded=0,total=0,'
                                 'speed="",file_path=NULL,updated_at=? WHERE id=? AND status IN (?,?)',
                                 (now(), task_id, 'ERROR', 'CANCELLED')).rowcount
            if changed:
                self.event(db, task_id, 'PENDING', '用户重新提交任务')
        if changed:
            self.wake.set()
        return bool(changed)
