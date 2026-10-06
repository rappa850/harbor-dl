"""Lifecycle-owned periodic checks; recording and notifications are separate."""
import asyncio
import json
import random
from .live_rooms import bilibili_room_id
from .live_config import RoomCheckBusy


def check_interval(value):
    try:value=int(value or 60)
    except (TypeError,ValueError):value=60
    return max(10,min(600,value))


class LiveMonitor:
    def __init__(self,subscriptions,detector,network,jitter=None,startup_spacing=1,recording=None):
        self.subscriptions,self.detector,self.network=subscriptions,detector,network
        self.jitter=jitter or (lambda interval:interval*random.uniform(.8,1.2))
        self.startup_spacing=startup_spacing
        self.recording=recording;self.recording_errors={}
        self.running=False;self.tasks={};self.wakes={};self.errors={}

    def config(self,scope):
        row=self.subscriptions.store.one('SELECT config FROM live_subscriptions WHERE id=?',(str(scope),))
        return json.loads(row['config']) if row else None

    def supported(self,config):
        try:
            if not config or config['platform']!='bilibili':return False
            bilibili_room_id(config['room_url']);return True
        except ValueError:return False

    def status(self,scope,config):
        task=self.tasks.get(str(scope));available=self.supported(config)
        return {'monitor_available':available,'monitor_running':bool(task and not task.done()),
                'scheduler_running':self.running,'effective_check_interval':check_interval(config['check_interval']),
                'recording_available':bool(available and self.recording and not self.recording.options_error(config)),
                'recording':bool(self.recording and str(scope) in self.recording.active),
                'manual_stopped':bool(self.recording and str(scope) in self.recording.manual_stopped),
                'recording_error':self.recording_errors.get(str(scope)), 'error':self.errors.get(str(scope)),
                'reason':'B 站 TS 自动开录及文件停滞收尾已接入；分段及后处理暂未支持' if available and self.recording
                         else 'B 站周期检测已接入；自动录制暂未接入' if available else '此平台直播监控和录制尚未接入'}

    async def start(self):
        if self.running:return
        self.running=True
        await self.reconcile(startup=True)

    async def stop(self):
        self.running=False
        tasks=list(self.tasks.values())
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        self.tasks.clear();self.wakes.clear()

    async def register(self,scope,url,platform,interval):
        config=self.config(scope)
        if not self.supported(config):raise ValueError('直播检测适配尚未接入')
        if not self.running:raise RuntimeError('周期检测服务尚未启动')
        if config['monitor_enabled']:self._spawn(str(scope))

    def _spawn(self,scope,delay=0):
        current=self.tasks.get(scope)
        if current and not current.done():return
        wake=asyncio.Event();self.wakes[scope]=wake
        self.tasks[scope]=asyncio.create_task(self._run(scope,wake,delay))

    async def reconcile(self,startup=False):
        if not self.running:return
        desired={item['id']:item for item in self.subscriptions.list()
                 if item['monitor_enabled'] and self.supported(item)}
        removed=[]
        for scope in list(self.tasks):
            if scope not in desired:
                task=self.tasks.pop(scope);task.cancel();removed.append(task)
                self.wakes.pop(scope,None)
        if removed:await asyncio.gather(*removed,return_exceptions=True)
        for index,scope in enumerate(sorted(desired)):
            if scope in self.tasks and not self.tasks[scope].done():
                if not startup:self.wakes[scope].set()
            else:self._spawn(scope,index*self.startup_spacing if startup else 0)

    async def _run(self,scope,wake,delay):
        if delay:await asyncio.sleep(delay)
        while self.running:
            config=self.config(scope)
            if not config or not config['monitor_enabled'] or not self.supported(config):return
            try:
                result=await self.subscriptions.check(scope,self.detector,self.network)
                self.errors.pop(scope,None)
                if self.recording:
                    # Reload after the network await: edits may disable automatic recording.
                    latest=self.config(scope)
                    if latest and latest['monitor_enabled']:
                        try:
                            await self.recording.observe(scope,result,latest)
                            self.recording_errors.pop(scope,None)
                        except asyncio.CancelledError:raise
                        except ValueError as error:self.recording_errors[scope]=str(error)
                        except Exception:self.recording_errors[scope]='录制启动或收尾检查失败，将在后续检测重试'
            except RoomCheckBusy:pass
            except asyncio.CancelledError:raise
            except Exception:self.errors[scope]='最近一次周期检测失败，上次成功结果保留'
            config=self.config(scope)
            if not config:return
            delay=self.jitter(check_interval(config['check_interval']))
            try:await asyncio.wait_for(wake.wait(),timeout=delay)
            except asyncio.TimeoutError:pass
            wake.clear()
