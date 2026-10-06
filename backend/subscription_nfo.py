"""Inspect and edit existing NFO sidecar files; automatic NFO generation is not implemented."""
import hashlib
import os
import tempfile
import uuid
from pydantic import BaseModel,Field
from .downloads import now
from .subscription_downloads import video_state
from .subscription_cleanup import is_link

MAX_BYTES=1024*1024


class NfoConflict(Exception):pass


class NfoInput(BaseModel):
    content: str=Field(max_length=MAX_BYTES)
    expected_etag: str | None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    expected_task_id: str | None=Field(default=None,max_length=128)


class SubscriptionNfo:
    def __init__(self,store,manager):self.store,self.manager=store,manager

    def locate(self,db,subscription_id,video_id):
        subscription_id,video_id=str(subscription_id),str(video_id)
        if not db.execute('SELECT id FROM subscriptions WHERE id=?',(subscription_id,)).fetchone():
            raise LookupError('订阅不存在')
        row=db.execute('SELECT v.*,t.status AS task_status,t.file_path AS task_file_path,t.error AS task_error,t.subscription_id AS task_subscription_id '
                       'FROM subscription_videos v LEFT JOIN tasks t ON t.id=v.download_task_id '
                       'WHERE v.subscription_id=? AND v.id=?',(subscription_id,video_id)).fetchone()
        if row is None:raise LookupError('作品不存在')
        if video_state(row,self.manager.assets)['status']!='downloaded' or not row['download_task_id']:
            raise NfoConflict('仅已下载且有任务关联的作品支持编辑 NFO')
        if row['download_task_id'] in self.manager.running:raise NfoConflict('下载器尚未结束，请稍后编辑 NFO')
        if row['task_status'] is not None and row['task_subscription_id']!=subscription_id:
            raise ValueError('任务不属于此订阅，无法编辑 NFO')
        media=self.manager.assets.path(row['task_file_path'] or row['download_file_path'])
        directory=self.manager.root/row['download_task_id']
        if is_link(directory):raise ValueError('任务目录为链接，无法编辑 NFO')
        expected=directory.resolve()
        if expected.parent!=self.manager.root or expected.name!=row['download_task_id'] or media.parent!=expected:
            raise ValueError('作品文件不在所属任务目录，无法定位 NFO')
        nfo=media.with_suffix('.nfo')
        if is_link(nfo):raise ValueError('NFO 路径为链接，无法编辑')
        return row,nfo

    def exists(self,subscription_id,video_id):
        with self.store.connect() as db:
            try:row,path=self.locate(db,subscription_id,video_id)
            except NfoConflict:return {'has_nfo':False}
        return {'has_nfo':path.is_file()}

    def read_bytes(self,path):
        if not path.is_file():raise LookupError('未找到 NFO 文件')
        if path.stat().st_size>MAX_BYTES:raise ValueError('NFO 文件超过 1 MiB')
        raw=path.read_bytes()
        if len(raw)>MAX_BYTES:raise ValueError('NFO 文件超过 1 MiB')
        try:raw.decode('utf-8')
        except UnicodeDecodeError as exc:raise ValueError('NFO 文件需采用 UTF-8 编码') from exc
        return raw

    def read(self,subscription_id,video_id):
        with self.store.connect() as db:row,path=self.locate(db,subscription_id,video_id)
        raw=self.read_bytes(path)
        return {'success':True,'content':raw.decode('utf-8'),'etag':hashlib.sha256(raw).hexdigest(),
                'task_id':row['download_task_id']}

    def save(self,subscription_id,video_id,payload):
        raw=payload.content.encode('utf-8')
        if len(raw)>MAX_BYTES:raise ValueError('NFO 内容超过 1 MiB')
        temporary=None
        try:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row,path=self.locate(db,subscription_id,video_id)
                original=self.read_bytes(path)
                if payload.expected_task_id is not None and payload.expected_task_id!=row['download_task_id']:
                    raise NfoConflict('作品下载关联已变化，请重新打开 NFO')
                if payload.expected_etag is not None and payload.expected_etag!=hashlib.sha256(original).hexdigest():
                    raise NfoConflict('NFO 内容已变化，请重新打开后编辑')
                with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.harbor-nfo-',delete=False) as output:
                    temporary=output.name;output.write(raw);output.flush();os.fsync(output.fileno())
                relative=path.relative_to(self.manager.root).as_posix()
                task_exists=db.execute('SELECT id FROM tasks WHERE id=?',(row['download_task_id'],)).fetchone()
                db.execute('INSERT INTO media_assets(id,path,task_id,title,kind,is_primary,created_at) '
                           'VALUES (?,?,?,?,?,?,?) ON CONFLICT(path) DO NOTHING',
                           (str(uuid.uuid4()),relative,row['download_task_id'] if task_exists else None,path.name,'attachment',0,now()))
                if is_link(path):raise ValueError('NFO 路径已变为链接，未保存')
                if payload.expected_etag is not None and hashlib.sha256(self.read_bytes(path)).hexdigest()!=payload.expected_etag:
                    raise NfoConflict('NFO 内容已变化，未保存')
                os.replace(temporary,path);temporary=None
            return {'success':True,'etag':hashlib.sha256(raw).hexdigest()}
        finally:
            if temporary is not None:
                try:os.unlink(temporary)
                except FileNotFoundError:pass
