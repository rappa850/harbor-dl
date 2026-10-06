"""Recover configuration lifecycle first; platform synchronization is separate."""
import json
import sqlite3
import uuid
from typing import Literal
from pydantic import BaseModel, Field, field_validator

from .downloads import now

Platform = Literal['douyin','douyin_favorite','douyin_collection','xiaohongshu','youtube',
                   'youtube_playlist','bilibili','bilibili_collection','tiktok','instagram','x','netease','kuaishou']


class SubscriptionConfig(BaseModel):
    platform: Platform
    user_id: str = Field(min_length=1,max_length=512)
    profile_url: str = Field(default='',max_length=4096)
    nickname: str = Field(default='',max_length=256)
    storage_name: str = Field(default='',max_length=256)
    nickname_locked: bool = False
    subscription_type: Literal['user','favorite','playlist','collection'] = 'user'
    youtube_tab_type: Literal['videos','shorts'] | None = None
    collection_id: str | None = None
    collection_title: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    update_interval: float = Field(default=28800,ge=0,allow_inf_nan=False)
    auto_download: bool = True
    generate_nfo: bool = True
    skip_bilibili_upower: bool = False
    quality: str = Field(default='best',min_length=1,max_length=200)
    status: Literal['active','paused','error','invalid'] = 'active'
    signature: str | None = None
    avatar_url: str | None = None
    follower_count: int | None = None
    like_count: int | None = None
    video_count: int | None = None

    @field_validator('user_id')
    @classmethod
    def identity_not_blank(cls,value):
        if not value.strip():raise ValueError('用户或集合标识不能为空')
        return value.strip()


class SubscriptionEdit(BaseModel):
    nickname: str | None = Field(default=None,max_length=256)
    update_interval: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    auto_download: bool | None = None
    generate_nfo: bool | None = None
    skip_bilibili_upower: bool | None = None
    quality: str | None = Field(default=None,min_length=1,max_length=200)


class SubscriptionImport(BaseModel):
    subscriptions: list[dict] = Field(min_length=1,max_length=10000)


class Subscriptions:
    def __init__(self,store):self.store=store

    def decode(self,row):
        if row is None:return None
        return {**json.loads(row['config']),'id':row['id'],'created_at':row['created_at'],'updated_at':row['updated_at'],
                'runtime':{'sync_available':False,'reason':'此平台的身份解析、检查与同步适配尚未提供'}}

    def list(self):
        return [self.decode(row) for row in self.store.all('SELECT * FROM subscriptions ORDER BY created_at DESC,id')]

    def get(self,subscription_id):
        return self.decode(self.store.one('SELECT * FROM subscriptions WHERE id=?',(str(subscription_id),)))

    def add_config(self,payload):
        data=payload.model_dump()
        if data['platform']=='bilibili_collection':data['subscription_type']='collection'
        if data['platform']=='youtube_playlist':data['subscription_type']='playlist'
        if data['platform']=='youtube' and not data['youtube_tab_type']:data['youtube_tab_type']='videos'
        identity=json.dumps([data[k] for k in ('platform','user_id','subscription_type','youtube_tab_type','collection_id')],ensure_ascii=False)
        data['storage_name']=data['storage_name'] or data['nickname'] or data['user_id']
        if data['update_interval']==0:data['status']='paused'
        timestamp=now();subscription_id=str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute('INSERT INTO subscriptions VALUES (?,?,?,?,?)',
                (subscription_id,identity,json.dumps(data,ensure_ascii=False),timestamp,timestamp))
        return self.get(subscription_id)

    def import_config(self,items):
        result={'total':len(items),'success':0,'failed':0,'errors':[]}
        for index,item in enumerate(items,1):
            try:
                payload=SubscriptionConfig.model_validate(item)
                self.add_config(payload)
                result['success']+=1
            except sqlite3.IntegrityError:
                result['failed']+=1;result['errors'].append(f'第 {index} 项：订阅身份重复')
            except ValueError:
                result['failed']+=1;result['errors'].append(f'第 {index} 项：订阅配置字段无效')
        return result

    def edit(self,subscription_id,payload):
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM subscriptions WHERE id=?',(str(subscription_id),)).fetchone()
            if row is None:return None
            data=json.loads(row['config'])
            fields=payload.model_dump(exclude_unset=True)
            if any(value is None for value in fields.values()):raise ValueError('编辑字段不能为 null')
            if 'nickname' in fields:data['nickname_locked']=True
            if 'update_interval' in fields:
                interval=fields['update_interval']
                fields['update_interval']=max(3600,interval) if interval>0 else 0
                data['status']='active' if interval>0 else 'paused'
            data.update(fields)
            db.execute('UPDATE subscriptions SET config=?,updated_at=? WHERE id=?',
                       (json.dumps(data,ensure_ascii=False),now(),str(subscription_id)))
        return self.get(subscription_id)

    def delete(self,subscription_id):
        with self.store.connect() as db:
            db.execute('DELETE FROM subscription_states WHERE subscription_id=?',(str(subscription_id),))
            return bool(db.execute('DELETE FROM subscriptions WHERE id=?',(str(subscription_id),)).rowcount)

    def export(self):
        records=self.list()
        fields=SubscriptionConfig.model_fields
        return {'export_time':now(),'total_subscriptions':len(records),
                'subscriptions':[{**{key:record[key] for key in fields},'created_at':record['created_at']} for record in records]}
