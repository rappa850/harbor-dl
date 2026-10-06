"""Link a saved subscription work to the real download queue atomically."""
import json
import re
from pydantic import BaseModel, Field
from .downloads import now
from .task_status import ACTIVE


class DownloadConflict(Exception):pass


class SubscriptionDownloadInput(BaseModel):
    redownload: bool=False


class BatchDownloadInput(BaseModel):
    video_ids: list[str] | None = Field(default=None,max_length=2000)   # explicit works; None = every work still to do


def format_for_quality(quality):
    if quality=='best':return 'bestvideo+bestaudio/best'
    if quality=='bestvideo+bestaudio':return quality
    if re.fullmatch(r'bestvideo\[height<=\d{3,4}\]\+bestaudio',quality):return quality
    match=re.fullmatch(r'(\d{3,4})p?',quality)
    if match:
        height=int(match[1])
        return f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'
    raise ValueError('此画质配置尚未适配，请先选择 best 或分辨率数值')


def video_state(row,assets):
    task_status=row['task_status']
    path=row['task_file_path'] or row['download_file_path']
    playable=False
    if path:
        try:assets.path(path);playable=True
        except ValueError:pass
    if task_status in ACTIVE:status='downloading'
    elif task_status=='ERROR':status='failed'
    elif task_status=='CANCELLED':status='cancelled'
    elif task_status=='COMPLETED' or row['downloaded']:status='downloaded' if playable else 'orphaned'
    else:status='failed' if row['error_message'] else 'not_downloaded'
    return {'status':status,'task_status':task_status,'downloaded':bool(row['downloaded']),
            'error_message':row['task_error'] or row['error_message'],'file_available':playable}


PENDING_STATUSES=('not_downloaded','failed','cancelled','orphaned')


def queue_many(store,manager,subscription_id,video_ids=None):
    """Queue several works; each one succeeds or is reported on its own. Without ids: all works still to do."""
    subscription_id=str(subscription_id)
    with store.connect() as db:
        if not db.execute('SELECT id FROM subscriptions WHERE id=?',(subscription_id,)).fetchone():raise LookupError('订阅不存在')
        rows=db.execute('SELECT v.id,v.video_id,v.downloaded,v.download_file_path,v.error_message,t.status AS task_status,'
                        't.file_path AS task_file_path,t.error AS task_error FROM subscription_videos v '
                        'LEFT JOIN tasks t ON t.id=v.download_task_id WHERE v.subscription_id=? ORDER BY v.created_at,v.id',
                        (subscription_id,)).fetchall()
    chosen=None if video_ids is None else set(video_ids)
    result={'requested':0,'queued':0,'skipped':0,'errors':[]}
    for row in rows:
        if chosen is not None and row['id'] not in chosen:continue
        if chosen is None and video_state(row,manager.assets)['status'] not in PENDING_STATUSES:continue
        result['requested']+=1
        try:queue_video(store,manager,subscription_id,row['id'])
        except DownloadConflict:result['skipped']+=1            # already downloading / downloaded
        except (LookupError,ValueError) as exc:result['errors'].append({'video_id':row['video_id'],'message':str(exc)})
        else:result['queued']+=1
    if chosen is not None:
        known={row['id'] for row in rows}
        for missing in chosen-known:result['errors'].append({'video_id':missing,'message':'作品不存在'});result['requested']+=1
    return result


def queue_video(store,manager,subscription_id,video_id,redownload=False):
    subscription_id,video_id=str(subscription_id),str(video_id)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        subscription=db.execute('SELECT config FROM subscriptions WHERE id=?',(subscription_id,)).fetchone()
        row=db.execute('SELECT v.*,t.status AS task_status,t.file_path AS task_file_path,t.error AS task_error '
                       'FROM subscription_videos v LEFT JOIN tasks t ON t.id=v.download_task_id '
                       'WHERE v.id=? AND v.subscription_id=?',(video_id,subscription_id)).fetchone()
        if subscription is None or row is None:raise LookupError('订阅或作品不存在')
        state=video_state(row,manager.assets)
        if row['task_status'] in ACTIVE:raise DownloadConflict('该作品已有进行中的下载任务')
        if state['status']=='downloaded' and not redownload:
            raise DownloadConflict('该作品已下载，请明确选择重新下载')
        config=json.loads(subscription['config']);metadata=json.loads(row['metadata'])
        task=manager.create(metadata['url'],metadata['title'],format_for_quality(config['quality']),
                            True,True,config['platform'],config['nickname'],subscription_id,db=db)
        db.execute('UPDATE subscription_videos SET download_task_id=?,downloaded=0,error_message=NULL,'
                   'download_file_path=NULL,updated_at=? WHERE id=?',(task['id'],now(),video_id))
    manager.wake.set()
    return task
