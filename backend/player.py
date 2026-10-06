"""Subtitle delivery, bounded metadata probing and subscription playback records."""
import asyncio
import json
import re
import shutil

from .downloads import now


def srt_to_vtt(content):
    content = content.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    content = re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{3})', r'\1.\2', content)
    return 'WEBVTT\n\n' + content


def subtitle_list(assets, media):
    path = assets.path(media['path'])
    result = []
    for asset in assets.store.all('SELECT * FROM media_assets WHERE kind=?', ('attachment',)):
        try:
            candidate = assets.path(asset['path'])
        except ValueError:
            continue
        if candidate.parent != path.parent or candidate.suffix.lower() not in ('.vtt', '.srt'):
            continue
        if not (candidate.stem == path.stem or candidate.stem.startswith(path.stem + '.')):
            continue
        language = candidate.stem[len(path.stem):].lstrip('.') or 'und'
        result.append({'id': asset['id'], 'language': language, 'label': language,
                       'path': f"/api/files/{asset['id']}/subtitle", 'is_default': False})
    if result:
        result[0]['is_default'] = True
    return result


async def metadata(path):
    executable = shutil.which('ffprobe')
    if not executable:
        return {'success': False, 'reason': 'FFprobe 未安装'}
    process = await asyncio.create_subprocess_exec(executable, '-v', 'error', '-show_format',
        '-show_streams', '-of', 'json', str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        return {'success': False, 'reason': '媒体元数据读取失败'}
    info = json.loads(stdout)
    video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
    fmt = info.get('format', {})
    def number(value):
        try:
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None
    return {'success': True, 'width': video.get('width'), 'height': video.get('height'),
            'duration': number(fmt.get('duration')), 'video_bitrate': number(video.get('bit_rate')),
            'format_bitrate': number(fmt.get('bit_rate'))}


class PlaybackRecords:
    def __init__(self, store):
        self.store = store

    def get(self, subscription_id):
        record = self.store.one('SELECT * FROM playback_records WHERE subscription_id=?', (str(subscription_id),))
        if record:
            record['video_progress'] = json.loads(record['video_progress'])
        return record

    def save(self, subscription_id, data):
        with self.store.connect() as db:
            db.execute('INSERT INTO playback_records VALUES (?,?,?,?,?) ON CONFLICT(subscription_id) '
                       'DO UPDATE SET current_index=excluded.current_index,playback_mode=excluded.playback_mode,'
                       'video_progress=excluded.video_progress,last_updated=excluded.last_updated',
                       (str(subscription_id), data.current_index, data.playback_mode,
                        json.dumps(data.video_progress), now()))
        return self.get(subscription_id)
