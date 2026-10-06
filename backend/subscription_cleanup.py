"""Reset missing-file works without touching live or shared download folders."""
import shutil
import sqlite3
import stat
from uuid import UUID
from pydantic import BaseModel
from .downloads import now
from .subscription_downloads import video_state


class OrphanCleanupInput(BaseModel):
    delete_residual: bool=True


def is_link(path):
    try:attributes=getattr(path.lstat(),'st_file_attributes',0)
    except FileNotFoundError:return False
    return path.is_symlink() or bool(attributes & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))


def checked_folder(root,task_id):
    if str(UUID(task_id))!=task_id:raise ValueError('任务标识不能用于目录清理')
    original=root/task_id
    if is_link(original):raise ValueError('任务目录包含链接，未清理')
    folder=original.resolve()
    if folder.parent!=root or folder.name!=task_id:raise ValueError('任务目录超出媒体根目录')
    if folder.exists():
        if not folder.is_dir():raise ValueError('任务路径不是目录')
        pending=[folder]
        while pending:
            for child in pending.pop().iterdir():
                if is_link(child):raise ValueError('残留目录包含链接，未清理')
                if child.is_dir():pending.append(child)
    return folder


def cleanup_orphans(store,catalog,manager,subscription_id,delete_residual=True):
    subscription_id=str(subscription_id)
    candidates=[record for record in catalog.records(subscription_id) if record['status']=='orphaned']
    result={'matched':len(candidates),'reset_videos':0,'deleted_tasks':0,'deleted_paths_count':0,'skipped':0,'errors':[]}
    for candidate in candidates:
        try:
            with store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT id FROM subscriptions WHERE id=?',(subscription_id,)).fetchone():
                    raise ValueError('订阅已删除，未清理作品')
                row=db.execute('SELECT v.*,t.status AS task_status,t.file_path AS task_file_path,t.error AS task_error '
                               'FROM subscription_videos v LEFT JOIN tasks t ON t.id=v.download_task_id '
                               'WHERE v.id=? AND v.subscription_id=?',(candidate['id'],subscription_id)).fetchone()
                if row is None or video_state(row,manager.assets)['status']!='orphaned':
                    result['skipped']+=1;continue
                task_id=row['download_task_id']
                folder=None;assets=[]
                if task_id:
                    if task_id in manager.running:raise ValueError('下载器尚未停止，未清理')
                    task=db.execute('SELECT subscription_id FROM tasks WHERE id=?',(task_id,)).fetchone()
                    if task and task['subscription_id']!=subscription_id:raise ValueError('关联任务不属于此订阅')
                    if db.execute('SELECT id FROM subscription_videos WHERE download_task_id=? AND id<>?',(task_id,row['id'])).fetchone():
                        raise ValueError('关联任务仍被其他作品使用，未清理')
                    if delete_residual:
                        folder=checked_folder(manager.root,task_id)
                        prefix=task_id+'/'
                        assets=db.execute('SELECT * FROM media_assets WHERE task_id=? OR substr(path,1,?)=?',
                                          (task_id,len(prefix),prefix)).fetchall()
                        for asset in assets:
                            path=(manager.root/asset['path']).resolve()
                            if not path.is_relative_to(folder) or asset['task_id'] not in (None,task_id):
                                raise ValueError('媒体索引包含其他任务或目录的文件，未清理')
                db.execute('UPDATE subscription_videos SET downloaded=0,download_task_id=NULL,error_message=NULL,'
                           'download_file_path=NULL,updated_at=? WHERE id=?',(now(),row['id']))
                deleted=0
                if task_id:
                    db.execute('DELETE FROM task_events WHERE task_id=?',(task_id,))
                    deleted=db.execute('DELETE FROM tasks WHERE id=?',(task_id,)).rowcount
                    if delete_residual:
                        for asset in assets:db.execute('DELETE FROM media_assets WHERE id=?',(asset['id'],))
                    else:db.execute('UPDATE media_assets SET task_id=NULL WHERE task_id=?',(task_id,))
                removed=int(folder is not None and folder.exists())
                if removed:shutil.rmtree(folder)
            result['reset_videos']+=1;result['deleted_tasks']+=deleted;result['deleted_paths_count']+=removed
        except (ValueError,OSError,sqlite3.Error) as exc:
            result['skipped']+=1;result['errors'].append({'video_id':candidate['id'],'message':str(exc)})
    return result
