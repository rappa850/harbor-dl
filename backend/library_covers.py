"""Poster for a library folder. Remote cover links expire, so the poster is always a local copy.

Order: local cover cache (hash tree, filled at discovery/download time) -> thumbnail yt-dlp saved next to the video ->
remote cover fetched now (into the cache) -> a frame cut from the video. Formats media servers do not read (AVIF, GIF, ...)
are converted to JPEG with ffmpeg."""
import asyncio
import os
import shutil
import subprocess
from pathlib import Path

from .covers import key_for

DIRECT = {'.jpg', '.jpeg', '.png', '.webp'}
IMAGES = DIRECT | {'.gif', '.avif', '.bmp'}
POSTER_NAMES = ('poster', 'folder')


def existing(folder, stem='poster'):
    return next((p for p in sorted(Path(folder).glob(f'{stem}.*')) if p.suffix.lower() in IMAGES), None)


def _swap(source, target):
    tmp = target.with_name(f'.{target.name}.{os.getpid()}.tmp')
    try:
        shutil.copyfile(source, tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def run_ffmpeg(ffmpeg, args):
    if not ffmpeg:
        return False
    try:
        done = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', *args], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


class PosterResolver:
    def __init__(self, cache, ffmpeg=None):
        self.cache, self.ffmpeg = cache, ffmpeg

    def clear(self, folder, stem, keep):
        for old in Path(folder).glob(f'{stem}.*'):
            if old != keep and old.suffix.lower() in IMAGES:
                old.unlink(missing_ok=True)

    def place(self, source, folder, stem='poster'):
        """Copy (or convert) an image to <folder>/<stem>.<ext>; returns the new path or None."""
        source, folder = Path(source), Path(folder)
        if source.suffix.lower() in DIRECT:
            target = folder / f'{stem}{".jpg" if source.suffix.lower() == ".jpeg" else source.suffix.lower()}'
            _swap(source, target)
        else:
            target = folder / f'{stem}.jpg'
            tmp = folder / f'.{stem}.{os.getpid()}.tmp.jpg'
            ok = run_ffmpeg(self.ffmpeg, ['-i', str(source), '-frames:v', '1', '-q:v', '3', str(tmp)])
            if not ok or not tmp.is_file():
                tmp.unlink(missing_ok=True)
                return None
            os.replace(tmp, target)
        self.clear(folder, stem, target)
        return target

    def frame(self, video, folder, duration=None, stem='poster'):
        at = max(1.0, min(float(duration) * 0.1, 3.0)) if duration else 1.0
        tmp = Path(folder) / f'.{stem}.{os.getpid()}.tmp.jpg'
        if not run_ffmpeg(self.ffmpeg, ['-ss', f'{at:.2f}', '-i', str(video), '-frames:v', '1', '-q:v', '3', str(tmp)]) or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            return None
        target = Path(folder) / f'{stem}.jpg'
        os.replace(tmp, target)
        self.clear(folder, stem, target)
        return target

    async def poster(self, folder, *, work_url, cover_url, thumbnails=(), video=None, duration=None, network=None, previous=None):
        """Returns (file name, source) with source in cache|thumbnail|remote|frame, or (None, None).
        A poster that came from a real cover is kept; one cut from a frame is replaced as soon as a real cover exists."""
        folder = Path(folder)
        have = existing(folder)
        if have and previous and previous != 'frame':
            return have.name, previous
        key = key_for(work_url) if work_url else ''
        cached = self.cache.find(key) if key else None
        source = 'cache'
        if not cached:
            cached = next((Path(t) for t in thumbnails if Path(t).is_file() and Path(t).suffix.lower() in IMAGES), None)
            source = 'thumbnail'
        if not cached and work_url and cover_url:
            await self.cache.store(work_url, cover_url, network)
            cached, source = self.cache.find(key), 'remote'
        if cached:
            placed = await asyncio.to_thread(self.place, cached, folder)
            if placed:
                return placed.name, source
        if have and previous == 'frame':
            return have.name, 'frame'
        if video:
            cut = await asyncio.to_thread(self.frame, video, folder, duration)
            if cut:
                return cut.name, 'frame'
        return (have.name, previous or 'cache') if have else (None, None)

    async def avatar(self, folder, avatar_url, network=None):
        """folder.<ext> for the author folder, from the same hash cache (keyed by the avatar address)."""
        if not avatar_url or existing(folder, 'folder'):
            return None
        if not self.cache.find(key_for(avatar_url)):
            await self.cache.store(avatar_url, avatar_url, network)
        cached = self.cache.find(key_for(avatar_url))
        return await asyncio.to_thread(self.place, cached, folder, 'folder') if cached else None
