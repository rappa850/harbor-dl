"""Own FFmpeg processes, recording history and current-session stop markers."""
import asyncio
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from .downloads import now


class RecordingConflict(Exception):pass


def ffmpeg_executable():
    configured=os.environ.get('HARBOR_FFMPEG')
    if configured and Path(configured).is_file():return configured
    executable=shutil.which('ffmpeg')
    if executable:return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError,RuntimeError,OSError):return None


class LiveRecording:
    def __init__(self,store,root,detector,network,command_builder=None,clock=None):
        self.store,self.root,self.detector,self.network=store,Path(root).resolve(),detector,network
        self.root.mkdir(parents=True,exist_ok=True)
        self.command_builder=command_builder;self.active={};self.starting=set();self.pending={};self.closing=False
        self.manual_stopped=set()
        self.clock=clock or time.monotonic

    async def check_growth(self,scope):
        scope=str(scope);context=self.active.get(scope)
        if not context or context['stop_requested']:return False
        path=context['path']
        size=path.stat().st_size if path.is_file() else 0
        # The captured old scheduler only enters this check for positive file sizes.
        if size<=0:
            context.pop('last_size',None);context.pop('stale_since',None)
            return False
        previous=context.get('last_size');context['last_size']=size
        if previous is None or previous!=size:
            context.pop('stale_since',None)
            return False
        sampled=self.clock()
        context.setdefault('stale_since',sampled)
        if sampled-context['stale_since']>=30:
            await self.stop(scope,manual=False)
            return True
        return False

    def options_error(self,config):
        if config['output_format'].lower()!='ts' or config['split_enabled']:
            return '当前录制仅支持 TS 不分段，其他录制选项暂未支持'
        if config.get('max_duration'):return '最大录制时长选项暂未支持'
        for field in ('generate_subtitle','auto_convert_mp4'):
            if config.get(field) in (True,'true'):return '该录制后处理选项暂未支持'
        return None

    async def observe(self,scope,result,config):
        scope=str(scope)
        # Failed checks never reach this method: they must not clear a stop marker.
        stopped=await self.check_growth(scope)
        if result.get('is_live') is False:
            self.manual_stopped.discard(scope)
            return
        # A stalled recording is retried on the next successful cycle, not this one.
        if stopped:return
        if result.get('is_live') is not True or not config['auto_record']:return
        if scope in self.manual_stopped or scope in self.active or scope in self.starting:return
        extra=config.get('extra_data')
        if isinstance(extra,str):
            try:extra=json.loads(extra)
            except (ValueError,TypeError):raise ValueError('直播扩展配置无效')
        if config.get('record_windows') or isinstance(extra,dict) and extra.get('record_windows'):
            raise ValueError('自动录制时间窗暂未支持，当前配置不能自动开录')
        await self.start(scope,automatic=True)

    async def restore(self):
        self.closing=False
        self.manual_stopped.clear()
        with self.store.connect() as db:
            db.execute('UPDATE live_records SET status=?,end_time=?,error=? WHERE status=?',
                       ('failed',now(),'服务中断，录制进程未能继续','recording'))

    def items(self,scope):
        if not self.store.one('SELECT id FROM live_subscriptions WHERE id=?',(str(scope),)):raise LookupError('直播订阅不存在')
        return self.store.all('SELECT * FROM live_records WHERE subscription_id=? ORDER BY start_time DESC,id',(str(scope),))

    def path(self,record_id):
        row=self.store.one('SELECT * FROM live_records WHERE id=?',(str(record_id),))
        if row is None:raise LookupError('录制记录不存在')
        path=(self.root/row['file_path']).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():raise LookupError('录制文件不存在')
        return path

    async def start(self,scope,automatic=False):
        scope=str(scope)
        if self.closing:raise RecordingConflict('录制服务正在关闭')
        if scope in self.active or scope in self.starting:raise RecordingConflict('该直播间已有正在启动或运行的录制')
        self.starting.add(scope)
        self.pending[scope]=asyncio.current_task()
        try:
            row=self.store.one('SELECT config FROM live_subscriptions WHERE id=?',(scope,))
            if row is None:raise LookupError('直播订阅不存在')
            config=json.loads(row['config'])
            error=self.options_error(config)
            if error:raise ValueError(error)
            executable=ffmpeg_executable()
            if not executable and not self.command_builder:raise ValueError('FFmpeg 不可用')
            stream=await self.detector.stream(config,self.network.for_url(config['room_url']))
            if not stream['is_live'] or not stream.get('url'):raise RecordingConflict('直播间当前没有可录制的直播流')
            if self.closing:raise RecordingConflict('录制服务正在关闭')
            if automatic:
                current=json.loads(self.store.one('SELECT config FROM live_subscriptions WHERE id=?',(scope,))['config'])
                if not current['auto_record'] or not current['monitor_enabled'] or current!=config or scope in self.manual_stopped:
                    raise RecordingConflict('配置或本场停止状态已变化，等待后续检测')
            record_id=str(uuid.uuid4());folder=self.root/record_id;folder.mkdir()
            path=folder/'record.ts'
            headers=stream.get('headers') or {}
            if any('\r' in str(value) or '\n' in str(value) for value in headers.values()):raise ValueError('媒体请求头无效')
            args=[executable,'-hide_banner','-loglevel','error','-n']
            if headers:args+=['-headers',''.join(f'{name}: {value}\r\n' for name,value in headers.items())]
            proxy=config.get('proxy') or self.network.for_url(config['room_url']).get('proxy')
            if proxy:args+=['-http_proxy',proxy]
            args+=['-i',stream['url'],'-map','0:v?','-map','0:a?','-c','copy','-f','mpegts',str(path)]
            if self.command_builder:args=self.command_builder(stream,path,args)
            launch=asyncio.create_task(asyncio.create_subprocess_exec(*args,stdin=asyncio.subprocess.PIPE,
                                                        stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE))
            try:process=await asyncio.shield(launch)
            except BaseException:
                process=await launch
                process.kill();await process.communicate();raise
            try:
                with self.store.connect() as db:
                    db.execute('INSERT INTO live_records(id,subscription_id,platform,anchor_name,room_id,quality,status,start_time,file_path) '
                               'VALUES (?,?,?,?,?,?,?,?,?)',(record_id,scope,config['platform'],stream.get('anchor_name') or '',
                                stream.get('room_id') or '',config['quality'],'recording',now(),path.relative_to(self.root).as_posix()))
            except BaseException:
                process.kill();await process.communicate();raise
            context={'id':record_id,'process':process,'path':path,'started':time.monotonic(),'stop_requested':False,
                     'automatic':automatic}
            self.active[scope]=context
            if not automatic:self.manual_stopped.discard(scope)
            context['watcher']=asyncio.create_task(self._watch(scope,context))
            return self.store.one('SELECT * FROM live_records WHERE id=?',(record_id,))
        finally:self.starting.discard(scope);self.pending.pop(scope,None)

    async def _watch(self,scope,context):
        process=context['process']
        # Drain stderr without persisting URLs or unbounded subprocess output.
        while await process.stderr.read(8192):pass
        code=await process.wait();path=context['path']
        size=path.stat().st_size if path.is_file() else 0
        status=('stopped' if context['stop_requested'] else 'completed') if code==0 and size else 'failed'
        with self.store.connect() as db:
            db.execute('UPDATE live_records SET status=?,end_time=?,duration=?,file_size=?,error=? WHERE id=?',
                       (status,now(),time.monotonic()-context['started'],size,
                        '' if status!='failed' else f'录制未正常完成（退出码 {code}）',context['id']))
        if self.active.get(scope) is context:self.active.pop(scope,None)

    async def stop(self,scope,manual=True):
        scope=str(scope);context=self.active.get(scope)
        if context is None:raise RecordingConflict('该直播间没有活动录制')
        if manual:self.manual_stopped.add(scope)
        context['stop_requested']=True;process=context['process']
        if process.returncode is None:
            try:
                process.stdin.write(b'q\n');await process.stdin.drain()
            except (BrokenPipeError,ConnectionResetError):pass
            try:await asyncio.wait_for(asyncio.shield(context['watcher']),10)
            except asyncio.TimeoutError:
                if process.returncode is None:process.kill()
        await context['watcher']
        return self.store.one('SELECT * FROM live_records WHERE id=?',(context['id'],))

    async def close(self):
        self.closing=True
        pending=list(self.pending.values())
        for task in pending:task.cancel()
        if pending:await asyncio.gather(*pending,return_exceptions=True)
        for scope in list(self.active):
            try:await self.stop(scope,manual=False)
            except RecordingConflict:pass
