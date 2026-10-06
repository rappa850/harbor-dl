"""Media inspection adapter. Platform-specific adapters will extend this contract."""
import asyncio
import json
import re
import sys
from urllib.parse import urlsplit


def share_url(text):
    match = re.search(r'https?://[^\s\u4e00-\u9fa5，。？！、“”《》]+', text.strip(), re.I)
    if not match:
        raise ValueError('分享文本中没有 HTTP 或 HTTPS 链接')
    value = match.group().rstrip('),.;!?\'"“”')
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('媒体链接无效或包含登录凭据')
    _ = parsed.port
    return value


def platform_for(url):
    host = urlsplit(url).hostname or ''
    groups = {
        'youtube': ('youtube.com', 'youtu.be'), 'bilibili': ('bilibili.com', 'b23.tv'),
        'douyin': ('douyin.com', 'iesdouyin.com'),
        'xiaohongshu': ('xiaohongshu.com', 'xhslink.com', 'xhslink.cn'),
        'kuaishou': ('kuaishou.com', 'gifshow.com', 'chenzhongtech.com'),
        'tiktok': ('tiktok.com',), 'instagram': ('instagram.com',),
        'x': ('x.com', 'twitter.com'), 'netease': ('music.163.com', '163cn.tv'),
    }
    return next((name for name, domains in groups.items()
                 if any(host == domain or host.endswith('.' + domain) for domain in domains)), 'universal')


def format_choices(info):
    formats = [f for f in info.get('formats', []) if f.get('format_id') and not f.get('has_drm')]
    audio = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') not in (None, 'none')]
    audio_id = str(audio[-1]['format_id']) if audio else None
    choices = []
    heights = sorted({f.get('height') for f in formats if f.get('height') and f.get('vcodec') != 'none'}, reverse=True)
    for height in heights:
        candidates = [f for f in formats if f.get('height') == height and f.get('vcodec') != 'none']
        chosen = next((f for f in reversed(candidates) if f.get('ext') == 'mp4'), candidates[-1])
        format_id = str(chosen['format_id'])
        merge = chosen.get('acodec') == 'none'
        if merge and not audio_id:
            continue
        if merge:
            format_id += '+' + audio_id
        choices.append({'id': format_id, 'label': f'{height}p', 'extension': chosen.get('ext'),
                        'fps': chosen.get('fps'), 'size': chosen.get('filesize') or chosen.get('filesize_approx'),
                        'requires_merge': merge, 'kind': 'video'})
    if audio_id:
        choices.append({'id': audio_id, 'label': '仅音频', 'extension': audio[-1].get('ext'),
                        'kind': 'audio', 'requires_merge': False})
    if not choices:
        choices.append({'id': 'best', 'label': '最佳可用格式', 'extension': info.get('ext'),
                        'kind': 'video', 'requires_merge': False})
    return choices


class MediaInspector:
    def __init__(self):
        self.slots = asyncio.Semaphore(2)

    async def raw_info(self, url, network=None, profile=False, catalog=False):
        from .network import redact
        from pathlib import Path
        network = network or {'proxy': '', 'cookie_content': ''}
        async with self.slots:
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-X', 'utf8', '-u', '-m', 'backend.download_worker', '--catalog' if catalog else '--profile' if profile else '--inspect',
                cwd=Path(__file__).resolve().parents[1], stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(
                    json.dumps({'url': url, 'network': network}, ensure_ascii=False).encode('utf-8')), timeout=90)
            except BaseException:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                raise
        if process.returncode:
            raise ValueError(redact(stderr.decode('utf-8', 'replace')[-1500:], network) or '媒体解析失败')
        info = json.loads(stdout)
        return info

    async def inspect(self, url, network=None):
        info = await self.raw_info(url,network)
        if info.get('_type') in ('playlist', 'multi_video'):
            raise ValueError('该链接包含多项内容，歌单和集合适配尚未完成，请使用单项链接')
        return {'url': url, 'platform': platform_for(url), 'title': info.get('title') or url,
                'author': info.get('uploader') or info.get('channel') or '',
                'thumbnail': info.get('thumbnail'), 'duration': info.get('duration'),
                'formats': format_choices(info), 'adapter': 'yt-dlp', 'kind': 'video'}
