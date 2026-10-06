"""Local cover cache: remote cover links expire, so a copy is kept under a hashed directory tree.

A cover is keyed by the work's page URL (the same URL a download task carries), so subscription works,
manual downloads, redownloads and the media library all find the same file: covers/ab/cd/<sha256>.<ext>.
"""
import asyncio
import hashlib
import ipaddress
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx

MAX_BYTES = 8 * 1024 * 1024
TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif', 'image/avif': '.avif'}
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/141.0.0.0 Safari/537.36')
KEY = re.compile(r'[0-9a-f]{64}')


def key_for(work_url):
    return hashlib.sha256(work_url.strip().encode('utf-8')).hexdigest()


def public_url(value):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme not in ('http', 'https') or not host or parsed.username or parsed.password:
            return False
        if host == 'localhost' or host.endswith('.localhost'):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


class CoverCache:
    def __init__(self, root, transport=None):
        self.root, self.transport = Path(root).resolve(), transport
        self.pending = set()
        self.tasks = set()

    def folder(self, key):
        return self.root / key[:2] / key[2:4]

    def find(self, key):
        if not KEY.fullmatch(key):
            return None
        return next((p for p in self.folder(key).glob(f'{key}.*') if p.suffix != '.tmp'), None) \
            if self.folder(key).is_dir() else None

    def local(self, work_url):
        """Public path of the cached cover for a work, or None."""
        key = key_for(work_url) if work_url else ''
        return f'/api/covers/{key}' if key and self.find(key) else None

    async def store(self, work_url, cover_url, network=None):
        """Download cover_url once for work_url. Best effort: returns True when a copy exists afterwards."""
        if not work_url or not cover_url:
            return False
        key = key_for(work_url)
        if self.find(key):
            return True
        if not public_url(cover_url) or key in self.pending:
            return False
        self.pending.add(key)
        try:
            kwargs = {'timeout': 20, 'follow_redirects': False, 'headers': {'user-agent': UA}}
            if self.transport is not None:
                kwargs['transport'] = self.transport
            elif network and network.get('proxy'):
                kwargs['proxy'] = network['proxy']
            async with httpx.AsyncClient(**kwargs) as client:
                async with client.stream('GET', cover_url) as response:
                    kind = response.headers.get('content-type', '').split(';')[0].strip().lower()
                    if response.status_code != 200 or kind not in TYPES:
                        return False
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data += chunk
                        if len(data) > MAX_BYTES:
                            return False
            if not data:
                return False
            folder = self.folder(key)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f'{key}{TYPES[kind]}'
            temporary = folder / f'{key}.tmp'
            temporary.write_bytes(bytes(data))
            os.replace(temporary, target)
            return True
        except (httpx.HTTPError, OSError, ValueError):
            return False
        finally:
            self.pending.discard(key)

    def fetch_later(self, work_url, cover_url, network=None):
        """Fire-and-forget store() from a running event loop."""
        task = asyncio.get_running_loop().create_task(self.store(work_url, cover_url, network))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def fill(self, entries, network=None, concurrency=4):
        """entries: iterable of (work_url, cover_url). Skips covers already cached."""
        gate = asyncio.Semaphore(concurrency)

        async def one(work_url, cover_url):
            async with gate:
                await self.store(work_url, cover_url, network)
        await asyncio.gather(*(one(w, c) for w, c in entries if w and c and not self.find(key_for(w))))
