"""Live subscription configuration, backup import / export and defaults; recording is separate."""
import json
import sqlite3
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .downloads import now

class RoomCheckBusy(Exception):pass


class LiveConfig(BaseModel):
    model_config=ConfigDict(extra='allow')
    platform: str=Field(min_length=1,max_length=100)
    room_url: str=Field(min_length=1,max_length=4096)
    room_id: str | None=None
    anchor_name: str | None=None
    avatar_url: str | None=None
    signature: str | None=None
    quality: str='原画'
    auto_record: bool=True
    monitor_enabled: bool=True
    check_interval: int=Field(default=60,ge=1)
    output_format: str='ts'
    split_enabled: bool=False
    split_duration: int=Field(default=3600,ge=1)
    max_duration: int | None=None
    notification_enabled: bool=True
    notification_end_enabled: bool=False
    proxy: str | None=None
    cookies: str | None=None
    remark: str | None=None
    extra_data: dict | str | None=None

    @field_validator('platform','room_url')
    @classmethod
    def not_blank(cls,value):
        value=value.strip()
        if not value:raise ValueError('平台和直播间不能为空')
        return value


class LiveEdit(BaseModel):
    quality: str | None=Field(default=None,min_length=1,max_length=200)
    auto_record: bool | None=None
    monitor_enabled: bool | None=None
    check_interval: int | None=Field(default=None,ge=1)
    output_format: str | None=Field(default=None,min_length=1,max_length=50)
    split_enabled: bool | None=None
    split_duration: int | None=Field(default=None,ge=1)
    notification_enabled: bool | None=None
    notification_end_enabled: bool | None=None
    remark: str | None=Field(default=None,max_length=4096)


class LiveImport(BaseModel):
    subscriptions: list[dict]=Field(min_length=1,max_length=10000)


class LiveSubscriptions:
    def __init__(self,store,register_monitor=None):
        self.store,self.register_monitor=store,register_monitor
        self.monitor_status=None;self.active_checks=set()

    def decode(self,row,private=False):
        if row is None:return None
        config=json.loads(row['config'])
        if not private:
            config['has_cookies']=bool(config.pop('cookies',None))
            config['has_proxy']=bool(config.pop('proxy',None))
            state=self.store.one('SELECT * FROM live_room_states WHERE subscription_id=?',(row['id'],))
            config['last_detection']={**json.loads(state['result']),'checked_at':state['checked_at']} if state else None
        runtime=self.monitor_status(row['id'],config) if self.monitor_status else {
            'monitor_available':False,'recording_available':False,'reason':'当前仅管理配置，监控和录制尚未接入'}
        return {**config,'id':row['id'],'created_at':row['created_at'],'updated_at':row['updated_at'],'runtime':runtime}

    def list(self):
        return [self.decode(row) for row in self.store.all('SELECT * FROM live_subscriptions ORDER BY created_at DESC,id')]

    async def check(self,subscription_id,detector,network):
        subscription_id=str(subscription_id)
        if subscription_id in self.active_checks:raise RoomCheckBusy()
        self.active_checks.add(subscription_id)
        try:return await self._check(subscription_id,detector,network)
        finally:self.active_checks.discard(subscription_id)

    async def _check(self,subscription_id,detector,network):
        row=self.store.one('SELECT * FROM live_subscriptions WHERE id=?',(str(subscription_id),))
        if row is None:raise LookupError('直播订阅不存在')
        config=json.loads(row['config'])
        result=await detector.detect(config,network.for_url(config['room_url']))
        checked_at=now()
        with self.store.connect() as db:
            db.execute('INSERT INTO live_room_states VALUES (?,?,?) ON CONFLICT(subscription_id) '
                       'DO UPDATE SET result=excluded.result,checked_at=excluded.checked_at',
                       (str(subscription_id),json.dumps(result,ensure_ascii=False),checked_at))
        return {**result,'checked_at':checked_at}

    async def import_config(self,items):
        result={'total':len(items),'success':0,'failed':0,'errors':[],'monitor_warnings':[]}
        for index,item in enumerate(items,1):
            try:
                # Parse string booleans directly: bool("false") is incorrect.
                raw={key:value for key,value in item.items() if key not in ('id','created_at','updated_at','runtime')}
                for field,default in {'quality':'原画','check_interval':60,'output_format':'ts','split_duration':3600}.items():
                    if not raw.get(field):raw[field]=default
                config=LiveConfig.model_validate(raw)
                identity=json.dumps([config.platform,config.room_url],ensure_ascii=False)
                subscription_id=str(uuid.uuid4());timestamp=now()
                with self.store.connect() as db:
                    db.execute('INSERT INTO live_subscriptions VALUES (?,?,?,?,?)',
                               (subscription_id,identity,config.model_dump_json(),timestamp,timestamp))
            except sqlite3.IntegrityError:
                result['failed']+=1;result['errors'].append(f'第 {index} 项：相同平台和直播间已存在');continue
            except (ValueError,TypeError):
                result['failed']+=1;result['errors'].append(f'第 {index} 项：直播订阅字段无效');continue
            result['success']+=1
            if self.register_monitor is None:
                result['monitor_warnings'].append({'id':subscription_id,'message':'监控尚未接入，配置已保存'})
            else:
                try:await self.register_monitor(subscription_id,config.room_url,config.platform,config.check_interval)
                except Exception:
                    result['monitor_warnings'].append({'id':subscription_id,'message':'监控注册失败，配置已保存'})
        return result

    def edit(self,subscription_id,payload):
        fields=payload.model_dump(exclude_unset=True)
        if any(value is None for value in fields.values()):raise ValueError('编辑字段不能为 null')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM live_subscriptions WHERE id=?',(str(subscription_id),)).fetchone()
            if row is None:raise LookupError('直播订阅不存在')
            config=LiveConfig.model_validate({**json.loads(row['config']),**fields})
            db.execute('UPDATE live_subscriptions SET config=?,updated_at=? WHERE id=?',
                       (config.model_dump_json(),now(),str(subscription_id)))
        return self.decode(self.store.one('SELECT * FROM live_subscriptions WHERE id=?',(str(subscription_id),)))

    def export(self):
        items=[self.decode(row,True) for row in self.store.all('SELECT * FROM live_subscriptions ORDER BY created_at,id')]
        for item in items:
            for field in ('id','updated_at','runtime'):item.pop(field,None)
        return {'export_time':now(),'total_subscriptions':len(items),'subscriptions':items}
