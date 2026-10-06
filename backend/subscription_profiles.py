"""Typed profile identity resolution; never treat a video URL as a channel."""
import re
from urllib.parse import parse_qs, urlsplit
from typing import Literal

from pydantic import BaseModel, Field
from .media import share_url
from .subscriptions import SubscriptionConfig


class ProfileInput(BaseModel):
    platform: Literal['youtube','youtube_playlist','bilibili','douyin']
    profile_url: str = Field(min_length=1,max_length=8192)
    youtube_tab_type: Literal['videos','shorts'] = 'videos'
    nickname: str = Field(default='',max_length=256)
    update_interval: float = Field(default=28800,ge=0,allow_inf_nan=False)
    auto_download: bool = True


def profile_url(payload):
    if payload.platform=='douyin':raise ValueError('抖音订阅由平台适配器解析')
    if payload.platform=='youtube_playlist' and re.fullmatch(r'PL[A-Za-z0-9_-]{8,}',payload.profile_url.strip()):
        return 'https://www.youtube.com/playlist?list='+payload.profile_url.strip()
    url=share_url(payload.profile_url)
    parsed=urlsplit(url)
    parts=[segment for segment in parsed.path.split('/') if segment]
    if payload.platform.startswith('youtube'):
        if parsed.hostname not in ('youtube.com','www.youtube.com','m.youtube.com'):
            raise ValueError('请输入 YouTube 频道或歌单链接')
        if payload.platform=='youtube_playlist':
            playlist=parse_qs(parsed.query).get('list',[''])[0]
            if not re.fullmatch(r'[A-Za-z0-9_-]+',playlist):raise ValueError('歌单链接缺少有效 list 标识')
            return 'https://www.youtube.com/playlist?list='+playlist
        if not parts:raise ValueError('链接缺少频道标识')
        if parts[0].startswith('@') and len(parts[0])>1:
            base=parts[0]
        elif parts[0] in ('channel','c','user') and len(parts)>=2:
            base='/'.join(parts[:2])
        else:raise ValueError('请使用频道主页，单个视频不能作为作者订阅')
        return f'https://www.youtube.com/{base}/{payload.youtube_tab_type}'
    if parsed.hostname!='space.bilibili.com' or not parts or not parts[0].isdigit():
        raise ValueError('请输入 B 站作者空间链接')
    if 'fid' in parse_qs(parsed.query,keep_blank_values=True):
        raise ValueError('链接包含收藏夹标识，不能作为作者主页；收藏订阅入口尚未完成')
    if len(parts)>1 and parts[1] not in ('video','upload'):
        raise ValueError('收藏与合集身份解析尚未完成，请先使用作者主页或导入配置')
    return f'https://space.bilibili.com/{parts[0]}/video'


class ProfileResolver:
    def __init__(self,inspector,network,registry=None):self.inspector,self.network,self.registry=inspector,network,registry

    async def resolve(self,payload):
        adapter=self.registry.get(payload.platform) if self.registry else None
        if adapter is not None:
            return await adapter.resolve(payload,self.network.for_url(adapter.home_url))
        url=profile_url(payload)
        info=await self.inspector.raw_info(url,self.network.for_url(url),profile=True)
        if info.get('_type') not in ('playlist','multi_video'):
            raise ValueError('该链接未解析为作者或歌单')
        if payload.platform=='youtube':
            user_id=info.get('channel_id') or info.get('id')
            if not isinstance(user_id,str) or not re.fullmatch(r'UC[A-Za-z0-9_-]+',user_id):
                raise ValueError('解析结果没有可用的 YouTube 频道标识')
        else:
            user_id=str(info.get('id') or '')
            expected=parse_qs(urlsplit(url).query).get('list',[''])[0] if payload.platform=='youtube_playlist' else urlsplit(url).path.split('/')[1]
            if user_id!=expected:raise ValueError('平台返回的身份与请求不一致')
        nickname=payload.nickname.strip() or (info.get('title') if payload.platform=='youtube_playlist' else
                   info.get('channel') or info.get('uploader')) or user_id
        return SubscriptionConfig(platform=payload.platform,user_id=user_id,profile_url=url,nickname=nickname,
            nickname_locked=bool(payload.nickname.strip()),update_interval=payload.update_interval,
            auto_download=payload.auto_download,youtube_tab_type=payload.youtube_tab_type if payload.platform=='youtube' else None,
            subscription_type='playlist' if payload.platform=='youtube_playlist' else 'user',
            avatar_url=info.get('thumbnail'))
