"""Periodic author-subscription checks (incremental discovery + auto download).

One sequential loop: due subscriptions are checked one at a time with a pause in between, so many
subscriptions on one platform never fire together. A failed check is recorded and retried after the
subscription's own interval rather than immediately.
"""
import asyncio
import logging
import random
import time
from datetime import datetime

from .subscription_catalog import SyncBusy
from .subscription_platforms import PlatformError

log = logging.getLogger('harbor.subscriptions')


class SubscriptionScheduler:
    def __init__(self, subscriptions, catalog, tick=60, startup_delay=15, gap=(3, 8), clock=time.time, sleep=asyncio.sleep):
        self.subscriptions, self.catalog = subscriptions, catalog
        self.tick_seconds, self.startup_delay, self.gap = tick, startup_delay, gap
        self.clock, self.sleep = clock, sleep
        self.task = None
        self.stopping = False

    def due(self):
        """Subscriptions whose adapter supports checks, that are active and past their interval."""
        result = []
        for config in self.subscriptions.list():
            interval = config.get('update_interval') or 0
            adapter = self.catalog.adapter(config)
            if config.get('status') != 'active' or interval <= 0 or adapter is None or not adapter.supports_check:
                continue
            state = self.catalog.state(config['id'])
            last = datetime.fromisoformat(state['last_checked_at']).timestamp() if state and state['last_checked_at'] else 0
            if self.clock() - last >= interval:
                result.append((last, config['id']))
        return [item[1] for item in sorted(result)]

    async def run_once(self):
        """Check every due subscription; returns how many were attempted."""
        attempted = 0
        for subscription_id in self.due():
            if self.stopping:break
            if attempted:await self.sleep(random.uniform(*self.gap))
            try:
                await self.catalog.check(subscription_id, mode='scheduled')
            except SyncBusy:continue
            except LookupError:continue
            except (ValueError, PlatformError, TimeoutError) as exc:
                log.warning('subscription %s check failed: %s', subscription_id, exc)
            except Exception:
                log.exception('subscription %s check crashed', subscription_id)
                self.catalog.record_state(subscription_id, 'scheduled', '检查更新时发生内部错误')
            attempted += 1
        return attempted

    async def loop(self):
        await self.sleep(self.startup_delay)
        while not self.stopping:
            try:await self.run_once()
            except Exception:log.exception('subscription scheduler tick failed')
            await self.sleep(self.tick_seconds)

    async def start(self):
        self.stopping = False
        self.task = asyncio.create_task(self.loop())

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
