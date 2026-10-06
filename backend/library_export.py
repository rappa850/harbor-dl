"""Media-server library: every video gets its own folder (video + poster + NFO + .harbor.json) under a library root.

The download tree (<downloads>/<task id>/) is not touched. Videos are hard-linked into the library (copied across disks),
so the library folder is the unit for cloud backup and disaster recovery: .harbor.json says what each folder is."""
import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from .downloads import now
from .library_covers import PosterResolver, existing
from .library_names import clean_name, platform_label, split_description
from .library_nfo import build_movie_nfo

SUBTITLES = {'.vtt', '.srt', '.ass', '.ssa'}
MANIFEST = '.harbor.json'
SCHEMA = 1


class Skipped(Exception):
    pass


class LibraryError(Exception):
    pass


def atomic_write(path, data):
    path = Path(path)
    handle, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as out:
            out.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def link_or_copy(source, target):
    """'kept' when the target already is this file, 'linked' for a hard link, 'copied' across disks."""
    source, target = Path(source), Path(target)
    if target.exists():
        try:
            if os.path.samefile(source, target):
                return 'kept'
        except OSError:
            pass
        a, b = source.stat(), target.stat()
        if a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns:
            return 'kept'
        target.unlink()
    try:
        os.link(source, target)
        return 'linked'
    except OSError:
        tmp = target.with_name(f'.{target.name}.{os.getpid()}.tmp')
        try:
            shutil.copy2(source, tmp)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        return 'copied'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class LibraryExporter:
    def __init__(self, store, manager, cache, ffmpeg, default_root, network=None):
        self.store, self.manager, self.cache = store, manager, cache
        self.default_root = Path(default_root)
        self.posters = PosterResolver(cache, ffmpeg)
        self.network = network
        self.job = None
        self.state = {'state': 'idle'}
        self.tasks = set()

    # --- settings -------------------------------------------------------------------------------------------------
    def value(self, key, default=''):
        row = self.store.one('SELECT value FROM settings WHERE key=?', (key,))
        return row['value'] if row else default

    def put(self, key, value):
        with self.store.connect() as db:
            db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))

    def config(self):
        root = self.value('library_root') or str(self.default_root)
        return {'enabled': self.value('library_enabled', '0') == '1', 'auto': self.value('library_auto', '1') == '1',
                'delete_with_work': self.value('library_delete_with_work', '0') == '1',
                'root': root, 'default_root': str(self.default_root)}

    def net(self, url):
        return self.network.for_url(url) if self.network and url else None

    def root(self):
        return Path(self.config()['root'])

    def check_root(self, text):
        """Validate and create the library root; returns the resolved path."""
        path = Path(text or self.default_root)
        if not path.is_absolute():
            raise LibraryError('媒体库目录必须是绝对路径')
        path = path.resolve()
        for guarded, name in ((self.manager.root, '下载目录'), (self.cache.root, '封面缓存目录')):
            if path == guarded or path.is_relative_to(guarded) or guarded.is_relative_to(path):
                raise LibraryError(f'媒体库目录不能与{name}重叠')
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / f'.harbor-write-test-{os.getpid()}'
            probe.write_text('ok')
            probe.unlink()
        except OSError as exc:
            raise LibraryError(f'媒体库目录不可写：{exc.strerror or exc}') from exc
        return path

    # --- one work ------------------------------------------------------------------------------------------------
    def context(self, task_id):
        task = self.store.one('SELECT * FROM tasks WHERE id=?', (task_id,))
        if not task:
            raise Skipped('任务不存在')
        if task['status'] != 'COMPLETED' or not task['file_path']:
            raise Skipped('任务尚未完成')
        assets = self.store.all('SELECT path,kind,is_primary FROM media_assets WHERE task_id=? ORDER BY path', (task_id,))
        primary = next((a for a in assets if a['path'] == task['file_path']), None)
        if primary is None or primary['kind'] == 'image':
            raise Skipped('图集作品不导出到媒体库')
        if primary['kind'] != 'video':
            raise Skipped('仅导出视频作品')
        try:
            video = self.manager.assets.path(task['file_path'])
        except ValueError as exc:
            raise Skipped('媒体文件已不存在') from exc
        row = self.store.one('SELECT video_id,metadata FROM subscription_videos WHERE download_task_id=?', (task_id,))
        meta = json.loads(row['metadata']) if row else {}
        sub = {}
        if task['subscription_id']:
            found = self.store.one('SELECT config FROM subscriptions WHERE id=?', (task['subscription_id'],))
            sub = json.loads(found['config']) if found else {}
        platform = sub.get('platform') or task['source'] or 'universal'
        match = re.search(r'\[([^\[\]]+)\]\.[^.]+$', video.name)
        work_id = (row['video_id'] if row else None) or (match[1] if match else task_id[:8])
        title, plot, tags = split_description(meta.get('description') or meta.get('title') or task['title'], work_id)
        stamp = meta.get('publish_time') or ''
        return {
            'task': task, 'video': video, 'platform': platform, 'work_id': str(work_id), 'title': title, 'plot': plot, 'tags': tags,
            'author': sub.get('nickname') or task['author'] or platform_label(platform), 'avatar_url': sub.get('avatar_url'),
            'author_id': sub.get('user_id'), 'premiered': stamp[:10] if re.match(r'\d{4}-\d{2}-\d{2}', stamp) else '',
            'duration': meta.get('duration'), 'cover_url': meta.get('cover_url'), 'source_url': task['url'],
            'thumbnails': [self.manager.root / a['path'] for a in assets if a['kind'] == 'image'],
            'subtitles': [self.manager.root / a['path'] for a in assets if Path(a['path']).suffix.lower() in SUBTITLES]}

    def folder_for(self, ctx, root):
        author = clean_name(ctx['author'], 80, '未知作者')
        name = clean_name(f"{ctx['title']} [{ctx['work_id']}]", 120, ctx['work_id'])
        return root / author, root / author / name, clean_name(f"{ctx['title']} [{ctx['work_id']}]", 110, ctx['work_id'])

    def read_manifest(self, folder):
        try:
            return json.loads((Path(folder) / MANIFEST).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    async def export_task(self, task_id, overwrite=False):
        """Returns {'status': 'exported'|'unchanged', 'folder', 'cover_source', ...}; raises Skipped or LibraryError."""
        ctx = await asyncio.to_thread(self.context, task_id)
        root = self.check_root(self.config()['root'])
        author_dir, folder, stem = self.folder_for(ctx, root)
        previous = self.store.one('SELECT folder FROM library_exports WHERE task_id=?', (task_id,))
        if previous and Path(previous['folder']) != folder:
            await asyncio.to_thread(self.remove_folder, previous['folder'])     # title or author changed: move the managed files
        folder.mkdir(parents=True, exist_ok=True)
        old = self.read_manifest(folder)
        changed = []

        ext = ctx['video'].suffix.lower()
        how = await asyncio.to_thread(link_or_copy, ctx['video'], folder / f'{stem}{ext}')
        files = [{'name': f'{stem}{ext}', 'role': 'video'}]
        changed += [] if how == 'kept' else [how]
        for sub in ctx['subtitles']:
            tail = sub.name[len(ctx['video'].stem):] if sub.name.startswith(ctx['video'].stem) else f'.{sub.suffix.lstrip(".")}'
            await asyncio.to_thread(link_or_copy, sub, folder / f'{stem}{tail}')
            files.append({'name': f'{stem}{tail}', 'role': 'subtitle'})

        poster, source = await self.posters.poster(
            folder, work_url=ctx['source_url'], cover_url=ctx['cover_url'], thumbnails=ctx['thumbnails'], video=ctx['video'],
            duration=ctx['duration'], network=self.net(ctx['cover_url']), previous=old.get('cover_source'))
        if poster:
            files.append({'name': poster, 'role': 'poster'})
        if ctx['avatar_url']:
            author_dir.mkdir(parents=True, exist_ok=True)
            await self.posters.avatar(author_dir, ctx['avatar_url'], self.net(ctx['avatar_url']))

        data = build_movie_nfo({
            'title': ctx['title'], 'original_title': ctx['plot'] and ctx['plot'].splitlines()[0][:200] or ctx['title'], 'plot': ctx['plot'],
            'premiered': ctx['premiered'], 'dateadded': (ctx['task']['updated_at'] or now()).replace('T', ' ')[:19],
            'runtime_minutes': -(-int(ctx['duration']) // 60) if ctx['duration'] else None, 'duration_seconds': ctx['duration'],
            'author': ctx['author'], 'platform': ctx['platform'], 'platform_name': platform_label(ctx['platform']),
            'work_id': ctx['work_id'], 'source_url': ctx['source_url'], 'tags': ctx['tags'], 'poster': poster}).encode('utf-8')
        nfo_path = folder / f'{stem}.nfo'
        digest, kept, edited = sha(data), False, False
        if nfo_path.exists():
            current = sha(nfo_path.read_bytes())
            if current == digest:
                kept = True
            elif current != old.get('nfo_sha256') and not overwrite:
                digest, kept, edited = old.get('nfo_sha256') or current, True, True      # edited by hand: leave it alone
        if not kept:
            await asyncio.to_thread(atomic_write, nfo_path, data)
            changed.append('nfo')
        files.append({'name': nfo_path.name, 'role': 'nfo'})

        manifest = {'schema': SCHEMA, 'platform': ctx['platform'], 'work_id': ctx['work_id'], 'source_url': ctx['source_url'],
                    'author': {'id': ctx['author_id'], 'nickname': ctx['author']}, 'task_id': task_id, 'title': ctx['title'],
                    'exported_at': now(), 'files': files, 'nfo_sha256': digest, 'cover_source': source}
        await asyncio.to_thread(atomic_write, folder / MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
        with self.store.connect() as db:
            db.execute('INSERT INTO library_exports(task_id,folder,cover_source,exported_at) VALUES (?,?,?,?) '
                       'ON CONFLICT(task_id) DO UPDATE SET folder=excluded.folder,cover_source=excluded.cover_source,exported_at=excluded.exported_at',
                       (task_id, str(folder), source, now()))
        return {'status': 'exported' if changed or not old else 'unchanged', 'folder': str(folder), 'cover_source': source,
                'nfo_kept': edited}

    # --- removal --------------------------------------------------------------------------------------------------
    def remove_folder(self, folder):
        """Delete only what the manifest lists, then the folder (and its author folder) when nothing else is inside."""
        folder = Path(folder)
        manifest = self.read_manifest(folder)
        for entry in manifest.get('files', []):
            (folder / entry['name']).unlink(missing_ok=True)
        (folder / MANIFEST).unlink(missing_ok=True)
        for directory in (folder, folder.parent):
            try:
                directory.rmdir()
            except OSError:
                break

    def nfo_path(self, task_id):
        """The NFO this work has in the media library, or None when it was not exported (or the file is gone)."""
        row = self.store.one('SELECT folder FROM library_exports WHERE task_id=?', (task_id,))
        if not row:
            return None
        folder = Path(row['folder'])
        stem = next((f['name'] for f in self.read_manifest(folder).get('files', []) if f.get('role') == 'nfo'), None)
        path = folder / stem if stem else None
        return path if path and path.is_file() else None

    def forget(self, task_id):
        """Called when a task is deleted: removes the library folder when 'delete with work' is on."""
        row = self.store.one('SELECT folder FROM library_exports WHERE task_id=?', (task_id,))
        if not row:
            return
        if self.config()['delete_with_work']:
            self.remove_folder(row['folder'])
        with self.store.connect() as db:
            db.execute('DELETE FROM library_exports WHERE task_id=?', (task_id,))

    # --- automatic and batch --------------------------------------------------------------------------------------
    def completed(self, task_id):
        """Download manager hook."""
        config = self.config()
        if not (config['enabled'] and config['auto']):
            return

        async def run():
            try:
                await self.export_task(task_id)
            except (Skipped, LibraryError, OSError) as exc:
                with self.store.connect() as db:
                    self.manager.event(db, task_id, 'LIBRARY', f'媒体库导出未完成：{exc}')
        task = asyncio.get_running_loop().create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def progress(self):
        return dict(self.state)

    def start_all(self, overwrite=False):
        if self.job and not self.job.done():
            raise LibraryError('批量导出正在进行')
        self.check_root(self.config()['root'])
        ids = [r['id'] for r in self.store.all("SELECT id FROM tasks WHERE status='COMPLETED' AND file_path IS NOT NULL ORDER BY updated_at")]
        self.state = {'state': 'running', 'total': len(ids), 'done': 0, 'exported': 0, 'unchanged': 0, 'skipped': 0, 'galleries': 0,
                      'failed': 0, 'frames': 0, 'no_cover': 0, 'errors': [], 'started_at': now()}
        self.job = asyncio.get_running_loop().create_task(self.run_all(ids, overwrite))

    async def run_all(self, ids, overwrite):
        state = self.state
        for task_id in ids:
            try:
                result = await self.export_task(task_id, overwrite)
                state[result['status']] += 1
                state['frames'] += result['cover_source'] == 'frame'
                state['no_cover'] += result['cover_source'] is None
            except Skipped as exc:
                state['galleries' if '图集' in str(exc) else 'skipped'] += 1
            except (LibraryError, OSError, ValueError) as exc:
                state['failed'] += 1
                state['errors'] = [*state['errors'][-9:], f'{task_id[:8]}：{exc}']
            state['done'] += 1
            await asyncio.sleep(0)
        state['state'] = 'done'
        state['finished_at'] = now()

    async def close(self):
        for task in [self.job, *self.tasks]:
            if task and not task.done():
                task.cancel()
