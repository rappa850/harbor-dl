import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from backend.live_recording import LiveRecording


class LiveGrowthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.tick=100.
        self.recorder=LiveRecording(None,self.root,None,None,clock=lambda:self.tick)
        self.path=self.root/'record.ts';self.path.write_bytes(b'media')
        self.context={'path':self.path,'stop_requested':False}
        self.recorder.active['room']=self.context
        async def stop(scope,manual=True):
            self.recorder.active.pop(scope)
        self.recorder.stop=AsyncMock(side_effect=stop)
        self.recorder.start=AsyncMock()
        self.config={'auto_record':True}

    async def asyncTearDown(self):self.temp.cleanup()

    async def test_offline_waits_for_unchanged_positive_file_at_30_second_boundary(self):
        self.recorder.manual_stopped.add('room')
        await self.recorder.observe('room',{'is_live':False},self.config)
        self.assertNotIn('room',self.recorder.manual_stopped)
        self.recorder.stop.assert_not_awaited()
        await self.recorder.observe('room',{'is_live':False},self.config)
        self.tick=129.999
        await self.recorder.observe('room',{'is_live':False},self.config)
        self.recorder.stop.assert_not_awaited()
        self.tick=130
        await self.recorder.observe('room',{'is_live':False},self.config)
        self.recorder.stop.assert_awaited_once_with('room',manual=False)
        self.recorder.start.assert_not_awaited()

    async def test_growth_resets_timer_and_offline_does_not_stop_growing_stream(self):
        await self.recorder.observe('room',{'is_live':False},self.config)
        await self.recorder.observe('room',{'is_live':False},self.config)
        self.tick=140;self.path.write_bytes(b'more media')
        await self.recorder.observe('room',{'is_live':False},self.config)
        self.assertNotIn('stale_since',self.context)
        self.recorder.stop.assert_not_awaited()
        await self.recorder.observe('room',{'is_live':False},self.config)
        self.tick=169.999
        await self.recorder.observe('room',{'is_live':False},self.config)
        self.recorder.stop.assert_not_awaited()
        self.tick=170
        await self.recorder.observe('room',{'is_live':False},self.config)
        self.recorder.stop.assert_awaited_once_with('room',manual=False)

    async def test_online_stall_stops_without_manual_mark_and_retries_next_cycle(self):
        await self.recorder.observe('room',{'is_live':True},self.config)
        await self.recorder.observe('room',{'is_live':True},self.config)
        self.tick=130
        await self.recorder.observe('room',{'is_live':True},self.config)
        self.recorder.stop.assert_awaited_once_with('room',manual=False)
        self.recorder.start.assert_not_awaited()
        self.assertFalse(self.recorder.manual_stopped)
        await self.recorder.observe('room',{'is_live':True},self.config)
        self.recorder.start.assert_awaited_once_with('room',automatic=True)

    async def test_empty_missing_replaced_file_and_stopping_context_do_not_false_stop(self):
        await self.recorder.check_growth('room');await self.recorder.check_growth('room')
        self.tick=200;self.path.unlink()
        self.assertFalse(await self.recorder.check_growth('room'))
        self.assertNotIn('stale_since',self.context)
        self.path.write_bytes(b'')
        self.assertFalse(await self.recorder.check_growth('room'))
        self.path.write_bytes(b'new file')
        self.assertFalse(await self.recorder.check_growth('room'))
        self.context['stop_requested']=True;self.tick=1000
        self.assertFalse(await self.recorder.check_growth('room'))
        self.recorder.stop.assert_not_awaited()
