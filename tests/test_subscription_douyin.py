import asyncio
import functools
import json
import tempfile
import threading
import unittest
import uuid
import wave
from datetime import datetime,timedelta,timezone
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.subscription_platforms import PlatformError,default_registry
from backend.subscription_platforms.douyin import cookie_header,entry_from_aweme,image_files,judge_detail,parse_sec_uid,play_url
from tests.test_task_lifecycle import until

SEC='MS4wLjABAAAAexampleSecUid0123456789abcdefghij'
SHORT='https://v.douyin.com/AbCdEf/'


def aweme(number,image=False,top=False,created=1_700_000_000):
    item={'aweme_id':str(7_000_000_000_000_000_000+number),'desc':f'作品 {number}','create_time':created-number,
          'is_top':int(top),'aweme_type':68 if image else 0,
          'video':{'duration':12_500,'cover':{'url_list':[f'https://p3.example/cover{number}.jpg']}}}
    if image:item['images']=[{'url_list':['https://p3.example/i.jpg']}]
    return item


class FakeDouyin:
    """Stands in for douyin.com; records every request so signing and cookies can be asserted."""
    def __init__(self):
        self.requests=[];self.pages={};self.empty=False;self.fail_first=0
        self.profile={'status_code':0,'user':{'sec_uid':SEC,'nickname':'示例博主','signature':'简介','follower_count':1200,
            'total_favorited':99,'aweme_count':40,'avatar_larger':{'url_list':['https://p3.example/a.jpg']}}}

    def serve(self,items_per_page):
        """pages[cursor] = (items, next cursor or None)."""
        self.pages={};cursor=0
        for index,items in enumerate(items_per_page):
            last=index==len(items_per_page)-1
            nxt=None if last else cursor+1000
            self.pages[cursor]=(items,nxt);cursor=nxt or cursor

    def __call__(self,request):
        self.requests.append(request)
        host,path=request.url.host,request.url.path
        if host=='v.douyin.com':
            return httpx.Response(302,headers={'location':f'https://www.iesdouyin.com/share/user/{SEC}?from=short'})
        if host=='www.iesdouyin.com':return httpx.Response(200,text='ok')
        if self.empty:return httpx.Response(200,content=b'')
        if self.fail_first>0:
            self.fail_first-=1;return httpx.Response(403,text='blocked')
        query=dict(request.url.params)
        if path.endswith('/user/profile/other/'):return httpx.Response(200,json=self.profile)
        if path.endswith('/aweme/post/'):
            items,nxt=self.pages[int(query['max_cursor'])]
            return httpx.Response(200,json={'status_code':0,'aweme_list':items,'has_more':int(nxt is not None),'max_cursor':nxt or 0})
        return httpx.Response(404)

    def calls(self,suffix):return [r for r in self.requests if r.url.path.endswith(suffix)]


async def no_sleep(_):return None


class DouyinCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.fake=FakeDouyin()
        self.detail=None;self.detail_calls=[]
        registry=default_registry(transport=httpx.MockTransport(self.fake),sleep=no_sleep,detail_fetcher=self.fetch_detail)
        self.app=create_app(self.temp.name,platform_registry=registry,scheduler_options={'startup_delay':3600})
        self.client=TestClient(self.app)
        self.client.post('/api/setup',json={'username':'admin','password':'test-password-123'})

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    async def fetch_detail(self,aweme_id,network):
        """Stands in for the anonymous browser page; records what it was given."""
        self.detail_calls.append((aweme_id,dict(network)))
        if self.detail is None:raise PlatformError('抖音没有返回作品详情，作品可能已删除或设为私密')
        return self.detail

    def add(self,url=f'https://www.douyin.com/user/{SEC}',**extra):
        return self.client.post('/api/subscriptions',json={'platform':'douyin','profile_url':url,**extra})

    def subscription(self,**extra):
        response=self.add(**extra);self.assertEqual(response.status_code,201,response.text)
        return response.json()


class IdentityTests(DouyinCase):
    def test_helpers(self):
        self.assertEqual(parse_sec_uid(f'https://www.douyin.com/user/{SEC}?modal_id=1'),SEC)
        self.assertIsNone(parse_sec_uid(SHORT))
        for bad in ('https://www.douyin.com/video/7000000000000000001','https://www.douyin.com/user/self','https://example.com/user/'+SEC):
            with self.assertRaises(ValueError):parse_sec_uid(bad)
        self.assertEqual(cookie_header('Cookie: a=1; b=2'),'a=1; b=2')
        self.assertEqual(cookie_header('# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tTRUE\t0\tttwid\tabc\n'),'ttwid=abc')
        self.assertIsNone(entry_from_aweme({'aweme_id':'abc'}));self.assertIsNone(entry_from_aweme('x'))
        self.assertEqual(play_url({'video':{'play_addr':{'url_list':['https://sf6.example/obj/ies-music/1.mp3']}}}),None)   # a music track is never "the video"
        self.assertEqual(image_files({'images':[{'download_url_list':['https://i.example/a.webp'],'url_list':['https://i.example/b.webp']},{'url_list':['https://i.example/c.jpg']},{}]}),['https://i.example/a.webp','https://i.example/c.jpg'])
        self.assertEqual(judge_detail('')[0],'retry');self.assertEqual(judge_detail('{"status_code":0,"aweme_detail":null}')[0],'retry')
        self.assertEqual(judge_detail('{"aweme_detail":{"aweme_id":"1"}}')[0],'ok')
        self.assertEqual(judge_detail('{"status_code":0,"aweme_detail":null,"filter_detail":{"notice":"私密"}}')[0],'fail')
        self.assertEqual(entry_from_aweme(aweme(1))[1]['url'].split('/')[-2],'video')
        image=entry_from_aweme(aweme(2,image=True))[1]
        self.assertEqual(image['extra_data']['media_type'],'image');self.assertIsNone(image['duration']);self.assertIn('/note/',image['url'])
        self.assertEqual(play_url({'video':{'play_addr':{'url_list':['https://v.example/playwm/x']},
            'bit_rate':[{'bit_rate':1,'play_addr':{'url_list':['https://v.example/low']}},{'bit_rate':9,'play_addr':{'url_list':['https://v.example/playwm/hi']}}]}}),'https://v.example/play/hi')

    def test_add_by_profile_signs_requests_and_uses_saved_cookie(self):
        self.client.put('/api/network/cookies/douyin',json={'cookie_content':'ttwid=secret1; msToken=tok-abc; s_v_web_id=verify_xyz'})
        item=self.subscription(nickname='')
        self.assertEqual((item['platform'],item['user_id'],item['nickname']),('douyin',SEC,'示例博主'))
        self.assertEqual((item['follower_count'],item['video_count'],item['like_count']),(1200,40,99))
        self.assertEqual(item['profile_url'],f'https://www.douyin.com/user/{SEC}')
        request=self.fake.calls('/user/profile/other/')[0]
        self.assertEqual(request.url.params['sec_user_id'],SEC);self.assertTrue(request.url.params['a_bogus'])
        self.assertEqual(request.url.params['msToken'],'tok-abc');self.assertEqual(request.url.params['verifyFp'],'verify_xyz')
        self.assertEqual(request.headers['cookie'],'ttwid=secret1; msToken=tok-abc; s_v_web_id=verify_xyz')
        self.assertEqual(request.headers['referer'],f'https://www.douyin.com/user/{SEC}')
        self.assertEqual(self.add().status_code,409)

    def test_requests_carry_the_device_id_from_the_uifid_cookie(self):
        self.client.put('/api/network/cookies/douyin',json={'cookie_content':'ttwid=t; UIFID=device-123; UIFID_TEMP=temp-9'})
        self.subscription(nickname='')
        self.assertEqual(self.fake.calls('/user/profile/other/')[0].url.params['uifid'],'device-123')

    def test_uifid_rejection_is_reported_as_a_login_problem(self):
        def blocked(request):
            return httpx.Response(403,text='Blocked by ArgusSecurityPlugin Uifid Not Found')
        self.app.state.catalog.registry.get('douyin').transport=httpx.MockTransport(blocked)
        response=self.add()
        self.assertEqual(response.status_code,502)
        self.assertIn('UIFID',response.json()['detail'])

    def test_short_link_custom_nickname_and_rejections(self):
        response=self.add(url=f'分享 {SHORT} 复制打开',nickname='我的备注')
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['user_id'],SEC)
        self.assertTrue(response.json()['nickname_locked']);self.assertEqual(response.json()['nickname'],'我的备注')
        self.assertEqual(self.add(url='https://www.douyin.com/video/7000000000000000001').status_code,422)
        self.assertEqual(self.add(url='not a link').status_code,422)
        self.fake.profile['user']['sec_uid']='MS4wLjABAAAAdifferentUser000000000000'
        self.client.delete('/api/subscriptions/'+response.json()['id'])
        self.assertEqual(self.add().status_code,422)

    def test_transient_403_is_retried_with_a_new_signature_but_not_forever(self):
        self.fake.fail_first=2
        self.assertEqual(self.add().status_code,201)
        first,second,third=self.fake.calls('/user/profile/other/')
        self.assertEqual(len({first.url.params['a_bogus'],second.url.params['a_bogus'],third.url.params['a_bogus']}),3)
        self.client.delete('/api/subscriptions/'+self.client.get('/api/subscriptions').json()['items'][0]['id'])
        self.fake.requests.clear();self.fake.fail_first=99
        response=self.add();self.assertEqual(response.status_code,502);self.assertIn('403',response.json()['detail'])
        self.assertEqual(len(self.fake.calls('/user/profile/other/')),3)              # gave up after three attempts

    def test_risk_control_and_auth(self):
        self.fake.empty=True
        response=self.add();self.assertEqual(response.status_code,502);self.assertIn('Cookie',response.json()['detail'])
        self.fake.empty=False;self.fake.profile={'status_code':0,'user':{}}
        self.assertEqual(self.add().status_code,502)
        self.fake.profile={'status_code':8,'status_msg':'rate'}
        self.assertIn('8',self.add().json()['detail'])
        self.client.post('/api/auth/logout')
        self.assertEqual(self.add().status_code,401)

    def test_unsupported_douyin_types_are_flagged_not_silently_fetched(self):
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[
            {'platform':'douyin','user_id':SEC,'subscription_type':'favorite'},{'platform':'douyin_collection','user_id':'7407257750834513958','subscription_type':'collection'}]})
        items=self.client.get('/api/subscriptions').json()['items']
        favorite=next(i for i in items if i['subscription_type']=='favorite')
        self.assertFalse(favorite['runtime']['manual_sync_available']);self.assertIn('尚未适配',favorite['runtime']['unavailable_reason'])
        self.assertEqual(self.client.post('/api/subscriptions/'+favorite['id']+'/sync').status_code,422)
        self.assertEqual(self.client.post('/api/subscriptions/'+favorite['id']+'/check').status_code,422)


class CatalogTests(DouyinCase):
    def setUp(self):
        super().setUp()
        self.item=self.subscription(auto_download=False);self.base='/api/subscriptions/'+self.item['id']

    def test_full_sync_pages_until_platform_ends(self):
        self.fake.serve([[aweme(i) for i in range(1,19)],[aweme(i) for i in range(19,37)],[aweme(37),aweme(38,image=True),{'aweme_id':'bad'}]])
        result=self.client.post(self.base+'/sync');self.assertEqual(result.status_code,200,result.text)
        self.assertEqual((result.json()['fetched'],result.json()['new_videos_count']),(38,38))
        self.assertEqual([r.url.params['max_cursor'] for r in self.fake.calls('/aweme/post/')],['0','1000','2000'])
        self.assertEqual(self.client.get(self.base+'/videos/stats').json()['total'],38)
        self.assertEqual(self.client.post(self.base+'/sync').json()['new_videos_count'],0)
        image=next(v for v in self.client.get(self.base+'/videos?page_size=100').json()['videos'] if v['extra_data']['media_type']=='image')
        self.assertEqual(image['status'],'not_downloaded')

    def test_bad_cursor_or_midway_failure_keeps_stored_catalog(self):
        self.fake.serve([[aweme(1)]]);self.client.post(self.base+'/sync')
        items,_=self.fake.pages[0];self.fake.pages[0]=(items,0)   # claims more pages but repeats cursor
        response=self.client.post(self.base+'/sync');self.assertEqual(response.status_code,502)
        self.assertEqual(self.client.get(self.base+'/videos').json()['total'],1)
        self.fake.empty=True
        self.assertEqual(self.client.post(self.base+'/sync').status_code,502)
        self.assertEqual(self.client.get(self.base+'/videos').json()['total'],1)


class CheckTests(DouyinCase):
    def make(self,auto):
        item=self.subscription(auto_download=auto)
        return item,'/api/subscriptions/'+item['id']

    def test_first_check_is_limited_and_queues_only_downloadable_new_works(self):
        item,base=self.make(True)
        self.fake.serve([[aweme(i) for i in range(1+n*3,4+n*3)] for n in range(5)])
        first=self.client.post(base+'/check').json()
        self.assertEqual((first['first_check'],first['pages'],first['new_videos_count']),(True,3,9))
        self.assertEqual(first['queued_count'],9)
        tasks=self.client.get('/api/tasks?subscription_id='+item['id']).json()
        self.assertEqual(tasks['total'],9)
        state=self.client.get(base).json()['runtime']
        self.assertEqual((state['last_mode'],state['last_new_count'],state['last_queued_count'],state['last_error']),('manual',9,9,None))
        self.assertTrue(state['last_checked_at']);self.assertTrue(state['next_check_at'])

    def test_incremental_stops_at_known_page_and_skips_pinned(self):
        item,base=self.make(True)
        old=[aweme(i) for i in range(10,13)]
        self.fake.serve([old]);self.client.post(base+'/check')
        self.fake.serve([[aweme(11,top=True),aweme(1),aweme(2,image=True)],[old[0],old[2]],[aweme(99)]])
        second=self.client.post(base+'/check').json()
        self.assertFalse(second['first_check'])
        self.assertEqual(second['new_videos_count'],2);self.assertEqual(second['queued_count'],2)    # pictures are queued too
        self.assertEqual(second['pages'],2)           # page 2 holds only known works -> stop, page 4 never requested
        self.assertEqual(len(self.fake.calls('/aweme/post/')),1+2)
        self.assertEqual(self.client.get('/api/tasks?subscription_id='+item['id']).json()['total'],5)

    def test_auto_download_off_and_failure_state(self):
        item,base=self.make(False)
        self.fake.serve([[aweme(1)]]);result=self.client.post(base+'/check').json()
        self.assertEqual((result['new_videos_count'],result['queued_count']),(1,0))
        self.assertEqual(self.client.get('/api/tasks?subscription_id='+item['id']).json()['total'],0)
        self.fake.empty=True
        self.assertEqual(self.client.post(base+'/check').status_code,502)
        state=self.client.get(base).json()['runtime']
        self.assertIn('Cookie',state['last_error']);self.assertTrue(state['last_success_at'])
        self.assertEqual(self.client.get(base+'/videos').json()['total'],1)

    def test_busy_missing_and_unsupported(self):
        item,base=self.make(False)
        self.app.state.catalog.active.add(item['id'])
        self.assertEqual(self.client.post(base+'/check').status_code,409)
        self.app.state.catalog.active.discard(item['id'])
        self.assertEqual(self.client.post('/api/subscriptions/'+str(uuid.uuid4())+'/check').status_code,404)
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[{'platform':'x','user_id':'a'}]})
        other=next(i for i in self.client.get('/api/subscriptions').json()['items'] if i['platform']=='x')
        self.assertEqual(self.client.post('/api/subscriptions/'+other['id']+'/check').status_code,422)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post(base+'/check').status_code,401)


class BatchAndSearchTests(DouyinCase):
    def setUp(self):
        super().setUp()
        self.item=self.subscription(auto_download=False);self.base='/api/subscriptions/'+self.item['id']
        self.fake.serve([[aweme(i) for i in range(1,7)]]);self.client.post(self.base+'/sync')
        self.videos=self.client.get(self.base+'/videos?page_size=100').json()['videos']

    def test_search_by_title_and_id_and_progress_fields(self):
        found=self.client.get(self.base+'/videos?q=作品 3').json()
        self.assertEqual(found['total'],1);self.assertEqual(found['videos'][0]['title'],'作品 3')
        self.assertEqual(self.client.get(self.base+'/videos?q='+self.videos[0]['video_id'][-6:]).json()['total'],1)
        self.assertEqual(self.client.get(self.base+'/videos?q=不存在').json()['total'],0)
        self.assertIn('task_progress',self.videos[0])

    def test_batch_download_selected_and_everything_pending(self):
        ids=[v['id'] for v in self.videos]
        first=self.client.post(self.base+'/videos/download',json={'video_ids':ids[:2]}).json()
        self.assertEqual((first['requested'],first['queued'],first['skipped']),(2,2,0))
        again=self.client.post(self.base+'/videos/download',json={'video_ids':ids[:3]}).json()
        self.assertEqual((again['queued'],again['skipped']),(1,2))                       # two already queued
        rest=self.client.post(self.base+'/videos/download',json={}).json()
        self.assertEqual((rest['requested'],rest['queued']),(3,3))                       # only works still to do
        self.assertEqual(self.client.get('/api/tasks?subscription_id='+self.item['id']).json()['total'],6)
        none=self.client.post(self.base+'/videos/download',json={}).json()
        self.assertEqual((none['requested'],none['queued']),(0,0))
        bad=self.client.post(self.base+'/videos/download',json={'video_ids':[str(uuid.uuid4())]}).json()
        self.assertEqual(bad['queued'],0);self.assertEqual(len(bad['errors']),1)
        self.assertEqual(self.client.post('/api/subscriptions/'+str(uuid.uuid4())+'/videos/download',json={}).status_code,404)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post(self.base+'/videos/download',json={}).status_code,401)


class SchedulerTests(DouyinCase):
    def test_only_due_active_supported_subscriptions_run_and_failure_waits_an_interval(self):
        scheduler=self.app.state.scheduler;catalog=self.app.state.catalog
        a=self.subscription(update_interval=3600)
        self.fake.serve([[aweme(1)]])
        self.assertEqual(scheduler.due(),[a['id']])                      # never checked
        self.client.post('/api/backup/subscriptions/import',json={'subscriptions':[
            {'platform':'douyin','user_id':'MS4wLjABAAAAotherUser0000000000000000','update_interval':0},
            {'platform':'x','user_id':'z'}]})
        self.assertEqual(scheduler.due(),[a['id']])                      # paused and unsupported never due
        scheduler.sleep=no_sleep
        self.assertEqual(asyncio.run(scheduler.run_once()),1)
        state=catalog.state(a['id']);self.assertEqual(state['last_mode'],'scheduled');before=state['last_success_at']
        self.assertEqual(scheduler.due(),[])
        scheduler.clock=lambda:datetime.now(timezone.utc).timestamp()+3601
        self.assertEqual(scheduler.due(),[a['id']])
        self.fake.empty=True
        self.assertEqual(asyncio.run(scheduler.run_once()),1)           # failure recorded, no exception escapes
        self.assertIn('Cookie',catalog.state(a['id'])['last_error'])
        self.assertEqual(catalog.state(a['id'])['last_success_at'],before)   # success time survives a failure
        scheduler.clock=lambda:datetime.now(timezone.utc).timestamp()+10
        self.assertEqual(scheduler.due(),[])                             # retried only after another interval
        scheduler.clock=lambda:datetime.now(timezone.utc).timestamp()+3601
        self.assertEqual(scheduler.due(),[a['id']])

    def test_lifespan_runs_loop_and_removes_state_with_subscription(self):
        self.fake.serve([[aweme(1)]])
        item=self.subscription(auto_download=False)
        registry=default_registry(transport=httpx.MockTransport(self.fake),sleep=no_sleep)
        app=create_app(self.temp.name,platform_registry=registry,scheduler_options={'startup_delay':0,'tick':3600,'gap':(0,0)})
        with TestClient(app) as client:
            client.post('/api/auth/login',json={'username':'admin','password':'test-password-123'})
            for _ in range(100):
                if app.state.catalog.state(item['id']):break
                import time;time.sleep(0.05)
            self.assertEqual(app.state.catalog.state(item['id'])['last_mode'],'scheduled')
            client.delete('/api/subscriptions/'+item['id'])
            self.assertIsNone(app.state.catalog.state(item['id']))
        self.assertIsNone(app.state.scheduler.task)


class DownloadTests(DouyinCase):
    def serve_media(self):
        folder=Path(self.temp.name)/'served';folder.mkdir()
        with wave.open(str(folder/'clip.wav'),'wb') as clip:
            clip.setnchannels(1);clip.setsampwidth(2);clip.setframerate(8000);clip.writeframes(b'\x01\x00'*8000)
        for number in range(1,5):(folder/f'pic{number}.jpg').write_bytes(b'\xff\xd8\xff\xe0'+bytes([number])*600)
        (folder/'bgm.mp3').write_bytes(b'ID3'+b'\x00'*400)
        (folder/'page.html').write_text('<html>blocked</html>')
        server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(SimpleHTTPRequestHandler,directory=str(folder)))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}'

    def queue(self,*works):
        item=self.subscription(auto_download=False);base='/api/subscriptions/'+item['id']
        self.fake.serve([list(works)]);self.client.post(base+'/sync')
        videos={v['video_id']:v for v in self.client.get(base+'/videos?page_size=100').json()['videos']}
        return base,videos

    def run_task(self,base,video):
        task=self.client.post(base+'/videos/'+video['id']+'/download',json={}).json()
        manager=self.app.state.manager;asyncio.run(manager.run(manager.get(task['id'])))
        return manager.get(task['id'])

    def test_video_downloads_without_login_and_without_the_saved_cookie(self):
        base_url=self.serve_media()
        self.client.put('/api/network/cookies/douyin',json={'cookie_content':'sessionid=user-login-secret'})
        work=aweme(5);base,videos=self.queue(work)
        self.detail={**work,'video':{**work['video'],'bit_rate':[{'bit_rate':5,'play_addr':{'url_list':[f'{base_url}/clip.wav']}}]}}
        done=self.run_task(base,videos[work['aweme_id']])
        self.assertEqual(done['status'],'COMPLETED',done['error'])
        self.assertTrue(done['file_path'].endswith('.mp4'));self.assertIn(work['aweme_id'],done['file_path'])
        self.assertEqual((self.app.state.manager.root/done['file_path']).stat().st_size,16044)
        self.assertEqual(self.client.get(base+'/videos?page_size=100').json()['videos'][0]['status'],'downloaded')
        self.assertEqual(self.detail_calls[0][0],work['aweme_id'])
        self.assertEqual(self.detail_calls[0][1]['cookie_content'],'')            # saved login Cookie never reaches the fetch
        self.assertTrue(self.client.get('/api/network').json()['cookies']['douyin']['exists'])

    def test_picture_post_downloads_every_picture_and_the_music(self):
        base_url=self.serve_media()
        work=aweme(6,image=True);base,videos=self.queue(work)
        self.detail={**work,'images':[{'download_url_list':[f'{base_url}/pic{n}.jpg'],'url_list':['http://127.0.0.1:9/unused.jpg']} for n in range(1,5)],
                     'video':{'duration':0,'play_addr':{'url_list':[f'{base_url}/bgm.mp3']}},
                     'music':{'play_url':{'url_list':[f'{base_url}/bgm.mp3']}}}
        done=self.run_task(base,videos[work['aweme_id']])
        self.assertEqual(done['status'],'COMPLETED',done['error'])
        folder=(self.app.state.manager.root/done['file_path']).parent
        names=sorted(p.name for p in folder.iterdir())
        self.assertEqual(len(names),5);self.assertEqual(sum(n.endswith('.jpg') for n in names),4)
        self.assertTrue(any(n.endswith('_bgm.mp3') for n in names))
        self.assertTrue(done['file_path'].endswith('_01.jpg'))                      # first picture is the primary file
        for number in range(1,5):self.assertTrue(any(n.endswith(f'_0{number}.jpg') for n in names))
        assets=self.client.get('/api/files').json()
        kinds=sorted(a['kind'] for a in (assets['items'] if isinstance(assets,dict) else assets) if a['task_id']==done['id'])
        self.assertEqual(kinds,['audio','image','image','image','image'])
        self.assertEqual(self.client.get(base+'/videos?page_size=100').json()['videos'][0]['status'],'downloaded')
        playable=self.client.get(base+'/playable').json()['items'][0]
        self.assertEqual(playable['kind'],'image')
        gallery=self.client.get('/api/files/'+playable['id']+'/gallery').json()
        self.assertEqual([i['name'][-7:] for i in gallery['images']],[f'_0{n}.jpg' for n in range(1,5)])   # display order
        self.assertEqual(gallery['index'],0);self.assertTrue(gallery['audio']['name'].endswith('_bgm.mp3'))
        self.assertEqual(self.client.get('/api/files/'+gallery['audio']['id']+'/stream').status_code,200)
        later=self.client.get('/api/files/'+gallery['images'][2]['id']+'/gallery').json()
        self.assertEqual(later['index'],2);self.assertEqual(len(later['images']),4)
        self.assertEqual(self.client.get('/api/files/'+gallery['audio']['id']+'/gallery').status_code,422)   # not a picture
        self.assertEqual(self.client.get('/api/files/'+str(uuid.uuid4())+'/gallery').status_code,404)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/files/'+playable['id']+'/gallery').status_code,401)

    def test_missing_music_is_tolerated_but_a_blocked_picture_fails_the_task(self):
        base_url=self.serve_media()
        work=aweme(7,image=True);base,videos=self.queue(work)
        pictures=[{'download_url_list':[f'{base_url}/pic1.jpg']},{'download_url_list':[f'{base_url}/pic2.jpg']}]
        self.detail={**work,'images':pictures,'music':{'play_url':{'url_list':[f'{base_url}/missing.mp3']}}}
        done=self.run_task(base,videos[work['aweme_id']])
        self.assertEqual(done['status'],'COMPLETED',done['error'])
        self.client.delete('/api/tasks/'+done['id']+'?delete_file=true')
        self.detail={**work,'images':[{'download_url_list':[f'{base_url}/page.html']}]}
        failed=self.run_task(base,videos[work['aweme_id']])
        self.assertEqual(failed['status'],'ERROR');self.assertIn('非图片',failed['error'])

    def test_unavailable_work_and_audio_only_detail_fail_with_a_reason(self):
        work=aweme(8);base,videos=self.queue(work)
        self.detail=None                                                              # deleted / private / risk control
        failed=self.run_task(base,videos[work['aweme_id']])
        self.assertEqual(failed['status'],'ERROR');self.assertIn('详情',failed['error'])
        self.assertEqual(next(iter(self.client.get(base+'/videos?page_size=100').json()['videos']))['status'],'failed')
        self.detail={**work,'video':{'play_addr':{'url_list':['https://sf6.example/obj/ies-music/1.mp3']}}}
        again=self.run_task(base,videos[work['aweme_id']])
        self.assertIn('视频地址',again['error'])

    def test_short_profile_link_is_not_treated_as_a_work(self):
        self.assertIsNone(asyncio.run(self.app.state.manager.resolvers['douyin']({'url':'https://v.douyin.com/AbCdEf/'},{'proxy':'','cookie_content':''})))
        self.assertEqual(self.detail_calls,[])


if __name__=='__main__':unittest.main()


class SyncProgressTests(DouyinCase):
    def setUp(self):
        super().setUp()
        self.item=self.subscription(auto_download=False);self.base='/api/subscriptions/'+self.item['id']

    def test_progress_is_reported_per_page_and_cleared_afterwards(self):
        catalog=self.app.state.catalog
        self.assertIsNone(self.client.get(self.base+'/sync-progress').json()['progress'])
        seen=[]
        original=catalog.persist
        def spy(subscription_id,unique):
            seen.append(dict(catalog.progress[str(subscription_id)]));return original(subscription_id,unique)
        catalog.persist=spy
        self.fake.serve([[aweme(i) for i in range(1,19)],[aweme(i) for i in range(19,25)]])
        self.assertEqual(self.client.post(self.base+'/sync').status_code,200)
        self.assertEqual((seen[0]['state'],seen[0]['pages'],seen[0]['fetched'],seen[0]['total']),('running',2,24,40))
        self.assertIsNone(self.client.get(self.base+'/sync-progress').json()['progress'])

    def test_sync_concurrency_defaults_to_one_and_is_adjustable(self):
        self.assertEqual(self.client.get('/api/settings').json()['sync_concurrency'],1)
        saved=self.client.put('/api/settings',json={'concurrency':2,'sync_concurrency':2}).json()
        self.assertEqual(saved['sync_concurrency'],2)
        self.assertEqual(self.client.put('/api/settings',json={'concurrency':3}).json()['sync_concurrency'],2)   # omitted = unchanged
        self.assertEqual(self.client.put('/api/settings',json={'concurrency':2,'sync_concurrency':4}).status_code,422)

    def test_gate_lets_only_the_configured_number_run_at_once(self):
        from backend.subscription_catalog import SyncGate
        async def scenario(limit):
            gate=SyncGate(lambda:limit[0]);running=peak=0
            async def job():
                nonlocal running,peak
                async with gate:
                    running+=1;peak=max(peak,running);await asyncio.sleep(0.02);running-=1
            await asyncio.gather(*(job() for _ in range(4)))
            return peak
        self.assertEqual(asyncio.run(scenario([1])),1)
        self.assertEqual(asyncio.run(scenario([2])),2)
