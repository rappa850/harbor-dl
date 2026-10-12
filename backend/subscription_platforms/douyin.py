"""Douyin author subscription adapter (web API, a_bogus signed).

Request shapes and signing follow the public web client; they have only been exercised against
recorded/stubbed responses here. A logged-in Cookie (Settings -> Douyin) is normally required for
the web API to answer; an empty body is reported as probable risk control instead of "no works".
"""
import asyncio
import json
import random
import re
import string
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlsplit

import httpx

from ..media import share_url
from ..subscriptions import SubscriptionConfig
from ..browser_fetch import BrowserFetchError, fetch_in_page
from ..vendor.douyin_ab_sign import ab_sign
from . import FetchResult, PlatformError, SubscriptionAdapter

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/141.0.0.0 Safari/537.36')
MOBILE_UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) '
             'Version/16.6 Mobile/15E148 Safari/604.1')
WEB = 'https://www.douyin.com'
DOUYIN_HOSTS = ('douyin.com', 'iesdouyin.com')
SEC_UID = re.compile(r'^[A-Za-z0-9_\-]{12,}$')
PAGE_SIZE = 18
RETRIES = 3
MAX_PAGES = 1000
MAX_MIX_PAGES = 20
MIX_ID = re.compile(r'^\d{10,}$')
PERSONAL_TYPES = ('like', 'favorite')   # lists that belong to the logged-in account itself
PERSONAL_DELAY = 2.0                    # extra spacing factor between pages: these lists are watched more closely
LOGIN_CODES = (8, 2154)   # status codes the web client answers when the session is missing or expired
RISK_HINT = '抖音没有返回数据，可能触发风控或 Cookie 无效；请在设置中更新抖音 Cookie 后重试'


def _host_ok(host):
    return any(host == d or host.endswith('.' + d) for d in DOUYIN_HOSTS)


def cookie_header(content):
    """Header-form cookie text from either stored form (header line or Netscape file)."""
    content = (content or '').strip()
    if not content:return ''
    if '# Netscape HTTP Cookie File' in content or '# HTTP Cookie File' in content or '\t' in content:
        pairs=[]
        for line in content.splitlines():
            line=line.removeprefix('#HttpOnly_') if line.startswith('#HttpOnly_') else line
            parts=line.split('\t')
            if len(parts)==7 and not line.startswith('#'):pairs.append(f'{parts[5]}={parts[6]}')
        return '; '.join(pairs)
    return content.removeprefix('Cookie:').strip()


def cookie_value(header, name):
    for part in header.split(';'):
        key, sep, value = part.strip().partition('=')
        if sep and key == name:return value
    return ''


def parse_sec_uid(url):
    """sec_uid from a full profile URL, or None when the URL is not a profile (e.g. short link)."""
    parsed = urlsplit(url)
    if not _host_ok(parsed.hostname or ''):raise ValueError('请输入抖音博主主页链接')
    parts = [p for p in parsed.path.split('/') if p]
    if 'user' in parts[:-1]:
        value = parts[parts.index('user') + 1]
        if value == 'self' or not SEC_UID.fullmatch(value):raise ValueError('主页链接中的博主标识无效')
        return value
    if (parsed.hostname or '').startswith('v.') and parts:return None
    raise ValueError('请使用抖音博主主页链接（形如 https://www.douyin.com/user/…），单个作品链接不能作为博主订阅')


def parse_mix_id(url):
    """Mix id from a collection URL or a bare number, else None."""
    text = str(url).strip()
    if MIX_ID.fullmatch(text):return text
    parsed = urlsplit(text)
    if not _host_ok(parsed.hostname or ''):return None
    match = re.search(r'/(?:collection|mix/detail|share/mix/detail|share/mix)/(\d{10,})', parsed.path)
    return match[1] if match else None


def profile_fields(user, counts=True):
    """Profile details shared by every Douyin subscription built from a user record."""
    avatar = (user.get('avatar_larger') or user.get('avatar_thumb') or {}).get('url_list') or []
    def count(key):
        value = user.get(key) if counts else None
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    return dict(signature=user.get('signature') or None, avatar_url=avatar[0] if avatar else None,
                follower_count=count('follower_count'), like_count=count('total_favorited'), video_count=count('aweme_count'))


def entry_from_aweme(item):
    """(video_id, metadata) from one aweme_list item, or None when it has no usable identity."""
    if not isinstance(item, dict):return None
    video_id = str(item.get('aweme_id') or '')
    if not re.fullmatch(r'\d{6,}', video_id):return None
    video = item.get('video') if isinstance(item.get('video'), dict) else {}
    images = item.get('images')
    is_image = bool(images) or item.get('aweme_type') in (2, 68, 150)
    duration = video.get('duration')
    duration = duration / 1000 if isinstance(duration, (int, float)) and duration > 0 and not is_image else None
    stamp = item.get('create_time')
    published = None
    if isinstance(stamp, (int, float)) and stamp > 0:
        try:published = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):pass
    cover = None
    for key in ('cover', 'origin_cover', 'dynamic_cover'):
        urls = (video.get(key) or {}).get('url_list') if isinstance(video.get(key), dict) else None
        if urls:cover = urls[0];break
    title = (item.get('desc') or '').strip() or video_id
    owner = item.get('author') if isinstance(item.get('author'), dict) else {}
    avatar = first_url(owner.get('avatar_thumb') or owner.get('avatar_larger'))
    author = {'name': owner.get('nickname') or None, 'sec_uid': owner.get('sec_uid') or None, 'avatar_url': avatar} \
        if owner.get('nickname') or owner.get('sec_uid') else None
    return video_id, {
        'title': title, 'description': item.get('desc') or None,
        'url': f'{WEB}/{"note" if is_image else "video"}/{video_id}', 'cover_url': cover,
        'duration': duration, 'publish_time': published,
        'extra_data': {'media_type': 'image' if is_image else 'video', 'aweme_type': item.get('aweme_type'),
                       'is_top': bool(item.get('is_top')), 'author': author}}


def is_audio_url(url):
    return '/ies-music/' in url or url.split('?')[0].lower().endswith(('.mp3', '.m4a'))


def play_url(detail):
    """Best direct video URL from an aweme detail; watermark-free variant when the platform offers it."""
    video = detail.get('video') if isinstance(detail.get('video'), dict) else {}
    candidates = []
    for variant in sorted((v for v in video.get('bit_rate') or [] if isinstance(v, dict)),
                          key=lambda v: v.get('bit_rate') or 0, reverse=True):
        candidates += (variant.get('play_addr') or {}).get('url_list') or []
    candidates += (video.get('play_addr') or {}).get('url_list') or []
    for url in candidates:
        if isinstance(url, str) and url.startswith('http') and not is_audio_url(url):
            return url.replace('/playwm/', '/play/')
    return None


def first_url(address):
    for url in (address or {}).get('url_list') or []:
        if isinstance(url, str) and url.startswith('http'):return url
    return None


def image_files(detail):
    """Picture URLs of an image post in display order (original-quality download URL preferred)."""
    result = []
    for image in detail.get('images') or []:
        if not isinstance(image, dict):continue
        url = first_url({'url_list': image.get('download_url_list') or []}) or first_url(image)
        if url:result.append(url)
    return result


DETAIL_SCRIPT = ("fetch('/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id=%s"
                 "&pc_client_type=1&version_code=190500&version_name=19.5.0&cookie_enabled=true&platform=PC',"
                 "{credentials:'include'}).then(r=>r.text()).catch(()=>'')")


def judge_detail(value):
    """Decision for browser_fetch: the page's own SDK signs the fetch once its scripts have loaded."""
    try:data = json.loads(value) if value else None
    except ValueError:data = None
    if not isinstance(data, dict):return 'retry', None
    detail = data.get('aweme_detail')
    if isinstance(detail, dict) and detail:return 'ok', detail
    if data.get('status_code') in (0, None) and data.get('filter_detail'):
        return 'fail', '作品不可访问：' + str((data['filter_detail'] or {}).get('notice') or '已删除或设为私密')
    return 'retry', None


async def browser_detail(aweme_id, network):
    """Anonymous work detail through a throwaway headless Chrome (no login, no saved Cookie)."""
    try:
        return await fetch_in_page(f'{WEB}/video/{aweme_id}', DETAIL_SCRIPT % aweme_id, judge_detail,
                                   proxy=network.get('proxy', ''))
    except BrowserFetchError as exc:
        raise PlatformError(str(exc)) from exc


class DouyinAdapter(SubscriptionAdapter):
    platforms = ('douyin',)
    home_url = WEB + '/'

    def __init__(self, transport=None, sleep=asyncio.sleep, page_delay=(0.8, 1.6), detail_fetcher=None):
        self.transport, self.sleep, self.page_delay = transport, sleep, page_delay
        self.detail_fetcher = detail_fetcher or browser_detail

    def describe_unavailable(self, config):
        kind = config.get('subscription_type', 'user')
        if kind == 'mix':
            if not MIX_ID.fullmatch(str(config.get('collection_id') or '')):return '缺少已解析的抖音合集标识'
            return None
        if kind not in ('user', *PERSONAL_TYPES):return '此抖音订阅类型尚未适配'
        if not SEC_UID.fullmatch(str(config.get('user_id') or '')):
            return '缺少已解析的抖音账号标识' if kind in PERSONAL_TYPES else '缺少已解析的抖音博主标识'
        return None

    def client(self, network):
        kwargs = {'timeout': 20, 'follow_redirects': True}
        if self.transport is not None:kwargs['transport'] = self.transport
        elif network.get('proxy'):kwargs['proxy'] = network['proxy']
        return httpx.AsyncClient(**kwargs)

    def signed_url(self, path, params, cookie):
        base = {'device_platform': 'webapp', 'aid': '6383', 'channel': 'channel_pc_web', 'update_version_code': '170400',
                'pc_client_type': '1', 'version_code': '290100', 'version_name': '29.1.0', 'cookie_enabled': 'true',
                'screen_width': '1920', 'screen_height': '1080', 'browser_language': 'zh-CN', 'browser_platform': 'Win32',
                'browser_name': 'Chrome', 'browser_version': '141.0.0.0', 'browser_online': 'true', 'engine_name': 'Blink',
                'engine_version': '141.0.0.0', 'os_name': 'Windows', 'os_version': '10', 'cpu_core_num': '12',
                'device_memory': '8', 'platform': 'PC', 'downlink': '10', 'effective_type': '4g', 'round_trip_time': '100'}
        fp = cookie_value(cookie, 's_v_web_id')
        if fp:base.update(verifyFp=fp, fp=fp)
        # The gateway rejects calls without the device id the web client echoes from its UIFID cookie (403 "Uifid Not Found").
        uifid = cookie_value(cookie, 'UIFID') or cookie_value(cookie, 'UIFID_TEMP')
        if uifid:base['uifid'] = uifid
        base.update(params)
        base['msToken'] = cookie_value(cookie, 'msToken') or ''.join(random.choices(string.ascii_letters + string.digits + '_-', k=107))
        query = urlencode(base, quote_via=quote)
        return f'{WEB}{path}?{query}&a_bogus={ab_sign(query, UA)}'

    async def api(self, client, network, path, params, referer, data=None):
        cookie = cookie_header(network.get('cookie_content', ''))
        headers = {'user-agent': UA, 'referer': referer, 'accept': 'application/json, text/plain, */*',
                   'accept-language': 'zh-CN,zh;q=0.9'}
        if cookie:headers['cookie'] = cookie
        # The platform answers 403 / an empty body intermittently (risk control); a new signature a moment later
        # usually passes, so retry a couple of times before reporting the failure.
        failure, auth_hint = None, False
        for attempt in range(RETRIES):
            if attempt:await self.sleep(random.uniform(1.5, 3.5) * attempt)
            url = self.signed_url(path, params, cookie)
            try:
                if data is None:response = await client.get(url, headers=headers)
                else:response = await client.post(url, headers={**headers, 'content-type': 'application/x-www-form-urlencoded; charset=UTF-8'},
                                                  content=urlencode(data))
            except httpx.HTTPError as exc:raise PlatformError(f'抖音请求失败：{exc.__class__.__name__}') from exc
            if response.status_code >= 400:
                if 'Uifid Not Found' in response.text:
                    raise PlatformError('抖音要求设备标识 UIFID，已保存的登录状态里没有，请重新登录抖音后再试', auth=True)
                failure = f'抖音请求被拒绝（HTTP {response.status_code}），可能触发风控';continue
            if not response.content.strip():failure = RISK_HINT;auth_hint = not cookie;continue
            try:data = response.json()
            except ValueError:failure = RISK_HINT;continue
            failure = None;break
        if failure:raise PlatformError(failure, auth=auth_hint)
        if not isinstance(data, dict):raise PlatformError('抖音返回了无法识别的数据')
        code = data.get('status_code')
        if code not in (0, None):
            message = str(data.get('status_msg') or '未知')
            raise PlatformError(f'抖音返回错误 {code}：{message}', auth=code in LOGIN_CODES or '登录' in message)
        return data

    async def sec_uid_for(self, client, text):
        url = share_url(text)
        found = parse_sec_uid(url)
        if found:return found
        try:response = await client.get(url, headers={'user-agent': UA})
        except httpx.HTTPError as exc:raise PlatformError(f'短链接解析失败：{exc.__class__.__name__}') from exc
        final = str(response.url)
        if '/share/video/' in final or '/video/' in urlsplit(final).path:
            raise ValueError('该短链接指向单个作品，请使用博主主页链接')
        found = parse_sec_uid(final) if _host_ok(urlsplit(final).hostname or '') else None
        if not found:raise ValueError('短链接没有指向抖音博主主页')
        return found

    async def resolve(self, payload, network):
        if payload.source in PERSONAL_TYPES:return await self.resolve_personal(payload, network)
        if payload.source == 'mix':return await self.resolve_mix(payload, network)
        async with self.client(network) as client:
            sec_uid = await self.sec_uid_for(client, payload.profile_url)
            data = await self.api(client, network, '/aweme/v1/web/user/profile/other/',
                                  {'sec_user_id': sec_uid, 'source': 'channel_pc_web', 'publish_video_strategy_type': '2'},
                                  f'{WEB}/user/{sec_uid}')
        user = data.get('user')
        if not isinstance(user, dict) or not user:raise PlatformError('抖音没有返回博主资料，Cookie 可能无效或博主不存在')
        if user.get('sec_uid') and user['sec_uid'] != sec_uid:raise ValueError('平台返回的博主身份与链接不一致')
        return SubscriptionConfig(
            platform='douyin', user_id=sec_uid, profile_url=f'{WEB}/user/{sec_uid}',
            nickname=payload.nickname.strip() or user.get('nickname') or sec_uid,
            nickname_locked=bool(payload.nickname.strip()), subscription_type='user',
            update_interval=payload.update_interval, auto_download=payload.wants_auto_download, **profile_fields(user))

    async def resolve_personal(self, payload, network):
        """My likes / my favorites: both belong to the account the saved Cookie is logged in to."""
        if not cookie_header(network.get('cookie_content', '')):
            raise ValueError('点赞和收藏属于登录账号，请先登录抖音')
        async with self.client(network) as client:
            data = await self.api(client, network, '/aweme/v1/web/user/profile/self/',
                                  {'source': 'channel_pc_web', 'publish_video_strategy_type': '2'}, f'{WEB}/user/self')
        user = data.get('user')
        sec_uid = user.get('sec_uid') if isinstance(user, dict) else None
        if not sec_uid or not SEC_UID.fullmatch(str(sec_uid)):
            raise PlatformError('抖音没有返回当前登录账号的资料，登录状态可能已失效，请重新登录', auth=True)
        label = '点赞' if payload.source == 'like' else '收藏'
        name = user.get('nickname') or sec_uid
        return SubscriptionConfig(
            platform='douyin', user_id=sec_uid, profile_url=f'{WEB}/user/self?showTab={"like" if payload.source == "like" else "favorite_collection"}',
            nickname=payload.nickname.strip() or f'{name} 的{label}', nickname_locked=bool(payload.nickname.strip()),
            subscription_type=payload.source, update_interval=payload.update_interval, auto_download=payload.wants_auto_download,
            **profile_fields(user, counts=False))

    async def mix_id_for(self, client, text):
        found = parse_mix_id(text)
        if found:return found
        url = share_url(text)
        found = parse_mix_id(url)
        if found:return found
        if not (urlsplit(url).hostname or '').startswith('v.'):raise ValueError('请输入抖音合集链接（形如 https://www.douyin.com/collection/…）或合集 ID')
        try:response = await client.get(url, headers={'user-agent': MOBILE_UA})
        except httpx.HTTPError as exc:raise PlatformError(f'短链接解析失败：{exc.__class__.__name__}') from exc
        found = parse_mix_id(str(response.url))
        if not found:raise ValueError('短链接没有指向抖音合集')
        return found

    async def resolve_mix(self, payload, network):
        async with self.client(network) as client:
            mix_id = await self.mix_id_for(client, payload.profile_url)
            data = await self.api(client, network, '/aweme/v1/web/mix/detail/', {'mix_id': mix_id}, f'{WEB}/collection/{mix_id}')
        info = data.get('mix_info')
        if not isinstance(info, dict) or not info:raise PlatformError('抖音没有返回合集资料，Cookie 可能无效或合集不存在')
        if info.get('mix_id') and str(info['mix_id']) != mix_id:raise ValueError('平台返回的合集身份与链接不一致')
        title = (info.get('mix_name') or '').strip() or mix_id
        owner = info.get('author') if isinstance(info.get('author'), dict) else {}
        stats = info.get('statis') if isinstance(info.get('statis'), dict) else {}
        total = stats.get('updated_to_episode')
        return SubscriptionConfig(
            platform='douyin', user_id=mix_id, profile_url=f'{WEB}/collection/{mix_id}', nickname=payload.nickname.strip() or title,
            nickname_locked=bool(payload.nickname.strip()), subscription_type='mix', collection_id=mix_id, collection_title=title,
            author_id=owner.get('sec_uid') or None, author_name=owner.get('nickname') or None,
            update_interval=payload.update_interval, auto_download=payload.wants_auto_download,
            signature=(info.get('desc') or '').strip() or None, avatar_url=first_url(info.get('cover_url')),
            video_count=total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None)

    async def my_mixes(self, network):
        """Mixes the logged-in account has collected, for the 'add a mix' picker."""
        if not cookie_header(network.get('cookie_content', '')):
            raise ValueError('收藏的合集属于登录账号，请先登录抖音')
        result, cursor = [], 0
        async with self.client(network) as client:
            for page in range(MAX_MIX_PAGES):
                if page:await self.sleep(random.uniform(*self.page_delay))
                data = await self.api(client, network, '/aweme/v1/web/mix/listcollection/', {}, f'{WEB}/user/self?showTab=favorite_collection',
                                      data={'count': 12, 'cursor': cursor})
                infos = data.get('mix_infos')
                if not isinstance(infos, list):infos = []
                for info in infos:
                    mix_id = str(info.get('mix_id') or '') if isinstance(info, dict) else ''
                    if not MIX_ID.fullmatch(mix_id):continue
                    owner = info.get('author') if isinstance(info.get('author'), dict) else {}
                    result.append({'mix_id': mix_id, 'title': (info.get('mix_name') or mix_id).strip(), 'author': owner.get('nickname'),
                                   'cover_url': first_url(info.get('cover_url')),
                                   'count': (info.get('statis') or {}).get('updated_to_episode')})
                nxt = data.get('cursor')
                if not data.get('has_more') or not isinstance(nxt, int) or nxt == cursor:break
                cursor = nxt
        return result

    def page_request(self, config, cursor):
        """(path, query params, form body or None, referer, cursor key in the answer) for one page of the subscription's list."""
        kind = config.get('subscription_type', 'user')
        if kind == 'like':
            return ('/aweme/v1/web/aweme/favorite/', {'sec_user_id': config['user_id'], 'max_cursor': cursor, 'min_cursor': 0,
                    'count': PAGE_SIZE, 'whale_cut_token': '', 'cut_version': '1', 'publish_video_strategy_type': '2'},
                    None, f'{WEB}/user/self?showTab=like', 'max_cursor')
        if kind == 'favorite':
            return ('/aweme/v1/web/aweme/listcollection/', {}, {'count': 10, 'cursor': cursor},
                    f'{WEB}/user/self?showTab=favorite_collection', 'cursor')
        if kind == 'mix':
            return ('/aweme/v1/web/mix/aweme/', {'mix_id': config['collection_id'], 'cursor': cursor, 'count': 20},
                    None, f'{WEB}/collection/{config["collection_id"]}', 'cursor')
        sec_uid = config['user_id']
        return ('/aweme/v1/web/aweme/post/', {'sec_user_id': sec_uid, 'max_cursor': cursor, 'count': PAGE_SIZE, 'locate_query': 'false',
                'show_live_replay_strategy': '1', 'need_time_list': '1', 'time_list_query': '0',
                'whale_cut_token': '', 'cut_version': '1', 'publish_video_strategy_type': '2'},
                None, f'{WEB}/user/{sec_uid}', 'max_cursor')

    async def fetch(self, config, network, known=None, max_pages=None, progress=None):
        kind = config.get('subscription_type', 'user')
        if kind != 'user' and not cookie_header(network.get('cookie_content', '')):
            raise PlatformError('这个抖音订阅需要登录状态，请先登录抖音', auth=True)
        result, cursor, limit = FetchResult(), 0, min(max_pages or MAX_PAGES, MAX_PAGES)
        spacing = PERSONAL_DELAY if kind in PERSONAL_TYPES else 1.0
        async with self.client(network) as client:
            while result.pages < limit:
                if result.pages:await self.sleep(random.uniform(*self.page_delay) * spacing)
                path, params, form, referer, cursor_key = self.page_request(config, cursor)
                data = await self.api(client, network, path, params, referer, data=form)
                items = data.get('aweme_list')
                if items is None and data.get('has_more') in (0, False, None):items = []
                if not isinstance(items, list):raise PlatformError('抖音作品列表格式无法识别')
                result.pages += 1
                fresh = False
                for item in items:
                    entry = entry_from_aweme(item)
                    if entry is None:result.skipped += 1;continue
                    result.entries[entry[0]] = entry[1]
                    # pinned works sit at the top regardless of age, so they say nothing about "already seen".
                    if known is not None and entry[0] not in known and not entry[1]['extra_data']['is_top']:fresh = True
                if progress:progress(result.pages, len(result.entries))
                more = bool(data.get('has_more'))
                next_cursor = data.get(cursor_key)
                if not more:result.complete = True;break
                if not isinstance(next_cursor, int) or next_cursor == cursor or not items:
                    raise PlatformError('抖音分页游标异常，未保存此次读取')
                cursor = next_cursor
                if known is not None and not fresh:break
                if known is not None and result.pages >= limit:result.truncated = True
        return result

    async def aweme_id_for(self, client, url):
        match = re.search(r'/(?:share/)?(?:video|note)/(\d+)|[?&]modal_id=(\d+)', url)
        if match:return match[1] or match[2]
        if (urlsplit(url).hostname or '').startswith('v.') and _host_ok(urlsplit(url).hostname or ''):
            try:response = await client.get(url, headers={'user-agent': MOBILE_UA})
            except httpx.HTTPError as exc:raise PlatformError(f'短链接解析失败：{exc.__class__.__name__}') from exc
            match = re.search(r'/(?:share/)?(?:video|note)/(\d+)', str(response.url))
            return match[1] if match else None
        return None

    async def download_target(self, task, network):
        """Download plan for one work. Never needs a login: the saved Cookie is not used or sent anywhere."""
        anonymous = {'proxy': network.get('proxy', ''), 'cookie_content': ''}
        async with self.client(anonymous) as client:
            aweme_id = await self.aweme_id_for(client, task['url'])
        if not aweme_id:return None
        detail = await self.detail_fetcher(aweme_id, anonymous)
        if not isinstance(detail, dict) or not detail:raise PlatformError('抖音没有返回作品详情，作品可能已删除或设为私密')
        title = (detail.get('desc') or '').strip() or aweme_id
        headers = {'user-agent': UA, 'referer': WEB + '/'}
        pictures = image_files(detail)
        if pictures or detail.get('images'):
            if not pictures:raise PlatformError('图集作品中没有可用的图片地址')
            files = [{'url': url, 'kind': 'image'} for url in pictures]
            music = first_url(((detail.get('music') or {}).get('play_url')))
            if music:files.append({'url': music, 'kind': 'audio', 'optional': True, 'label': 'bgm'})
            return {'id': aweme_id, 'title': title, 'headers': headers, 'files': files}
        url = play_url(detail)
        if not url:raise PlatformError('作品详情中没有可用的视频地址')
        return {'url': url, 'id': aweme_id, 'ext': 'mp4', 'title': title, 'headers': headers}
