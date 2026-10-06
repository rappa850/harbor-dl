"""Isolated yt-dlp worker; emits structured progress and postprocessing events."""
import json
import sys
from pathlib import Path
from contextlib import ExitStack

from yt_dlp import YoutubeDL
from .network import cookie_file, redact


def emit(kind, value):
    print('harbor-' + kind + ':' + json.dumps(value, ensure_ascii=False), flush=True)


def main():
    # Read options through stdin so credentials can later be added without argv exposure.
    task = json.load(sys.stdin)
    network = task.get('network', {'proxy': '', 'cookie_content': ''})
    if any(flag in sys.argv for flag in ('--inspect','--profile','--catalog')):
        with ExitStack() as stack:
            options = network_options(network, task['url'], stack)
            options.update({'quiet': True, 'no_warnings': True, 'noplaylist': True,
                            'socket_timeout': 20, 'retries': 1})
            if '--profile' in sys.argv:
                options.update({'noplaylist':False,'extract_flat':True,'playlistend':1})
            if '--catalog' in sys.argv:
                options.update({'noplaylist':False,'extract_flat':True})
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(task['url'], download=False)
                print(json.dumps(ydl.sanitize_info(info), ensure_ascii=False), flush=True)
        return
    folder = Path(task.pop('output_folder'))
    if task.get('direct'):
        return direct_download(task['direct'], folder, task.get('network') or {})

    def progress(event):
        if event.get('status') in ('downloading', 'finished'):
            emit('progress', {k: event.get(k) for k in (
                'status', 'downloaded_bytes', 'total_bytes', 'total_bytes_estimate', '_speed_str')})

    def postprocess(event):
        if event.get('status') == 'started':
            emit('processing', event.get('postprocessor') or '媒体后处理')

    def finished(info):
        emit('title', info.get('title') or task['url'])
        emit('file', info['filepath'])

    options = {'noplaylist': True, 'format': task['format_id'], 'quiet': True,
               'no_warnings': True, 'socket_timeout': 30, 'retries': 3,
               'restrictfilenames': True, 'outtmpl': str(folder / '%(title).160B [%(id)s].%(ext)s'),
               'writesubtitles': bool(task['subtitles']), 'writeautomaticsub': bool(task['subtitles']),
               'writethumbnail': bool(task['thumbnail']),
               'progress_hooks': [progress], 'postprocessor_hooks': [postprocess]}
    with ExitStack() as stack:
        options.update(network_options(network, task['url'], stack))
        with YoutubeDL(options) as ydl:
            ydl.add_post_processor(FinishedPP(ydl, finished), when='after_move')
            ydl.download([task['url']])


def direct_download(target, folder, network):
    """Stream resolved media URLs to disk; used where the platform has no usable yt-dlp extractor.

    A target is either one video ({'url','ext'}) or a picture post ({'files': [{'url','kind','optional','label'}]}).
    The first picture of a post is reported as the primary file, the rest sit next to it in the task folder.
    """
    import re
    import httpx
    ident = str(target['id'])
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', target.get('title') or ident).strip(' ._')[:80] or ident
    files = target.get('files') or [{'url': target['url'], 'kind': 'video', 'ext': target.get('ext') or 'mp4'}]
    kwargs = {'timeout': httpx.Timeout(30, read=60), 'follow_redirects': True}
    if network.get('proxy'):
        kwargs['proxy'] = network['proxy']
    emit('title', target.get('title') or ident)
    saved = []
    pictures = sum(1 for item in files if item.get('kind') == 'image')
    with httpx.Client(**kwargs) as client:
        for number, item in enumerate(files, 1):
            suffix = f"_{item.get('label') or str(len([f for f in saved if f[1] == 'image']) + 1).zfill(2)}" if len(files) > 1 else ''
            try:
                path = fetch_one(client, item, folder / f"{name} [{ident}]{suffix}", target.get('headers') or {}, number - 1, len(files))
            except RuntimeError:
                if item.get('optional'):
                    continue
                raise
            saved.append((path, item.get('kind')))
    if pictures and not any(kind == 'image' for _, kind in saved):
        raise RuntimeError('没有成功下载任何图片')
    primary = next((p for p, kind in saved if kind == 'image'), saved[0][0])
    emit('file', str(primary))


IMAGE_TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif', 'image/avif': '.avif'}
AUDIO_TYPES = {'audio/mpeg': '.mp3', 'audio/mp4': '.m4a', 'audio/x-m4a': '.m4a', 'audio/aac': '.aac', 'audio/wav': '.wav', 'audio/x-wav': '.wav'}


def fetch_one(client, item, stem, headers, index, total):
    with client.stream('GET', item['url'], headers=headers) as response:
        if response.status_code >= 400:
            raise RuntimeError(f'媒体地址返回 HTTP {response.status_code}，链接可能已过期或被风控拦截')
        content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
        kind = item.get('kind') or 'video'
        generic = content_type in ('application/octet-stream', 'binary/octet-stream', '')
        if kind == 'image' and not (content_type.startswith('image/') or generic):
            raise RuntimeError(f'图片地址返回了非图片内容（{content_type}），可能触发风控')
        if kind != 'image' and not (content_type.startswith(('video/', 'audio/')) or generic):
            raise RuntimeError(f'媒体地址返回了非媒体内容（{content_type}），可能触发风控')
        extension = item.get('ext') or (IMAGE_TYPES.get(content_type, '.jpg') if kind == 'image'
                                        else AUDIO_TYPES.get(content_type, '.mp3') if kind == 'audio' else '.mp4')
        path = stem.with_name(stem.name + ('' if extension.startswith('.') else '.') + extension)
        expected = int(response.headers.get('content-length') or 0)
        done = 0
        with path.open('wb') as out:
            for chunk in response.iter_bytes(256 * 1024):
                out.write(chunk)
                done += len(chunk)
                if total == 1:
                    emit('progress', {'status': 'downloading', 'downloaded_bytes': done, 'total_bytes': expected or None})
    if not done or (expected and done != expected):
        path.unlink(missing_ok=True)
        raise RuntimeError('媒体下载不完整，已丢弃文件')
    if total > 1:
        emit('progress', {'status': 'downloading', 'downloaded_bytes': index + 1, 'total_bytes': total})
    return path


def network_options(network, url, stack):
    result = {'proxy': network.get('proxy', '')}
    content = network.get('cookie_content', '')
    if content:
        result['cookiefile'] = stack.enter_context(cookie_file(content, url))
    return result


from yt_dlp.postprocessor.common import PostProcessor


class FinishedPP(PostProcessor):
    def __init__(self, downloader, callback):
        super().__init__(downloader)
        self.callback = callback

    def run(self, info):
        self.callback(info)
        return [], info


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
