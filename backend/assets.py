"""Keep media discoverable independently of a download task's lifetime."""
import uuid
from pathlib import Path

KINDS = {'video': {'.mp4', '.mkv', '.webm', '.mov', '.flv', '.ts', '.m4v'},
         'audio': {'.mp3', '.flac', '.m4a', '.wav', '.aac', '.ogg', '.opus'},
         'image': {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif'}}


def kind(path):
    return next((name for name, extensions in KINDS.items() if Path(path).suffix.lower() in extensions), 'attachment')


class Assets:
    def __init__(self, store, root):
        self.store, self.root = store, root.resolve()

    def path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError('媒体文件不存在或路径无效')
        return path

    def register(self, db, task):
        folder = (self.root / task['id']).resolve()
        if not folder.is_relative_to(self.root):
            raise ValueError('任务目录无效')
        for candidate in folder.rglob('*'):
            if not candidate.is_file() or candidate.is_symlink() or candidate.suffix in ('.part', '.ytdl'):
                continue
            path = candidate.resolve()
            if not path.is_relative_to(folder):
                continue
            relative = path.relative_to(self.root).as_posix()
            primary = relative == task['file_path']
            db.execute('INSERT INTO media_assets(id,path,task_id,title,kind,is_primary,created_at) '
                       'VALUES (?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET task_id=excluded.task_id,'
                       'title=excluded.title,is_primary=excluded.is_primary',
                       (str(uuid.uuid4()), relative, task['id'], task['title'] if primary else path.name,
                        kind(path), int(primary), task['updated_at']))

    def backfill(self):
        with self.store.connect() as db:
            for task in db.execute("SELECT * FROM tasks WHERE status='COMPLETED' AND file_path IS NOT NULL").fetchall():
                self.register(db, dict(task))

    def get(self, asset_id):
        return self.store.one('SELECT * FROM media_assets WHERE id=? OR (task_id=? AND is_primary=1) '
                              'ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END LIMIT 1', (asset_id, asset_id, asset_id))

    def items(self, attachments=False):
        result = []
        for asset in self.store.all('SELECT * FROM media_assets ORDER BY created_at DESC,path'):
            try:
                path = self.path(asset['path'])
            except ValueError:
                continue
            if asset['kind'] == 'attachment' and not attachments:
                continue
            result.append({**asset, 'name': path.name, 'size': path.stat().st_size, 'extension': path.suffix.lower()})
        return result
