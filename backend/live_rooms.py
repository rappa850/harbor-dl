"""Manual Bilibili room detection, separate from scheduling and recording."""
import http.cookiejar
import re
from urllib.parse import urlsplit
import httpx
from .network import cookie_file,validate_proxy


class RoomDetectionError(Exception):pass

QUALITY_QN={'原画':10000,'4K':20000,'蓝光':400,'超清':250,'高清':150}


def valid_stream_url(value):
    try:
        parsed=urlsplit(value)
        if parsed.scheme in ('http','https') and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except (TypeError,ValueError):pass
    raise RoomDetectionError('平台未返回有效 HTTP 直播流')


def client_options(config,network):
    content=config.get('cookies') or network.get('cookie_content','')
    jar=http.cookiejar.MozillaCookieJar()
    if content:
        with cookie_file(content,'https://api.live.bilibili.com') as path:
            jar=http.cookiejar.MozillaCookieJar(path);jar.load(ignore_discard=True,ignore_expires=True)
        for cookie in jar:
            if cookie.expires==0:cookie.expires=None;cookie.discard=True
    return {'timeout':15,'follow_redirects':False,'trust_env':False,
            'proxy':validate_proxy(config.get('proxy') or network.get('proxy','')) or None,
            'cookies':jar,'headers':{'User-Agent':'Mozilla/5.0','Referer':'https://live.bilibili.com/'}}


def bilibili_room_id(url):
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or parsed.hostname!='live.bilibili.com' or parsed.username or parsed.password:
        raise ValueError('当前仅支持 live.bilibili.com 的直播间完整链接')
    if parsed.port not in (None,80,443) or not re.fullmatch(r'/\d+/?',parsed.path):
        raise ValueError('直播间链接缺少有效数字房间标识')
    return parsed.path.strip('/')


class BilibiliRooms:
    def __init__(self,client_factory=httpx.AsyncClient):self.client_factory=client_factory

    async def detect(self,config,network):
        if config['platform']!='bilibili':raise ValueError('此平台的直播检测适配尚未接入')
        room_id=bilibili_room_id(config['room_url'])
        api='https://api.live.bilibili.com'
        try:
            async with self.client_factory(**client_options(config,network)) as client:
                async def fetch(path,params):
                    response=await client.get(api+path,params=params)
                    response.raise_for_status();data=response.json()
                    if data.get('code')!=0 or not isinstance(data.get('data'),dict):raise RoomDetectionError('平台未返回有效直播间信息')
                    return data['data']
                room=await fetch('/room/v1/Room/room_init',{'id':room_id})
                actual=room.get('room_id');uid=room.get('uid');status=room.get('live_status')
                if not str(actual or '').isdigit() or not str(uid or '').isdigit() or status not in (0,1,2):
                    raise RoomDetectionError('平台直播间信息缺少有效字段')
                anchor=await fetch('/live_user/v1/Master/info',{'uid':uid})
                info=anchor.get('info')
                if not isinstance(info,dict) or not isinstance(info.get('uname'),str) or not info['uname']:
                    raise RoomDetectionError('平台主播信息缺少有效字段')
                return {'platform':'bilibili','room_id':str(actual),'room_url':f'https://live.bilibili.com/{actual}',
                        'anchor_name':info['uname'],'avatar_url':info.get('face'),
                        'is_live':status==1,'live_status':status}
        except RoomDetectionError:raise
        except (httpx.HTTPError,ValueError,TypeError,AttributeError,ImportError) as exc:
            # Never persist exception text that might contain credentials.
            raise RoomDetectionError('直播间检测失败，请检查网络、凭据或平台返回') from exc

    async def stream(self,config,network):
        room=await self.detect(config,network)
        if not room['is_live']:return {**room,'url':None,'format':None}
        requested=QUALITY_QN.get(config.get('quality'),10000)
        try:return await self._stream(room,config,network,requested)
        except RoomDetectionError:
            if not (config.get('cookies') or network.get('cookie_content')):raise
            guest_config={**config,'cookies':None};guest_network={**network,'cookie_content':''}
            result=await self._stream(room,guest_config,guest_network,requested)
            result['guest_fallback']=True
            return result

    async def _stream(self,room,config,network,requested):
        api='https://api.live.bilibili.com'
        try:
            async with self.client_factory(**client_options(config,network)) as client:
                async def get(path,params):
                    response=await client.get(api+path,params=params);response.raise_for_status()
                    value=response.json()
                    if not isinstance(value,dict):raise RoomDetectionError('直播流响应格式无效')
                    return value
                value=await get('/room/v1/Room/playUrl',{'cid':room['room_id'],'qn':requested,'platform':'web'})
                data=value.get('data') or {}
                urls=data.get('durl') if value.get('code')==0 else None
                actual=data.get('quality')
                if urls:
                    candidates=[entry.get('url') for entry in urls if isinstance(entry,dict) and entry.get('url')]
                    if not candidates:raise RoomDetectionError('直播流列表为空')
                    selected=next((url for url in candidates if 'd1--cn-gotcha' in url),candidates[-1])
                else:
                    value=await get('/xlive/web-room/v2/index/getRoomPlayInfo',{
                        'room_id':room['room_id'],'protocol':'0,1','format':'0,1,2','codec':'0,1,2',
                        'qn':requested,'platform':'web','ptype':'8','dolby':'5','panorama':'1','hdr_type':'0,1'})
                    data=value.get('data') or {}
                    if value.get('code')!=0:raise RoomDetectionError('平台拒绝直播流请求')
                    if data.get('live_status')==0:return {**room,'is_live':False,'url':None,'format':None}
                    streams=(data.get('playurl_info') or {}).get('playurl',{}).get('stream',[])
                    choices=[]
                    for stream in streams:
                        for format_info in stream.get('format',[]):
                            for codec in format_info.get('codec',[]):
                                qn=codec.get('current_qn')
                                if not isinstance(qn,int):continue
                                for host in codec.get('url_info',[]):
                                    url=(host.get('host') or '')+(codec.get('base_url') or '')+(host.get('extra') or '')
                                    if url:choices.append((qn,url))
                    if not choices:raise RoomDetectionError('平台未返回可用直播流')
                    lower=[choice for choice in choices if choice[0]<=requested]
                    actual,selected=max(lower,key=lambda choice:choice[0]) if lower else min(choices,key=lambda choice:choice[0])
                selected=valid_stream_url(selected)
                return {**room,'url':selected,'format':'flv' if '.flv' in urlsplit(selected).path else 'm3u8',
                        'requested_qn':requested,'actual_qn':actual,'guest_fallback':False,
                        'headers':{'User-Agent':'Mozilla/5.0','Referer':'https://live.bilibili.com/'}}
        except RoomDetectionError:raise
        except (httpx.HTTPError,ValueError,TypeError,AttributeError,ImportError) as exc:
            raise RoomDetectionError('直播流解析失败，请检查网络、凭据或平台返回') from exc
