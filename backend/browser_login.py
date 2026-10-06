"""Embedded browser used to log in to a platform and keep its Cookie.

One shared Chrome with a persistent user directory is started on demand when the user presses "login",
shown to the user (Docker: Xvfb + noVNC inside the page), kept alive by a 10 s heartbeat and closed
explicitly or when idle; the platform Cookie is then stored in the normal Cookie settings.

How it runs:
  * desktop mode - a visible Chrome window that uses its OWN user directory (data/browser/chrome-profile),
    never the user's everyday Chrome profile.
  * docker mode  - the same Chrome on a virtual display; the UI embeds it through noVNC (see deploy/docker).
Either way the browser is driven only through Chrome's DevTools protocol on a random 127.0.0.1 port, and
only the Cookies of the platform's own domains are read.
"""
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websockets


class BrowserLoginError(Exception):pass


class Platform:
    def __init__(self, label, login_url, domains, auth_cookies):
        self.label, self.login_url, self.domains, self.auth_cookies = label, login_url, tuple(domains), tuple(auth_cookies)

    def owns(self, domain):
        domain = (domain or '').lstrip('.').lower()
        return any(domain == d or domain.endswith('.' + d) for d in self.domains)


# Add a platform here (and a Cookie slot of the same name in network.PLATFORMS) to reuse the login flow.
PLATFORMS = {
    'douyin': Platform('抖音', 'https://www.douyin.com/', ('douyin.com',), ('sessionid', 'sessionid_ss')),
}

CHROME_CANDIDATES = {
    'nt': [r'%PROGRAMFILES%\Google\Chrome\Application\chrome.exe', r'%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe',
           r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'],
    'posix': ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', 'google-chrome', 'google-chrome-stable',
              'chromium', 'chromium-browser'],
}
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
LOCKS = ('SingletonLock', 'SingletonSocket', 'SingletonCookie', 'DevToolsActivePort')


def find_chrome(explicit=None):
    candidates = [explicit or os.environ.get('HARBOR_CHROME')] + CHROME_CANDIDATES['nt' if os.name == 'nt' else 'posix']
    for candidate in filter(None, candidates):
        candidate = os.path.expandvars(candidate)
        found = candidate if os.path.isfile(candidate) else shutil.which(candidate)
        if found:return found
    return None


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class BrowserLogin:
    def __init__(self, data_dir, network, mode=None, chrome=None, display=None, headless=False,
                 idle_timeout=600, clock=time.monotonic, busy=lambda: 0):
        self.root = Path(data_dir) / 'browser'
        self.profile = self.root / 'chrome-profile'
        self.network = network
        self.mode = (mode or os.environ.get('HARBOR_BROWSER_MODE') or 'desktop').lower()
        if self.mode not in ('desktop', 'docker'):raise ValueError('HARBOR_BROWSER_MODE 只能是 desktop 或 docker')
        self.chrome = chrome
        self.display = display or os.environ.get('HARBOR_DISPLAY') or ':99'
        self.headless, self.idle_timeout, self.clock, self.busy = headless, idle_timeout, clock, busy
        self.process = None
        self.port = None
        self.platform = None
        self.heartbeat_at = None
        self.lock = asyncio.Lock()
        self.watch = None

    # ---- process lifecycle -------------------------------------------------
    def running(self):
        return self.process is not None and self.process.returncode is None

    def command(self, platform):
        chrome = find_chrome(self.chrome)
        if not chrome:raise BrowserLoginError('没有找到 Chrome。请安装 Google Chrome，或用环境变量 HARBOR_CHROME 指定可执行文件路径。')
        args = [chrome, f'--user-data-dir={self.profile}', f'--remote-debugging-port={self.port}',
                '--remote-debugging-address=127.0.0.1', f'--remote-allow-origins=http://127.0.0.1:{self.port}',
                '--no-first-run', '--no-default-browser-check', '--disable-search-engine-choice-screen']
        if self.mode == 'docker':args += ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1280,1024', '--start-maximized']
        if self.headless:args.append('--headless=new')
        return args + [platform.login_url]

    def clear_stale_locks(self):
        """A crashed or force-killed Chrome leaves singleton files that block the next start."""
        for name in LOCKS:
            try:(self.profile / name).unlink()
            except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):pass

    async def launch(self, platform):
        if self.mode == 'docker':
            socket_path = Path('/tmp/.X11-unix') / f'X{self.display.lstrip(":").split(".")[0]}'
            if os.name == 'posix' and not socket_path.exists():
                raise BrowserLoginError(f'虚拟显示 {self.display} 未就绪（Xvfb 未启动或已崩溃），无法打开内嵌浏览器')
        self.profile.mkdir(parents=True, exist_ok=True)
        self.clear_stale_locks()
        self.port = free_port()
        environment = {**os.environ, **({'DISPLAY': self.display} if self.mode == 'docker' else {})}
        kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        self.process = await asyncio.create_subprocess_exec(*self.command(platform), env=environment, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **kwargs)
        for _ in range(100):
            if self.process.returncode is not None:
                self.process = None
                raise BrowserLoginError('Chrome 启动后立即退出，请检查是否有另一个 Chrome 占用了专用用户目录')
            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    if (await client.get(f'http://127.0.0.1:{self.port}/json/version')).status_code == 200:return
            except httpx.HTTPError:pass
            await asyncio.sleep(0.2)
        await self.terminate()
        raise BrowserLoginError('Chrome 调试接口没有就绪')

    async def terminate(self):
        process, self.process = self.process, None
        if process is None or process.returncode is not None:return
        if os.name == 'nt':
            killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F',
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await killer.wait()
        else:
            import signal
            try:os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:pass
        try:await asyncio.wait_for(process.wait(), 8)
        except TimeoutError:
            process.kill();await process.wait()

    # ---- DevTools ----------------------------------------------------------
    async def cdp(self, method, params=None, timeout=10):
        if not self.running():raise BrowserLoginError('内嵌浏览器没有运行')
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                url = (await client.get(f'http://127.0.0.1:{self.port}/json/version')).json()['webSocketDebuggerUrl']
            async with websockets.connect(url, open_timeout=timeout, max_size=32 * 1024 * 1024) as socket:
                await socket.send(json.dumps({'id': 1, 'method': method, 'params': params or {}}))
                async with asyncio.timeout(timeout):
                    while True:
                        reply = json.loads(await socket.recv())
                        if reply.get('id') == 1:
                            if 'error' in reply:raise BrowserLoginError('浏览器拒绝了请求：' + str(reply['error'].get('message')))
                            return reply.get('result') or {}
        except (httpx.HTTPError, OSError, TimeoutError, websockets.WebSocketException, KeyError, ValueError) as exc:
            raise BrowserLoginError('无法连接内嵌浏览器，浏览器可能已被关闭') from exc

    async def platform_cookies(self, platform):
        result = await self.cdp('Storage.getCookies')
        return [c for c in result.get('cookies', []) if platform.owns(c.get('domain'))]

    # ---- public operations -------------------------------------------------
    def platform_for(self, key):
        if key not in PLATFORMS:raise ValueError('该平台暂不支持内嵌浏览器登录')
        return PLATFORMS[key]

    async def start(self, key):
        platform = self.platform_for(key)
        async with self.lock:
            if self.running():
                if self.platform != key:
                    # one shared browser: open the other platform in a new tab
                    async with httpx.AsyncClient(timeout=5) as client:
                        await client.put(f'http://127.0.0.1:{self.port}/json/new?{platform.login_url}')
            else:
                await self.launch(platform)
            self.platform = key
            self.heartbeat_at = self.clock()
            if self.mode == 'docker' and (self.watch is None or self.watch.done()):
                self.watch = asyncio.create_task(self.idle_watch())
        return await self.status()

    def heartbeat(self):
        if not self.running():raise BrowserLoginError('内嵌浏览器没有运行')
        self.heartbeat_at = self.clock()
        return {'ok': True}

    async def idle_watch(self):
        while self.running():
            await asyncio.sleep(min(15, max(1, self.idle_timeout / 4)))
            if self.heartbeat_at is not None and self.clock() - self.heartbeat_at > self.idle_timeout and not self.busy():
                await self.close()
                return

    async def status(self):
        running = self.running()
        logged_in = None
        if running and self.platform:
            try:
                names = {c['name'] for c in await self.platform_cookies(PLATFORMS[self.platform])}
                logged_in = any(n in names for n in PLATFORMS[self.platform].auth_cookies)
            except BrowserLoginError:running = self.running()
        if not running and self.process is not None and self.process.returncode is not None:self.process = None
        return {'mode': self.mode, 'running': running, 'platform': self.platform if running else None,
                'logged_in': logged_in if running else None, 'chrome_found': bool(find_chrome(self.chrome)),
                'platforms': {k: p.label for k, p in PLATFORMS.items()}, 'active_tasks': self.busy(),
                'idle_timeout': self.idle_timeout if self.mode == 'docker' else None,
                'embedded_path': '/novnc/vnc_lite.html' if self.mode == 'docker' else None}

    async def save(self, key):
        """Store the logged-in Cookie of this platform; returns only non-secret facts."""
        platform = self.platform_for(key)
        cookies = await self.platform_cookies(platform)
        if not any(c['name'] in platform.auth_cookies for c in cookies):
            raise BrowserLoginError(f'尚未检测到{platform.label}登录状态，请先在浏览器中完成登录')
        # Real browsers hold nameless or odd cookies (e.g. an empty-name one on douyin.com) that cannot be
        # written in a Cookie header; they carry no login state, so leave them out instead of failing the save.
        usable = [c for c in cookies if HEADER_NAME.fullmatch(c.get('name') or '') and c.get('value') is not None
                  and not any(ch in c['value'] for ch in chr(9)+chr(13)+chr(10)+';')]
        header = '; '.join(f"{c['name']}={c['value']}" for c in usable)
        self.network.save_cookie(key, header)
        return {'saved': True, 'cookie_count': len(usable), 'skipped': len(cookies) - len(usable), 'platform': key}

    async def close(self):
        async with self.lock:
            watch, self.watch = self.watch, None
            if watch and watch is not asyncio.current_task():watch.cancel()
            await self.terminate()
            self.platform = None
            self.heartbeat_at = None
        return {'running': False}
