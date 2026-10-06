"""Manual full catalog retrieval, separate from checks and download jobs."""
import asyncio
import inspect
import json
import math
import re
import uuid
from datetime import datetime,timezone
from .downloads import now
from .subscription_downloads import video_state,queue_video,DownloadConflict
from .subscription_platforms import PlatformError

FIRST_CHECK_PAGES=3     # first look at a new subscription (old UI: "首次添加默认仅检测前几页")
INCREMENTAL_PAGES=5     # incremental check stops earlier once a page holds nothing new


class SyncBusy(Exception):pass


class SyncGate:
    """Caps how many subscriptions talk to a platform at once (full syncs and checks share it).
    The limit is read on every wake-up, so a settings change applies without a restart."""
    def __init__(self,limit):
        self.limit,self.running,self.waiting=limit,0,0
        self.condition=None

    def cond(self):
        if self.condition is None:self.condition=asyncio.Condition()
        return self.condition

    async def acquire(self):
        cond=self.cond()
        async with cond:
            self.waiting+=1
            try:await cond.wait_for(lambda:self.running<max(1,self.limit()))
            finally:self.waiting-=1
            self.running+=1

    async def release(self):
        cond=self.cond()
        async with cond:
            self.running-=1;cond.notify_all()

    async def poke(self):
        cond=self.cond()
        async with cond:cond.notify_all()

    async def __aenter__(self):await self.acquire()
    async def __aexit__(self,*exc):await self.release()

VIDEO_STATUSES=('downloaded','downloading','not_downloaded','failed','cancelled','orphaned')


def catalog_url(config):
    platform=config['platform'];identity=config['user_id'];kind=config['subscription_type']
    if platform=='youtube' and kind=='user' and re.fullmatch(r'UC[A-Za-z0-9_-]+',identity):
        return f"https://www.youtube.com/channel/{identity}/{config.get('youtube_tab_type') or 'videos'}"
    if platform=='youtube_playlist' and kind=='playlist' and re.fullmatch(r'[A-Za-z0-9_-]+',identity):
        return f'https://www.youtube.com/playlist?list={identity}'
    if platform=='bilibili' and kind=='user' and identity.isascii() and identity.isdigit():
        return f'https://space.bilibili.com/{identity}/video'
    raise ValueError('此订阅类型的作品同步适配尚未完成，或缺少已解析的平台身份')


def entry_metadata(entry,platform):
    if not isinstance(entry,dict) or entry.get('_type') in ('playlist','multi_video'):
        raise ValueError('作品列表包含不可用条目或未展开的子集合，未保存此次同步')
    identity=str(entry.get('id') or '')
    if platform.startswith('youtube') and re.fullmatch(r'[A-Za-z0-9_-]+',identity):
        url=f'https://www.youtube.com/watch?v={identity}'
    elif platform=='bilibili' and re.fullmatch(r'BV[A-Za-z0-9]+',identity):
        url=f'https://www.bilibili.com/video/{identity}'
    else:raise ValueError('作品缺少有效平台标识，未保存此次同步')
    duration=entry.get('duration')
    if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<0:duration=None
    published=None
    try:
        if entry.get('timestamp') is not None:
            published=datetime.fromtimestamp(entry['timestamp'],timezone.utc).isoformat()
        elif entry.get('upload_date'):
            published=datetime.strptime(entry['upload_date'],'%Y%m%d').replace(tzinfo=timezone.utc).isoformat()
    except (ValueError,TypeError,OverflowError,OSError):pass
    thumbnails=entry.get('thumbnails') or []
    cover=entry.get('thumbnail') or (thumbnails[-1].get('url') if thumbnails and isinstance(thumbnails[-1],dict) else None)
    return identity,{'title':entry.get('title') or identity,'description':entry.get('description'),
                     'url':url,'cover_url':cover,'duration':duration,'publish_time':published,
                     'extra_data':{'availability':entry.get('availability')}}


class SubscriptionCatalog:
    def __init__(self,store,subscriptions,inspector,network,manager,registry=None,covers=None):
        self.covers=covers
        self.gate=SyncGate(self.sync_limit)
        self.progress={}
        self.store,self.subscriptions,self.inspector,self.network=store,subscriptions,inspector,network
        self.manager=manager
        self.registry=registry
        self.active=set()

    def sync_limit(self):
        row=self.store.one("SELECT value FROM settings WHERE key='sync_concurrency'")
        try:return max(1,int(row['value'])) if row else 1
        except (TypeError,ValueError):return 1

    def sync_progress(self,subscription_id):
        """Live state of a running or queued sync/check, or None when idle."""
        state=self.progress.get(str(subscription_id))
        if state is None:return None
        return {**state,'queue_position':max(1,self.gate.waiting) if state['state']=='queued' else 0,
                'limit':self.sync_limit()}

    def track(self,subscription_id,mode,total):
        state={'state':'queued','mode':mode,'pages':0,'fetched':0,'total':total,'started_at':now()}
        self.progress[str(subscription_id)]=state
        return state

    @staticmethod
    def accepts_progress(adapter):
        return 'progress' in inspect.signature(adapter.fetch).parameters

    def adapter(self,config):
        return self.registry.for_config(config) if self.registry else None

    def unavailable(self,config):
        """Reason an adapter-declared platform cannot be handled, or None when no adapter claims it."""
        declared=self.registry.get(config['platform']) if self.registry else None
        return declared.describe_unavailable(config) if declared else None

    def state(self,subscription_id):
        return self.store.one('SELECT * FROM subscription_states WHERE subscription_id=?',(str(subscription_id),))

    def decorate(self,config):
        if config is None:return None
        adapter=self.adapter(config);reason=None
        if adapter:available=True
        else:
            try:catalog_url(config);available=True
            except ValueError as exc:available=False;reason=self.unavailable(config) or str(exc)
        state=self.state(config['id']) or {}
        stored=self.store.one('SELECT COUNT(*) AS n FROM subscription_videos WHERE subscription_id=?',(config['id'],))['n']
        interval=config.get('update_interval') or 0
        next_check=None
        if adapter and adapter.supports_check and config.get('status')=='active' and interval>0:
            if state.get('last_checked_at'):
                due=datetime.fromisoformat(state['last_checked_at']).timestamp()+interval
                next_check=datetime.fromtimestamp(due,timezone.utc).isoformat()
            else:next_check='pending'
        config['runtime'].update(stored_videos=stored,manual_sync_available=available,is_syncing=config['id'] in self.active,
            check_available=bool(adapter and adapter.supports_check),unavailable_reason=reason,
            last_checked_at=state.get('last_checked_at'),last_success_at=state.get('last_success_at'),
            last_error=state.get('last_error'),last_mode=state.get('last_mode'),
            last_new_count=state.get('last_new_count',0),last_queued_count=state.get('last_queued_count',0),
            next_check_at=next_check)
        return config

    async def sync(self,subscription_id):
        subscription_id=str(subscription_id)
        config=self.subscriptions.get(subscription_id)
        if config is None:raise LookupError('订阅不存在')
        adapter=self.adapter(config)
        if adapter is None and self.unavailable(config):raise ValueError(self.unavailable(config))
        url=None if adapter else catalog_url(config)
        if subscription_id in self.active:raise SyncBusy()
        self.active.add(subscription_id)
        state=self.track(subscription_id,'sync',config.get('video_count'))
        try:
            async with self.gate:
                state['state']='running'
                return await self.run_sync(subscription_id,config,adapter,url,state)
        finally:
            self.active.discard(subscription_id);self.progress.pop(subscription_id,None)

    async def run_sync(self,subscription_id,config,adapter,url,state):
        if adapter:
            def report(pages,fetched):state['pages'],state['fetched']=pages,fetched
            extra={'progress':report} if self.accepts_progress(adapter) else {}
            fetched=await adapter.fetch(config,self.network.for_url(self.adapter_url(config)),**extra)
            if not fetched.complete:raise ValueError('平台未返回完整作品列表，未保存此次同步')
            unique=fetched.entries
        else:
            info=await self.inspector.raw_info(url,self.network.for_url(url),catalog=True)
            if not isinstance(info,dict) or info.get('_type') not in ('playlist','multi_video') or str(info.get('id'))!=config['user_id']:
                raise ValueError('同步返回的集合身份不匹配，未保存此次同步')
            entries=info.get('entries')
            if not isinstance(entries,list):raise ValueError('平台未返回完整作品列表')
            unique={}
            for entry in entries:
                identity,metadata=entry_metadata(entry,config['platform'])
                unique[identity]=metadata
        added=len(self.persist(subscription_id,unique))
        self.cache_covers(unique)
        return {'status':'completed','fetched':len(unique),'new_videos_count':added,
                'video_count':self.list(subscription_id,1,1)['total']}

    def cache_covers(self,entries):
        """Keep local copies of the covers in the background; the remote links expire."""
        if self.covers is None:return
        for metadata in entries.values():
            cover=metadata.get('cover_url')
            if cover and metadata.get('url'):
                self.covers.fetch_later(metadata['url'],cover,self.network.for_url(cover))

    def backfill_covers(self):
        if self.covers is None:return
        with self.store.connect() as db:
            rows=[json.loads(r['metadata']) for r in db.execute('SELECT metadata FROM subscription_videos')]
        self.cache_covers({str(i):m for i,m in enumerate(rows)})

    def adapter_url(self,config):
        return self.registry.get(config['platform']).home_url

    def persist(self,subscription_id,unique):
        """Insert/update works in one transaction; returns [(row id, video id)] for newly discovered ones."""
        created=[];timestamp=now()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM subscriptions WHERE id=?',(subscription_id,)).fetchone():
                raise LookupError('订阅已经删除，未保存此次同步')
            for identity,metadata in unique.items():
                exists=db.execute('SELECT id FROM subscription_videos WHERE subscription_id=? AND video_id=?',(subscription_id,identity)).fetchone()
                if exists:
                    db.execute('UPDATE subscription_videos SET metadata=?,updated_at=? WHERE id=?',
                        (json.dumps(metadata,ensure_ascii=False),timestamp,exists['id']))
                else:
                    row_id=str(uuid.uuid4())
                    db.execute('INSERT INTO subscription_videos (id,subscription_id,video_id,metadata,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                        (row_id,subscription_id,identity,json.dumps(metadata,ensure_ascii=False),timestamp,timestamp))
                    created.append((row_id,identity))
        return created

    def record_state(self,subscription_id,mode,error=None,new=0,queued=0):
        stamp=now()
        with self.store.connect() as db:
            if not db.execute('SELECT id FROM subscriptions WHERE id=?',(subscription_id,)).fetchone():return
            db.execute('INSERT INTO subscription_states(subscription_id,last_checked_at,last_success_at,last_error,last_mode,'
                       'last_new_count,last_queued_count,updated_at) VALUES (?,?,?,?,?,?,?,?) '
                       'ON CONFLICT(subscription_id) DO UPDATE SET last_checked_at=excluded.last_checked_at,'
                       'last_success_at=CASE WHEN excluded.last_error IS NULL THEN excluded.last_checked_at ELSE last_success_at END,'
                       'last_error=excluded.last_error,last_mode=excluded.last_mode,last_new_count=excluded.last_new_count,'
                       'last_queued_count=excluded.last_queued_count,updated_at=excluded.updated_at',
                       (subscription_id,stamp,stamp if error is None else None,error,mode,new,queued,stamp))

    async def check(self,subscription_id,mode='check'):
        """Incremental look for new works; queues them when auto download is on. Failure keeps stored works."""
        subscription_id=str(subscription_id)
        config=self.subscriptions.get(subscription_id)
        if config is None:raise LookupError('订阅不存在')
        adapter=self.adapter(config)
        if adapter is None or not adapter.supports_check:
            raise ValueError(self.unavailable(config) or '此订阅类型的检查更新适配尚未完成')
        if subscription_id in self.active:raise SyncBusy()
        self.active.add(subscription_id)
        state=self.track(subscription_id,'check',config.get('video_count'))
        try:
            await self.gate.acquire()
            try:
                state['state']='running'
                with self.store.connect() as db:
                    known={row['video_id'] for row in db.execute('SELECT video_id FROM subscription_videos WHERE subscription_id=?',(subscription_id,))}
                first=not known
                def report(pages,count):state['pages'],state['fetched']=pages,count
                extra={'progress':report} if self.accepts_progress(adapter) else {}
                fetched=await adapter.fetch(config,self.network.for_url(self.adapter_url(config)),known=set(known),
                                            max_pages=FIRST_CHECK_PAGES if first else INCREMENTAL_PAGES,**extra)
                created=self.persist(subscription_id,fetched.entries)
                self.cache_covers(fetched.entries)
                queued=0;problems=[]
                if config['auto_download'] and config['status']=='active':
                    for row_id,video_id in created:
                        if not adapter.downloadable(fetched.entries[video_id]):continue
                        try:queue_video(self.store,self.manager,subscription_id,row_id)
                        except (DownloadConflict,LookupError,ValueError) as exc:problems.append(f'{video_id}: {exc}')
                        else:queued+=1
                error=('部分新作品未能加入下载：'+'；'.join(problems[:3])) if problems else None
                self.record_state(subscription_id,mode,error,len(created),queued)
                return {'status':'completed','first_check':first,'pages':fetched.pages,'fetched':len(fetched.entries),
                        'new_videos_count':len(created),'queued_count':queued,'skipped':fetched.skipped,
                        'errors':problems,'video_count':self.list(subscription_id,1,1)['total']}
            except LookupError:raise
            except (ValueError,PlatformError,TimeoutError) as exc:
                self.record_state(subscription_id,mode,str(exc) or exc.__class__.__name__)
                raise
            finally:await self.gate.release()
        finally:
            self.active.discard(subscription_id);self.progress.pop(subscription_id,None)

    def records(self,subscription_id):
        subscription_id=str(subscription_id)
        if self.subscriptions.get(subscription_id) is None:raise LookupError('订阅不存在')
        with self.store.connect() as db:
            db.execute('BEGIN')
            rows=db.execute("SELECT v.*,t.status AS task_status,t.file_path AS task_file_path,t.error AS task_error,t.progress AS task_progress,t.speed AS task_speed,a.id AS asset_id,a.kind AS media_kind FROM subscription_videos v LEFT JOIN tasks t ON t.id=v.download_task_id LEFT JOIN media_assets a ON a.path=COALESCE(NULLIF(t.file_path,''),v.download_file_path) AND a.is_primary=1 WHERE v.subscription_id=? ORDER BY json_extract(v.metadata,'$.publish_time') DESC,v.created_at DESC,v.id",
                (subscription_id,)).fetchall()
        return [
            {**json.loads(row['metadata']),'id':row['id'],'subscription_id':row['subscription_id'],
             'video_id':row['video_id'],'downloaded':bool(row['downloaded']),'download_task_id':row['download_task_id'],
             'error_message':row['error_message'],'created_at':row['created_at'],
             'asset_id':row['asset_id'],'media_kind':row['media_kind'],
             'cover_local':self.covers.local(json.loads(row['metadata']).get('url')) if self.covers else None,
             'task_progress':row['task_progress'],'task_speed':row['task_speed'],
             **video_state(row,self.manager.assets)} for row in rows]

    def playable(self,subscription_id):
        records=self.records(subscription_id)
        items=[{'id':record['asset_id'],'title':record['title'],'kind':record['media_kind'],
                'work_id':record['id'],'subscription_id':str(subscription_id),'duration':record.get('duration')} for record in records
               if record['status']=='downloaded' and record['asset_id'] and record['media_kind'] in ('video','audio','image')]
        return {'items':items,'total':len(items)}

    def delete_record(self,subscription_id,video_id):
        # Removing a list entry must not delegate to task/file deletion.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM subscriptions WHERE id=?',(str(subscription_id),)).fetchone():
                raise LookupError('订阅不存在')
            deleted=db.execute('DELETE FROM subscription_videos WHERE subscription_id=? AND id=?',
                               (str(subscription_id),str(video_id))).rowcount
            if not deleted:raise LookupError('作品记录不存在')
        return {'ok':True}

    def list(self,subscription_id,page=1,page_size=10,status='all',query=''):
        if status not in ('all',*VIDEO_STATUSES):raise ValueError('此作品状态的筛选尚未适配')
        records=self.records(subscription_id)
        if status!='all':records=[record for record in records if record['status']==status]
        query=(query or '').strip().casefold()
        if query:records=[r for r in records if query in (r.get('title') or '').casefold() or query in r['video_id']]
        offset=(page-1)*page_size
        return {'total':len(records),'page':page,'page_size':page_size,'videos':records[offset:offset+page_size]}

    def stats(self,subscription_id):
        records=self.records(subscription_id)
        fields={'downloaded':'downloaded_count','downloading':'downloading_count',
                'not_downloaded':'not_downloaded_count','failed':'failed_count',
                'cancelled':'cancelled_count','orphaned':'orphaned_count'}
        result={'total':len(records),'supported_statuses':list(VIDEO_STATUSES),
                **{field:0 for field in fields.values()}}
        for record in records:result[fields[record['status']]]+=1
        return result
