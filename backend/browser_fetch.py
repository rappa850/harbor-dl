"""Run a request from inside a real (headless, throwaway-profile) Chrome page.

Some platforms sign and cookie their web API with in-page scripts that are not worth re-implementing: the
page's own SDK adds the signature to a plain fetch(). The browser used here is anonymous - a fresh temporary
profile that is deleted afterwards - so no login or saved Cookie is involved.
"""
import asyncio
import json
import os
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

import httpx
import websockets

from .browser_login import find_chrome, free_port


class BrowserFetchError(Exception):pass


_slots = asyncio.Semaphore(2)


async def kill_tree(process):
    if process.returncode is not None:return
    if os.name == 'nt':
        killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F',
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        import signal
        try:os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:pass
    try:await asyncio.wait_for(process.wait(), 8)
    except TimeoutError:pass


def proxy_argument(proxy):
    if not proxy:return []
    parsed = urlsplit(proxy)
    if parsed.username or parsed.password:
        raise BrowserFetchError('内嵌浏览器不支持带账号密码的代理，请改用无需认证的代理地址')
    return [f'--proxy-server={parsed.scheme}://{parsed.hostname}:{parsed.port}']


async def fetch_in_page(page_url, expression, judge, proxy='', timeout=40, interval=1.5, chrome=None, container=None):
    """Open page_url, then evaluate `expression` (a JS promise returning a string) until judge(value) decides.

    judge(value) -> ('ok', result) | ('retry', None) | ('fail', message)
    """
    path = find_chrome(chrome)
    if not path:raise BrowserFetchError('没有找到 Chrome。请安装 Google Chrome，或用环境变量 HARBOR_CHROME 指定可执行文件路径。')
    container = os.environ.get('HARBOR_BROWSER_MODE', '').lower() == 'docker' if container is None else container
    async with _slots:
        with tempfile.TemporaryDirectory(prefix='harbor-anon-', ignore_cleanup_errors=True) as profile:
            port = free_port()
            args = [path, f'--user-data-dir={profile}', f'--remote-debugging-port={port}', '--remote-debugging-address=127.0.0.1',
                    f'--remote-allow-origins=http://127.0.0.1:{port}', '--headless=new', '--no-first-run',
                    '--no-default-browser-check', '--disable-gpu', '--mute-audio', *proxy_argument(proxy),
                    *(['--no-sandbox', '--disable-dev-shm-usage'] if container else []), 'about:blank']
            kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
            process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **kwargs)
            try:
                return await asyncio.wait_for(_drive(process, port, page_url, expression, judge, interval), timeout)
            except TimeoutError as exc:
                raise BrowserFetchError('浏览器取数超时，页面可能被风控拦截或网络不可用') from exc
            finally:
                await kill_tree(process)


async def _drive(process, port, page_url, expression, judge, interval):
    target = None
    async with httpx.AsyncClient(timeout=3) as client:
        for _ in range(100):
            if process.returncode is not None:raise BrowserFetchError('Chrome 启动后立即退出')
            try:
                pages = [t for t in (await client.get(f'http://127.0.0.1:{port}/json/list')).json() if t.get('type') == 'page']
                if pages:target = pages[0]['webSocketDebuggerUrl'];break
            except (httpx.HTTPError, ValueError, KeyError):pass
            await asyncio.sleep(0.2)
    if target is None:raise BrowserFetchError('Chrome 调试接口没有就绪')
    async with websockets.connect(target, max_size=64 * 1024 * 1024, open_timeout=10) as socket:
        counter = 0

        async def call(method, params=None):
            nonlocal counter
            counter += 1
            ident = counter
            await socket.send(json.dumps({'id': ident, 'method': method, 'params': params or {}}))
            while True:
                reply = json.loads(await socket.recv())
                if reply.get('id') == ident:
                    if 'error' in reply:raise BrowserFetchError('浏览器拒绝了请求：' + str(reply['error'].get('message')))
                    return reply.get('result') or {}

        await call('Page.enable')
        await call('Page.navigate', {'url': page_url})
        await asyncio.sleep(interval * 2)       # let the page's scripts install their request signing
        while True:
            try:
                result = await call('Runtime.evaluate', {'expression': expression, 'awaitPromise': True, 'returnByValue': True})
                value = (result.get('result') or {}).get('value')
            except BrowserFetchError:value = None
            state, payload = judge(value)
            if state == 'ok':return payload
            if state == 'fail':raise BrowserFetchError(payload)
            await asyncio.sleep(interval)
