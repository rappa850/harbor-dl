import asyncio
import tempfile
import unittest
from pathlib import Path
from backend.store import Store
from backend.live_config import LiveSubscriptions,LiveEdit,RoomCheckBusy
from backend.live_monitor import LiveMonitor,check_interval
from tests.test_task_lifecycle import until
from fastapi.testclient import TestClient
from backend.app import create_app


class Network:
    def for_url(self,url):return {}


class Detector:
    def __init__(self):self.calls=[];self.block=None;self.fail=False
    async def detect(self,config,network):
        self.calls.append(config['room_url'])
        if self.block:await self.block.wait()
        if self.fail:raise RuntimeError('fixture failure')
        return {'room_id':config['room_url'].split('/')[-1],'is_live':True,'anchor_name':'fixture'}


class LiveMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'store.sqlite3')
        self.subscriptions=LiveSubscriptions(self.store);self.detector=Detector();self.network=Network()
        self.monitor=LiveMonitor(self.subscriptions,self.detector,self.network,jitter=lambda interval:.02,startup_spacing=0)

    async def asyncTearDown(self):
        await self.monitor.stop();self.temp.cleanup()

    async def add(self,room='1',**fields):
        await self.subscriptions.import_config([{'platform':'bilibili','room_url':'https://live.bilibili.com/'+room,**fields}])
        return next(item['id'] for item in self.subscriptions.list() if item['room_url'].endswith('/'+room))

    async def test_restart_loads_enabled_rooms_regardless_of_auto_record_and_no_duplicate_registration(self):
        scope=await self.add(auto_record=False)
        paused=await self.add('2',monitor_enabled=False)
        await self.monitor.start();await until(lambda:len(self.detector.calls)>=2)
        self.assertEqual(set(self.detector.calls),{'https://live.bilibili.com/1'})
        task=self.monitor.tasks[scope]
        await self.monitor.start();await self.monitor.register(scope,'unused','bilibili',60)
        self.assertIs(self.monitor.tasks[scope],task);self.assertNotIn(paused,self.monitor.tasks)
        self.assertTrue(self.store.one('SELECT * FROM live_room_states WHERE subscription_id=?',(scope,)))
        await self.monitor.stop()
        await self.monitor.start();await until(lambda:len(self.detector.calls)>=3)
        self.assertIn(scope,self.monitor.tasks)

    async def test_pause_cancels_inflight_check_and_resume_reloads_config(self):
        scope=await self.add();self.detector.block=asyncio.Event()
        await self.monitor.start();await until(lambda:len(self.detector.calls)==1)
        self.assertIn(scope,self.subscriptions.active_checks)
        self.subscriptions.edit(scope,LiveEdit(monitor_enabled=False))
        await self.monitor.reconcile()
        self.assertNotIn(scope,self.monitor.tasks);self.assertNotIn(scope,self.subscriptions.active_checks)
        self.assertIsNone(self.store.one('SELECT * FROM live_room_states WHERE subscription_id=?',(scope,)))
        self.detector.block=None
        self.subscriptions.edit(scope,LiveEdit(monitor_enabled=True,check_interval=900))
        await self.monitor.reconcile();await until(lambda:len(self.detector.calls)>=2)
        self.assertEqual(self.monitor.status(scope,self.monitor.config(scope))['effective_check_interval'],600)

    async def test_failure_keeps_previous_snapshot_and_periodic_check_recovers(self):
        scope=await self.add()
        await self.subscriptions.check(scope,self.detector,self.network)
        previous=self.store.all('SELECT * FROM live_room_states')
        self.detector.fail=True
        await self.monitor.start();await until(lambda:scope in self.monitor.errors)
        self.assertEqual(self.store.all('SELECT * FROM live_room_states'),previous)
        self.detector.fail=False
        await until(lambda:scope not in self.monitor.errors)
        self.assertTrue(self.monitor.tasks[scope] and not self.monitor.tasks[scope].done())

    async def test_manual_check_overlap_and_shutdown_release_busy_state(self):
        scope=await self.add();self.detector.block=asyncio.Event()
        await self.monitor.start();await until(lambda:scope in self.subscriptions.active_checks)
        with self.assertRaises(RoomCheckBusy):await self.subscriptions.check(scope,self.detector,self.network)
        active=self.monitor.tasks[scope]
        await self.monitor.stop()
        self.assertTrue(active.done());self.assertFalse(self.monitor.running)
        self.assertFalse(self.subscriptions.active_checks)
        self.assertEqual(self.store.all('SELECT * FROM live_room_states'),[])

    def test_recovered_interval_bounds(self):
        for value,expected in [(None,60),(0,60),('bad',60),(1,10),(60,60),(900,600)]:
            self.assertEqual(check_interval(value),expected)

    def test_app_lifespan_registration_pause_and_shutdown(self):
        app=create_app(self.temp.name,live_detector=self.detector)
        with TestClient(app) as client:
            client.post('/api/setup',json={'username':'admin','password':'test-password-123'})
            result=client.post('/api/backup/live_subscriptions/import',json={'subscriptions':[
                {'platform':'bilibili','room_url':'https://live.bilibili.com/1','auto_record':False}]}).json()
            self.assertEqual(result['success'],1);self.assertEqual(result['monitor_warnings'],[])
            item=client.get('/api/live/subscriptions').json()['items'][0]
            self.assertTrue(item['runtime']['monitor_running'])
            self.assertTrue(item['runtime']['scheduler_running'])
            self.assertTrue(item['runtime']['recording_available'])
            paused=client.patch('/api/live/subscriptions/'+item['id'],json={'monitor_enabled':False})
            self.assertFalse(paused.json()['runtime']['monitor_running'])
            self.assertTrue(app.state.live_monitor.running)
        self.assertFalse(app.state.live_monitor.running)
        self.assertFalse(app.state.live_monitor.tasks)
