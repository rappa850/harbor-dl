"""File and folder naming for the media-server library (Jellyfin / Emby): safe on Windows, Linux and network shares."""
import re

BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')
RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{n}' for n in range(1, 10)), *(f'LPT{n}' for n in range(1, 10))}
HASHTAG = re.compile(r'#([^\s#@，。！？、,.!?]+)')
PLATFORMS = {'douyin': '抖音', 'youtube': 'YouTube', 'bilibili': '哔哩哔哩', 'tiktok': 'TikTok', 'xiaohongshu': '小红书',
             'kuaishou': '快手', 'instagram': 'Instagram', 'x': 'X', 'netease': '网易云音乐'}


def platform_label(platform):
    return PLATFORMS.get(platform or '', platform or '其他')


def truncate_bytes(text, limit):
    """Cut at a character boundary so that the UTF-8 length stays within `limit` bytes."""
    if len(text.encode('utf-8')) <= limit:
        return text
    out = ''
    for char in text:
        if len((out + char).encode('utf-8')) > limit:
            break
        out += char
    return out


def clean_name(text, limit=120, fallback='untitled'):
    """One path component: no separators or control characters, no trailing dots/spaces, no reserved device names."""
    value = BAD.sub('_', str(text or ''))
    value = re.sub(r'\s+', ' ', value).strip(' .')
    value = truncate_bytes(value, limit).strip(' .')
    if not value or set(value) <= {'_'}:
        value = fallback
    if value.split('.')[0].upper() in RESERVED:
        value = f'_{value}'
    return value


def split_description(description, work_id, title_chars=60):
    """Short title, full text and hashtags from a post description such as '一段话 #话题 #话题'."""
    text = (description or '').strip()
    tags = []
    for tag in HASHTAG.findall(text):
        if tag not in tags:
            tags.append(tag)
    first = next((line for line in text.splitlines() if HASHTAG.sub('', line).strip()), '')
    title = re.sub(r'\s+', ' ', HASHTAG.sub('', first)).strip(' -_·，,')
    if len(title) > title_chars:
        title = title[:title_chars].rstrip() + '…'
    return (title or str(work_id)), text, tags
