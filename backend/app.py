import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from .covers import CoverCache, key_for
from .imagesize import image_ratio
from .downloads import DownloadManager, now
from .store import Store
from .media import MediaInspector, platform_for, share_url
from .task_status import ACTIVE, ALL
from .network import NetworkConfig
from .player import PlaybackRecords, metadata, srt_to_vtt, subtitle_list
from .task_query import TaskQuery
from .api_tokens import ApiTokens
from .subscriptions import Subscriptions, SubscriptionEdit, SubscriptionImport
from .subscription_profiles import ProfileInput, ProfileResolver
from .subscription_catalog import SubscriptionCatalog, SyncBusy
from .subscription_platforms import PlatformError, default_registry
from .subscription_scheduler import SubscriptionScheduler
from .browser_login import BrowserLogin, BrowserLoginError
from . import novnc_proxy
from .subscription_downloads import SubscriptionDownloadInput,BatchDownloadInput,DownloadConflict,queue_video,queue_many
from .subscription_cleanup import OrphanCleanupInput,cleanup_orphans
from .subscription_nfo import SubscriptionNfo,NfoInput,NfoConflict
from .live_config import LiveSubscriptions,LiveImport,LiveEdit,RoomCheckBusy
from .live_rooms import BilibiliRooms,RoomDetectionError
from .live_monitor import LiveMonitor
from .live_recording import LiveRecording,RecordingConflict

BASE = Path(__file__).resolve().parents[1]
COOKIE = 'harbor_session'


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
    return f'{salt}${value}'


def password_matches(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split('$')[0]), encoded)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=256)

    @field_validator('username')
    @classmethod
    def clean_username(cls, value):
        value = value.strip()
        if len(value) < 3:
            raise ValueError('用户名至少 3 个字符')
        return value


class TaskInput(BaseModel):
    url: str = Field(min_length=10, max_length=4096)
    title: str = Field(default='', max_length=300)
    author: str = Field(default='', max_length=256)
    format_id: str = Field(default='bestvideo+bestaudio/best', min_length=1, max_length=200)
    subtitles: bool = True
    thumbnail: bool = True
    cover_url: str = Field(default='', max_length=4096)

    @field_validator('url')
    @classmethod
    def validate_url(cls, value):
        value = value.strip()
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('请输入 HTTP 或 HTTPS 媒体链接，链接中不能包含登录凭据')
            _ = parsed.port
        except ValueError as exc:
            raise ValueError('无效的媒体链接') from exc
        return value


class ParseInput(BaseModel):
    text: str = Field(min_length=10, max_length=8192)


class ProxyInput(BaseModel):
    enabled: bool = False
    proxy: str | None = Field(default=None, max_length=4096)
    no_proxy: str = Field(default='localhost,127.0.0.1,*.local', max_length=4096)


class CookieInput(BaseModel):
    cookie_content: str = Field(min_length=1, max_length=524288)


class PlaybackInput(BaseModel):
    current_index: int = Field(default=0, ge=0)
    playback_mode: Literal['order', 'random', 'single'] = 'order'
    video_progress: dict[str, Annotated[float, Field(ge=0, allow_inf_nan=False)]] = Field(default_factory=dict, max_length=5000)


class SettingsInput(BaseModel):
    concurrency: int = Field(ge=1, le=8)
    sync_concurrency: int | None = Field(default=None, ge=1, le=3)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1,max_length=128)
    expires_in_days: int | None = Field(default=None,ge=1)

    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        if not value.strip():raise ValueError('令牌名称不能为空')
        return value.strip()


class TokenUpdate(BaseModel):
    name: str | None = Field(default=None,min_length=1,max_length=128)
    expires_at: AwareDatetime | None = None
    is_active: bool | None = None

    @model_validator(mode='after')
    def validate_fields(self):
        if 'name' in self.model_fields_set:
            if not self.name or not self.name.strip():raise ValueError('令牌名称不能为空')
            self.name=self.name.strip()
        if 'is_active' in self.model_fields_set and self.is_active is None:
            raise ValueError('启用状态不能为 null')
        return self


def create_app(data_dir=None, frontend_dir=None, command_builder=None, inspector=None,live_detector=None,platform_registry=None,scheduler_options=None,browser_options=None):
    data = Path(data_dir or os.environ.get('HARBOR_DATA_DIR') or BASE / 'var').resolve()
    frontend = Path(frontend_dir or BASE / 'frontend' / 'dist').resolve()
    store = Store(data / 'harbor-dl.sqlite3')
    manager = DownloadManager(store, data / 'downloads', command_builder)
    inspector = inspector or MediaInspector()
    network = NetworkConfig(store)
    records = PlaybackRecords(store)
    task_query = TaskQuery(store, manager.assets)
    api_tokens = ApiTokens(store)
    subscriptions = Subscriptions(store)
    live_subscriptions=LiveSubscriptions(store)
    live_detector=live_detector or BilibiliRooms()
    live_recording=LiveRecording(store,data/'recordings',live_detector,network)
    live_monitor=LiveMonitor(live_subscriptions,live_detector,network,recording=live_recording)
    live_subscriptions.register_monitor=live_monitor.register
    live_subscriptions.monitor_status=live_monitor.status
    registry = platform_registry or default_registry()
    profiles = ProfileResolver(inspector,network,registry)
    covers = CoverCache(data / 'covers')
    catalog = SubscriptionCatalog(store,subscriptions,inspector,network,manager,registry,covers)
    scheduler = SubscriptionScheduler(subscriptions,catalog,**(scheduler_options or {}))
    for adapter in set(registry.adapters.values()):
        for platform in adapter.platforms:manager.resolvers[platform]=adapter.download_target
    nfo=SubscriptionNfo(store,manager)
    browser=BrowserLogin(data,network,busy=lambda:len(catalog.active),**(browser_options or {}))

    @asynccontextmanager
    async def lifespan(app):
        await manager.start()
        catalog.backfill_covers()
        try:
            await live_recording.restore()
            await live_monitor.start()
            await scheduler.start()
            yield
        finally:
            await scheduler.stop()
            await browser.close()
            await live_monitor.stop()
            await live_recording.close()
            await manager.stop()

    app = FastAPI(title='Harbor-DL', version='0.1.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.manager = store, manager
    app.state.catalog=catalog
    app.state.scheduler=scheduler
    app.state.browser=browser
    app.state.live_monitor=live_monitor
    app.state.live_recording=live_recording

    @app.middleware('http')
    async def same_origin(request: Request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail': '请求来源不匹配'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def session_user(request: Request):
        token = request.cookies.get(COOKIE, '')
        if not token:
            raise HTTPException(401, '请先登录')
        result = store.one('SELECT u.id,u.username FROM sessions s JOIN users u ON u.id=s.user_id '
                           'WHERE s.token_hash=? AND s.expires>?',
                           (hashlib.sha256(token.encode()).hexdigest(), time.time()))
        if not result:
            raise HTTPException(401, '登录已失效，请重新登录')
        return result

    novnc_proxy.install(app,session_user,lambda:browser.mode=='docker')

    def user(request: Request):
        token=request.headers.get('X-API-Token')
        authorization=request.headers.get('authorization','')
        if token is None and authorization:
            scheme, _, value=authorization.partition(' ')
            if scheme.lower()!='bearer' or not value.strip():
                raise HTTPException(401,'无效的认证请求头')
            token=value.strip()
        if token is not None:
            account=api_tokens.authenticate(token)
            if not account:raise HTTPException(401,'API Token 无效、已停用或已过期')
            return account
        return session_user(request)

    def set_session(response, account, request):
        token = secrets.token_urlsafe(48)
        with store.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), account['id'], time.time() + 86400 * 7))
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', max_age=86400 * 7)
        return {'username': account['username']}

    @app.get('/api/setup/status')
    def setup_status():
        return {'needs_setup': store.one('SELECT id FROM users LIMIT 1') is None}

    @app.post('/api/setup', status_code=201)
    def setup(payload: Credentials, response: Response, request: Request):
        encoded = password_hash(payload.password)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT id FROM users LIMIT 1').fetchone():
                raise HTTPException(409, '管理员已经创建')
            cursor = db.execute('INSERT INTO users(username,password,created_at) VALUES (?,?,?)',
                                (payload.username, encoded, now()))
            account = {'id': cursor.lastrowid, 'username': payload.username}
        return set_session(response, account, request)

    @app.post('/api/auth/login')
    def login(payload: Credentials, response: Response, request: Request):
        account = store.one('SELECT * FROM users WHERE username=?', (payload.username,))
        # Run the same expensive hash path even for an unknown account.
        dummy = '0' * 32 + '$' + '0' * 64
        matched = password_matches(payload.password, account['password'] if account else dummy)
        if not account or not matched:
            raise HTTPException(401, '用户名或密码错误')
        return set_session(response, account, request)

    @app.get('/api/auth/me')
    def me(account=Depends(user)):
        return account

    @app.post('/api/auth/logout')
    def logout(request: Request, response: Response, account=Depends(session_user)):
        token = request.cookies.get(COOKIE, '')
        with store.connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie(COOKIE)
        return {'ok': True}

    @app.get('/api/auth/tokens')
    def tokens(account=Depends(session_user)):
        return {'items':api_tokens.list(account['id'])}

    @app.post('/api/auth/tokens',status_code=201)
    def create_token(payload: TokenCreate,account=Depends(session_user)):
        try:return api_tokens.create(account['id'],payload.name,payload.expires_in_days)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @app.patch('/api/auth/tokens/{token_id}')
    def edit_token(token_id: UUID,payload: TokenUpdate,account=Depends(session_user)):
        result=api_tokens.update(str(token_id),account['id'],{key:getattr(payload,key) for key in payload.model_fields_set})
        if result is None:raise HTTPException(404,'API Token 不存在')
        return result

    @app.post('/api/auth/tokens/{token_id}/regenerate')
    def regenerate_token(token_id: UUID,account=Depends(session_user)):
        result=api_tokens.rotate(str(token_id),account['id'])
        if result is None:raise HTTPException(404,'API Token 不存在')
        return result

    @app.delete('/api/auth/tokens/{token_id}')
    def delete_token(token_id: UUID,account=Depends(session_user)):
        if not api_tokens.delete(str(token_id),account['id']):raise HTTPException(404,'API Token 不存在')
        return {'ok':True}

    @app.get('/api/dashboard')
    def dashboard(account=Depends(user)):
        counts = {r['status']: r['count'] for r in store.all('SELECT status,COUNT(*) AS count FROM tasks GROUP BY status')}
        disk = shutil.disk_usage(data)
        return {'counts': counts, 'total_tasks': sum(counts.values()),
                'downloaded_bytes': store.one('SELECT COALESCE(SUM(total),0) AS size FROM tasks WHERE status="COMPLETED"')['size'],
                'disk': {'total': disk.total, 'free': disk.free},
                'recent_tasks': store.all('SELECT * FROM tasks ORDER BY created_at DESC LIMIT 6')}

    @app.get('/api/tasks')
    def tasks(status: str = '', limit: int = Query(default=24,ge=1,le=500), offset: int = Query(default=0,ge=0),
              platform: str = '', subscription_id: str = '', manual_only: bool = False,
              orphan_only: bool = False, query: str = Query(default='',max_length=512), account=Depends(user)):
        try:
            return task_query.list(limit,offset,status,platform,subscription_id,manual_only,orphan_only,query)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc

    @app.post('/api/tasks', status_code=201)
    async def add_task(payload: TaskInput, account=Depends(user)):
        task = manager.create(payload.url, payload.title, payload.format_id, payload.subtitles,
                              payload.thumbnail, platform_for(payload.url), payload.author)
        if payload.cover_url:
            covers.fetch_later(payload.url, payload.cover_url, network.for_url(payload.cover_url))
        return task

    @app.post('/api/media/parse')
    async def parse_media(payload: ParseInput, account=Depends(user)):
        try:
            url = share_url(payload.text)
            return await inspector.inspect(url, network=network.for_url(url))
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(504, '解析超时，请检查网络或稍后重试') from exc

    @app.get('/api/network')
    def network_status(account=Depends(user)):
        return network.status()

    @app.put('/api/network/proxy')
    def save_proxy(payload: ProxyInput, account=Depends(user)):
        try:
            return network.save_proxy(payload.enabled, payload.proxy, payload.no_proxy)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.put('/api/network/cookies/{platform}')
    def save_cookie(platform: str, payload: CookieInput, account=Depends(user)):
        try:
            return network.save_cookie(platform, payload.cookie_content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete('/api/network/cookies/{platform}')
    def clear_cookie(platform: str, account=Depends(user)):
        try:
            return network.clear_cookie(platform)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def require_task(task_id):
        task = manager.get(task_id)
        if not task:
            raise HTTPException(404, '任务不存在')
        return task

    @app.get('/api/tasks/{task_id}')
    def task_detail(task_id: str, account=Depends(user)):
        task = require_task(task_id)
        task['events'] = store.all('SELECT status,message,created_at FROM task_events WHERE task_id=? ORDER BY id', (task_id,))
        return task

    @app.post('/api/tasks/{task_id}/cancel')
    async def cancel_task(task_id: str, account=Depends(user)):
        require_task(task_id)
        if not await manager.cancel(task_id):
            raise HTTPException(409, '仅排队、下载或后处理中的任务可以取消')
        return manager.get(task_id)

    @app.post('/api/tasks/{task_id}/retry')
    async def retry_task(task_id: str, account=Depends(user)):
        require_task(task_id)
        if not manager.retry(task_id):
            raise HTTPException(409, '任务尚未停止，或当前状态不支持重试')
        return manager.get(task_id)

    @app.delete('/api/tasks/{task_id}')
    async def delete_task(task_id: str, delete_file: bool = True, delete_related: bool = True, account=Depends(user)):
        task = require_task(task_id)
        if task_id in manager.running or task['status'] in ACTIVE:
            raise HTTPException(409, '请先取消任务，等待下载器停止后再删除')
        folder = (manager.root / task_id).resolve()
        if folder.parent != manager.root or folder.name != task_id:
            raise HTTPException(400, '无效的文件路径')
        if delete_file and delete_related and folder.exists():
            shutil.rmtree(folder)
        elif delete_file and task['file_path']:
            try:
                manager.assets.path(task['file_path']).unlink()
            except ValueError:
                pass
        with store.connect() as db:
            if delete_file:
                if delete_related:
                    db.execute('DELETE FROM media_assets WHERE task_id=?', (task_id,))
                else:
                    db.execute('DELETE FROM media_assets WHERE task_id=? AND is_primary=1', (task_id,))
            db.execute('UPDATE media_assets SET task_id=NULL WHERE task_id=?', (task_id,))
            db.execute('DELETE FROM task_events WHERE task_id=?', (task_id,))
            db.execute('DELETE FROM tasks WHERE id=?', (task_id,))
        return {'ok': True}

    @app.get('/api/files')
    def files(attachments: bool = False, account=Depends(user)):
        items = manager.assets.items(attachments)
        urls = {row['id']: row['url'] for row in store.all('SELECT id,url FROM tasks')}
        for item in items:
            work_url = urls.get(item['task_id']) if item['task_id'] else None
            item['cover'] = covers.local(work_url)
            # width / height of what the library shows for this file: the cached cover, else the picture itself
            shown = covers.find(key_for(work_url)) if item['cover'] else (manager.assets.root / item['path'] if item['kind'] == 'image' else None)
            item['ratio'] = image_ratio(shown) if shown else None
        return {'items': items}

    @app.get('/api/covers/{key}')
    def cover(key: str, account=Depends(user)):
        path = covers.find(key)
        if not path:
            raise HTTPException(404, '封面不存在')
        return FileResponse(path, headers={'Cache-Control': 'private, max-age=604800'})

    def asset_path(asset_id):
        asset = manager.assets.get(asset_id)
        if not asset:
            raise HTTPException(404, '媒体文件不存在')
        try:
            return manager.assets.path(asset['path'])
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get('/api/files/{task_id}/stream')
    def stream(task_id: str, account=Depends(user)):
        path = asset_path(task_id)
        asset = manager.assets.get(task_id)
        if asset['kind'] == 'attachment':
            return FileResponse(path, filename=path.name, media_type='application/octet-stream')
        return FileResponse(path, filename=path.name, content_disposition_type='inline')

    @app.get('/api/files/{asset_id}/gallery')
    def gallery(asset_id: str, account=Depends(user)):
        """All pictures of the post this picture belongs to (display order) and its background music, if any."""
        asset = manager.assets.get(asset_id)
        if not asset:
            raise HTTPException(404, '媒体文件不存在')
        rows = store.all('SELECT id,path,kind FROM media_assets WHERE task_id=? ORDER BY path', (asset['task_id'],)) if asset['task_id'] else [asset]
        found = {'image': [], 'audio': []}
        for row in rows:
            if row['kind'] in found:
                try:
                    manager.assets.path(row['path'])
                except ValueError:
                    continue
                found[row['kind']].append({'id': row['id'], 'name': Path(row['path']).name})
        if asset['kind'] != 'image':
            raise HTTPException(422, '该文件不是图片')
        index = next((i for i, item in enumerate(found['image']) if item['id'] == asset['id']), 0)
        return {'images': found['image'], 'audio': found['audio'][0] if found['audio'] else None, 'index': index}

    @app.get('/api/files/{asset_id}/archive')
    def archive(asset_id: str, account=Depends(user)):
        """Every file of the post this file belongs to, as one zip (pictures, motion pictures, music)."""
        asset = manager.assets.get(asset_id)
        if not asset:
            raise HTTPException(404, '媒体文件不存在')
        rows = store.all('SELECT path FROM media_assets WHERE task_id=? AND kind!=? ORDER BY path', (asset['task_id'], 'attachment')) if asset['task_id'] else [asset]
        paths = []
        for row in rows:
            try:
                paths.append(manager.assets.path(row['path']))
            except ValueError:
                continue
        if not paths:
            raise HTTPException(404, '媒体文件不存在')
        buffer = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as bundle:
            for path in paths:
                bundle.write(path, path.name)
        size = buffer.tell()
        buffer.seek(0)
        name = quote(f"{Path(asset['title']).stem[:60] or 'post'}.zip")
        def chunks():
            with buffer:
                while data := buffer.read(1 << 20):
                    yield data
        return StreamingResponse(chunks(), media_type='application/zip',
                                 headers={'Content-Length': str(size), 'Content-Disposition': f"attachment; filename*=UTF-8''{name}"})

    @app.get('/api/files/{task_id}/download')
    def download(task_id: str, account=Depends(user)):
        path = asset_path(task_id)
        return FileResponse(path, filename=path.name)

    @app.get('/api/files/{asset_id}/subtitles')
    def subtitles(asset_id: str, account=Depends(user)):
        asset_path(asset_id)
        return {'subtitles': subtitle_list(manager.assets, manager.assets.get(asset_id))}

    @app.get('/api/files/{asset_id}/subtitle')
    def subtitle_content(asset_id: str, account=Depends(user)):
        path = asset_path(asset_id)
        if path.suffix.lower() not in ('.vtt', '.srt'):
            raise HTTPException(400, '不是可用字幕文件')
        if path.stat().st_size > 8 * 1024 * 1024:
            raise HTTPException(413, '字幕文件过大')
        try:
            content = path.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError as exc:
            raise HTTPException(422, '字幕需采用 UTF-8 编码') from exc
        return Response(srt_to_vtt(content) if path.suffix.lower() == '.srt' else content,
                        media_type='text/vtt')

    @app.get('/api/files/{asset_id}/metadata')
    async def media_metadata(asset_id: str, account=Depends(user)):
        try:
            return await metadata(asset_path(asset_id))
        except TimeoutError as exc:
            raise HTTPException(504, '媒体元数据读取超时') from exc

    @app.get('/api/playback/record/{subscription_id}')
    def playback_record(subscription_id: UUID, account=Depends(user)):
        return records.get(subscription_id)

    @app.put('/api/playback/record/{subscription_id}')
    def save_playback(subscription_id: UUID, payload: PlaybackInput, account=Depends(user)):
        return records.save(subscription_id, payload)

    @app.get('/api/settings')
    def settings(account=Depends(user)):
        return {'concurrency': int(store.one('SELECT value FROM settings WHERE key="concurrency"')['value']),
                'sync_concurrency': catalog.sync_limit(),
                'ffmpeg_available': shutil.which('ffmpeg') is not None, 'version': app.version}

    @app.get('/api/subscriptions')
    def subscription_list(account=Depends(user)):
        return {'items':[catalog.decorate(item) for item in subscriptions.list()]}

    @app.get('/api/subscriptions/{subscription_id}/sync-progress')
    def sync_progress(subscription_id: UUID,account=Depends(user)):
        return {'progress': catalog.sync_progress(subscription_id)}

    @app.post('/api/subscriptions/{subscription_id}/sync')
    async def sync_subscription(subscription_id: UUID,account=Depends(user)):
        try:return await catalog.sync(subscription_id)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except SyncBusy as exc:raise HTTPException(409,'该订阅正在同步') from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        except TimeoutError as exc:raise HTTPException(504,'作品同步超时，原作品记录保留') from exc
        except PlatformError as exc:raise HTTPException(502,str(exc)) from exc

    @app.post('/api/subscriptions/{subscription_id}/check')
    async def check_subscription(subscription_id: UUID,account=Depends(user)):
        try:return await catalog.check(subscription_id,mode='manual')
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except SyncBusy as exc:raise HTTPException(409,'该订阅正在同步或检查') from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        except TimeoutError as exc:raise HTTPException(504,'检查更新超时') from exc
        except PlatformError as exc:raise HTTPException(502,str(exc)) from exc

    @app.get('/api/subscriptions/{subscription_id}/videos')
    def subscription_videos(subscription_id: UUID,page: int=Query(default=1,ge=1),
                            page_size: int=Query(default=10,ge=1,le=100),status: str='all',q: str=Query(default='',max_length=200),account=Depends(user)):
        try:return catalog.list(subscription_id,page,page_size,status,q)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @app.get('/api/subscriptions/{subscription_id}/videos/stats')
    def subscription_video_stats(subscription_id: UUID,account=Depends(user)):
        try:return catalog.stats(subscription_id)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc

    @app.get('/api/subscriptions/{subscription_id}/playable')
    def subscription_playable(subscription_id: UUID,account=Depends(user)):
        try:return catalog.playable(subscription_id)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc

    @app.post('/api/subscriptions/{subscription_id}/videos/orphan/cleanup')
    async def cleanup_subscription_orphans(subscription_id: UUID,payload: OrphanCleanupInput,account=Depends(user)):
        try:return cleanup_orphans(store,catalog,manager,subscription_id,payload.delete_residual)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc

    @app.post('/api/subscriptions/{subscription_id}/videos/download')
    async def download_subscription_videos(subscription_id: UUID,payload: BatchDownloadInput,account=Depends(user)):
        try:result=queue_many(store,manager,subscription_id,payload.video_ids)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        manager.wake.set()
        return result

    @app.post('/api/subscriptions/{subscription_id}/videos/{video_id}/download',status_code=201)
    async def download_subscription_video(subscription_id: UUID,video_id: UUID,payload: SubscriptionDownloadInput,account=Depends(user)):
        try:return queue_video(store,manager,subscription_id,video_id,payload.redownload)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except DownloadConflict as exc:raise HTTPException(409,str(exc)) from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @app.delete('/api/subscriptions/{subscription_id}/videos/{video_id}')
    def delete_subscription_video(subscription_id: UUID,video_id: UUID,account=Depends(user)):
        try:return catalog.delete_record(subscription_id,video_id)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc

    def nfo_response(action,*args):
        try:return action(*args)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except NfoConflict as exc:raise HTTPException(409,str(exc)) from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        except OSError as exc:raise HTTPException(409,'NFO 文件当前无法读写，请刷新后重试') from exc

    @app.get('/api/subscriptions/{subscription_id}/videos/{video_id}/nfo/exists')
    def subscription_nfo_exists(subscription_id: UUID,video_id: UUID,account=Depends(user)):
        return nfo_response(nfo.exists,subscription_id,video_id)

    @app.get('/api/subscriptions/{subscription_id}/videos/{video_id}/nfo')
    def subscription_nfo_read(subscription_id: UUID,video_id: UUID,account=Depends(user)):
        return nfo_response(nfo.read,subscription_id,video_id)

    @app.put('/api/subscriptions/{subscription_id}/videos/{video_id}/nfo')
    def subscription_nfo_write(subscription_id: UUID,video_id: UUID,payload:NfoInput,account=Depends(user)):
        return nfo_response(nfo.save,subscription_id,video_id,payload)

    def browser_call(error_status=409):
        class Guard:
            def __enter__(self):return self
            def __exit__(self,kind,exc,trace):
                if isinstance(exc,BrowserLoginError):raise HTTPException(error_status,str(exc)) from exc
                if isinstance(exc,ValueError):raise HTTPException(422,str(exc)) from exc
                return False
        return Guard()

    @app.get('/api/browser')
    async def browser_status(account=Depends(user)):
        return await browser.status()

    @app.post('/api/browser/{platform}/login')
    async def browser_login(platform: str,account=Depends(user)):
        with browser_call():return await browser.start(platform)

    @app.post('/api/browser/heartbeat')
    async def browser_heartbeat(account=Depends(user)):
        with browser_call():return browser.heartbeat()

    @app.post('/api/browser/{platform}/save')
    async def browser_save(platform: str,account=Depends(user)):
        with browser_call():
            result=await browser.save(platform)
            return {**result,'network':network.status()}

    @app.post('/api/browser/close')
    async def browser_close(account=Depends(user)):
        return await browser.close()

    @app.post('/api/subscriptions',status_code=201)
    async def add_subscription(payload: ProfileInput,account=Depends(user)):
        try:
            config=await profiles.resolve(payload)
            return subscriptions.add_config(config)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409,'该订阅已存在') from exc
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(504,'平台身份解析超时') from exc
        except PlatformError as exc:
            raise HTTPException(502,str(exc)) from exc

    @app.get('/api/subscriptions/{subscription_id}')
    def subscription_detail(subscription_id: UUID,account=Depends(user)):
        result=subscriptions.get(subscription_id)
        if result is None:raise HTTPException(404,'订阅不存在')
        return catalog.decorate(result)

    @app.patch('/api/subscriptions/{subscription_id}')
    def edit_subscription(subscription_id: UUID,payload: SubscriptionEdit,account=Depends(user)):
        try:result=subscriptions.edit(subscription_id,payload)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        if result is None:raise HTTPException(404,'订阅不存在')
        return result

    @app.delete('/api/subscriptions/{subscription_id}')
    def delete_subscription(subscription_id: UUID,account=Depends(user)):
        if not subscriptions.delete(subscription_id):raise HTTPException(404,'订阅不存在')
        return {'ok':True}

    @app.get('/api/backup/subscriptions')
    def export_subscriptions(account=Depends(user)):
        return subscriptions.export()

    @app.get('/api/live/subscriptions')
    def live_subscription_list(account=Depends(user)):
        return {'items':live_subscriptions.list()}

    @app.patch('/api/live/subscriptions/{subscription_id}')
    async def live_subscription_edit(subscription_id: UUID,payload: LiveEdit,account=Depends(user)):
        try:
            live_subscriptions.edit(subscription_id,payload)
            await live_monitor.reconcile()
            return next(item for item in live_subscriptions.list() if item['id']==str(subscription_id))
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @app.post('/api/live/subscriptions/{subscription_id}/check')
    async def check_live_room(subscription_id:UUID,account=Depends(user)):
        try:return await live_subscriptions.check(subscription_id,live_detector,network)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        except RoomDetectionError as exc:raise HTTPException(502,str(exc)) from exc
        except RoomCheckBusy as exc:raise HTTPException(409,'该直播间正在检测，请稍后刷新') from exc

    @app.post('/api/live/subscriptions/{subscription_id}/stream')
    async def resolve_live_stream(subscription_id:UUID,account=Depends(user)):
        row=store.one('SELECT config FROM live_subscriptions WHERE id=?',(str(subscription_id),))
        if row is None:raise HTTPException(404,'直播订阅不存在')
        config=json.loads(row['config'])
        try:return await live_detector.stream(config,network.for_url(config['room_url']))
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        except RoomDetectionError as exc:raise HTTPException(502,str(exc)) from exc

    @app.post('/api/live/subscriptions/{subscription_id}/record/start',status_code=201)
    async def start_live_record(subscription_id:UUID,account=Depends(user)):
        try:return await live_recording.start(subscription_id)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        except RecordingConflict as exc:raise HTTPException(409,str(exc)) from exc
        except RoomDetectionError as exc:raise HTTPException(502,str(exc)) from exc
        except OSError as exc:raise HTTPException(503,'录制进程当前无法启动') from exc

    @app.post('/api/live/subscriptions/{subscription_id}/record/stop')
    async def stop_live_record(subscription_id:UUID,account=Depends(user)):
        try:return await live_recording.stop(subscription_id)
        except RecordingConflict as exc:raise HTTPException(409,str(exc)) from exc

    @app.get('/api/live/subscriptions/{subscription_id}/records')
    def live_record_history(subscription_id:UUID,account=Depends(user)):
        try:return {'items':live_recording.items(subscription_id)}
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc

    @app.get('/api/live/records/{record_id}/download')
    def live_record_file(record_id:UUID,account=Depends(user)):
        try:return FileResponse(live_recording.path(record_id),filename='record.ts')
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc

    @app.get('/api/backup/live_subscriptions')
    def export_live_subscription_backup(account=Depends(user)):
        return live_subscriptions.export()

    @app.post('/api/backup/live_subscriptions/import')
    async def import_live_subscription_backup(payload:LiveImport,account=Depends(user)):
        return await live_subscriptions.import_config(payload.subscriptions)

    @app.post('/api/backup/subscriptions/import')
    def import_subscriptions(payload: SubscriptionImport,account=Depends(user)):
        return subscriptions.import_config(payload.subscriptions)

    @app.put('/api/settings')
    async def update_settings(payload: SettingsInput, account=Depends(user)):
        with store.connect() as db:
            db.execute('UPDATE settings SET value=? WHERE key="concurrency"', (str(payload.concurrency),))
            if payload.sync_concurrency is not None:
                db.execute('INSERT INTO settings(key,value) VALUES ("sync_concurrency",?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (str(payload.sync_concurrency),))
        manager.wake.set()
        await catalog.gate.poke()
        return settings(account)

    @app.get('/api/system/health')
    def health():
        return {'status': 'ok', 'version': app.version}

    @app.get('/api/capabilities')
    def capabilities(account=Depends(user)):
        return {'license': 'MIT', 'items': [
            {'id':'downloads','name':'媒体下载与任务管理','status':'available','phase':1},
            {'id':'files','name':'文件管理与媒体播放','status':'available','phase':1},
            {'id':'subscriptions','name':'作者订阅与自动下载','status':'partial','phase':2},
            {'id':'live','name':'直播录制与弹幕','status':'partial','phase':3},
            {'id':'notifications','name':'通知与机器人','status':'planned','phase':4},
            {'id':'ai','name':'AI 助手与精彩片段','status':'planned','phase':5},
        ]}

    if (frontend / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=frontend / 'assets'), name='assets')

    @app.get('/{route:path}', include_in_schema=False)
    def frontend_route(route: str):
        if route.startswith('api/'):
            raise HTTPException(404, '接口不存在')
        if (frontend / 'index.html').is_file():
            return FileResponse(frontend / 'index.html')
        return JSONResponse({'message':'前端尚未构建，请在 frontend 目录执行 npm install 和 npm run build'}, status_code=503)

    return app


app = create_app()
