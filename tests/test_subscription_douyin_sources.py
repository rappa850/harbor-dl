"""Douyin likes, favorites and mixes: identity, paging, shared downloads with author subscriptions."""
import unittest
import httpx
from backend.subscription_platforms.douyin import parse_mix_id
from tests.test_subscription_douyin import DouyinCase,FakeDouyin,SEC,aweme,no_sleep

MIX='7400000000000000001'
COOKIE={'cookie_content':'ttwid=t; UIFID=device-123; sessionid=abc'}
OTHER='MS4wLjABAAAAotherAuthorSecUid0123456789abcdefg'


def by(item,name='原作者',sec=OTHER):
    item['author']={'nickname':name,'sec_uid':sec,'avatar_thumb':{'url_list':['https://p3.example/author.jpg']}}
    return item


class FakeSources(FakeDouyin):
    def __init__(self):
        super().__init__()
        self.lists={'favorite':{},'collection':{},'mix':{}};self.mixes=[]
        self.me={'status_code':0,'user':{'sec_uid':SEC,'nickname':'我'}}
        self.mix_info={'status_code':0,'mix_info':{'mix_id':MIX,'mix_name':'合集甲','desc':'说明','statis':{'updated_to_episode':7},
                       'author':{'nickname':'合集作者','sec_uid':OTHER},'cover_url':{'url_list':['https://p3.example/mix.jpg']}}}

    def serve_list(self,kind,items_per_page):
        pages={};cursor=0
        for index,items in enumerate(items_per_page):
            nxt=None if index==len(items_per_page)-1 else cursor+1000
            pages[cursor]=(items,nxt);cursor=nxt or cursor
        self.lists[kind]=pages

    def answer(self,kind,cursor,key):
        items,nxt=self.lists[kind][cursor]
        return httpx.Response(200,json={'status_code':0,'aweme_list':items,'has_more':int(nxt is not None),key:nxt or 0})

    def __call__(self,request):
        path=request.url.path
        if request.url.host in ('v.douyin.com',) and request.url.path.startswith('/MIX'):
            return httpx.Response(302,headers={'location':f'https://www.iesdouyin.com/share/mix/detail/{MIX}'})
        if path.endswith('/user/profile/self/'):
            self.requests.append(request);return httpx.Response(200,json=self.me)
        if path.endswith('/aweme/favorite/'):
            self.requests.append(request);return self.answer('favorite',int(request.url.params['max_cursor']),'max_cursor')
        if path.endswith('/aweme/listcollection/'):
            self.requests.append(request)
            form=dict(item.split('=') for item in request.content.decode().split('&'))
            return self.answer('collection',int(form['cursor']),'cursor')
        if path.endswith('/mix/detail/'):
            self.requests.append(request);return httpx.Response(200,json=self.mix_info)
        if path.endswith('/mix/aweme/'):
            self.requests.append(request);return self.answer('mix',int(request.url.params['cursor']),'cursor')
        if path.endswith('/mix/listcollection/'):
            self.requests.append(request)
            return httpx.Response(200,json={'status_code':0,'mix_infos':self.mixes,'has_more':0,'cursor':0})
        return super().__call__(request)


class SourcesCase(DouyinCase):
    def setUp(self):
        super().setUp()
        self.fake=FakeSources()
        self.app.state.catalog.registry.get('douyin').transport=httpx.MockTransport(self.fake)

    def login(self):self.client.put('/api/network/cookies/douyin',json=COOKIE)

    def source(self,source,**extra):
        return self.client.post('/api/subscriptions',json={'platform':'douyin','source':source,**extra})

    def made(self,source,**extra):
        response=self.source(source,**extra);self.assertEqual(response.status_code,201,response.text)
        item=response.json();return item,'/api/subscriptions/'+item['id']


class ParseTests(unittest.TestCase):
    def test_mix_ids(self):
        self.assertEqual(parse_mix_id('https://www.douyin.com/collection/7400000000000000001'),'7400000000000000001')
        self.assertEqual(parse_mix_id('https://www.iesdouyin.com/share/mix/detail/7400000000000000001?x=1'),'7400000000000000001')
        self.assertEqual(parse_mix_id('7400000000000000001'),'7400000000000000001')
        self.assertIsNone(parse_mix_id('https://example.com/collection/7400000000000000001'))
        self.assertIsNone(parse_mix_id('https://www.douyin.com/user/abc'))


class AddTests(SourcesCase):
    def test_likes_and_favorites_need_a_login_and_default_to_no_auto_download(self):
        response=self.source('like')
        self.assertEqual(response.status_code,422);self.assertIn('登录',response.json()['detail'])
        self.login()
        like,_=self.made('like');favorite,_=self.made('favorite')
        self.assertEqual((like['subscription_type'],like['user_id'],like['auto_download']),('like',SEC,False))
        self.assertEqual((favorite['subscription_type'],favorite['auto_download']),('favorite',False))
        self.assertEqual(like['nickname'],'我 的点赞');self.assertEqual(favorite['nickname'],'我 的收藏')
        self.assertEqual(self.source('like').status_code,409)
        author=self.subscription(auto_download=False)         # the same account as an author subscription still coexists
        self.assertEqual(author['subscription_type'],'user')
        self.assertEqual(len(self.client.get('/api/subscriptions').json()['items']),3)

    def test_explicit_auto_download_and_lost_login_are_respected(self):
        self.login()
        item,_=self.made('favorite',auto_download=True,nickname='存档')
        self.assertTrue(item['auto_download']);self.assertEqual(item['nickname'],'存档')
        self.fake.me={'status_code':0,'user':{}}
        gone=self.source('like')
        self.assertEqual(gone.status_code,502);self.assertIn('重新登录',gone.json()['detail'])

    def test_mix_by_link_short_link_and_id(self):
        self.login()
        item,_=self.made('mix',profile_url=f'https://www.douyin.com/collection/{MIX}')
        self.assertEqual((item['subscription_type'],item['collection_id'],item['collection_title'],item['nickname']),('mix',MIX,'合集甲','合集甲'))
        self.assertEqual((item['author_name'],item['video_count'],item['auto_download']),('合集作者',7,True))
        self.assertEqual(self.source('mix',profile_url=MIX).status_code,409)
        self.client.delete('/api/subscriptions/'+item['id'])
        self.assertEqual(self.source('mix',profile_url='https://v.douyin.com/MIXabc/').status_code,201)

    def test_mix_input_is_validated(self):
        self.assertEqual(self.source('mix').status_code,422)
        self.assertEqual(self.source('mix',profile_url='https://www.douyin.com/user/abc').status_code,422)
        self.assertEqual(self.source('mix',profile_url='hello').status_code,422)
        self.fake.mix_info={'status_code':0,'mix_info':{'mix_id':'7400000000000000999','mix_name':'别的'}}
        self.assertEqual(self.source('mix',profile_url=MIX).status_code,422)
        self.fake.mix_info={'status_code':0}
        self.assertEqual(self.source('mix',profile_url=MIX).status_code,502)
        other=self.client.post('/api/subscriptions',json={'platform':'bilibili','source':'like','profile_url':'x'})
        self.assertEqual(other.status_code,422)

    def test_collected_mixes_listing(self):
        self.assertEqual(self.client.get('/api/douyin/collections').status_code,422)
        self.login()
        self.fake.mixes=[{'mix_id':MIX,'mix_name':'合集甲','author':{'nickname':'甲'},'statis':{'updated_to_episode':3}},{'mix_id':'bad'}]
        items=self.client.get('/api/douyin/collections').json()['items']
        self.assertEqual([(i['mix_id'],i['title'],i['author'],i['count']) for i in items],[(MIX,'合集甲','甲',3)])


class SyncTests(SourcesCase):
    def test_likes_page_with_max_cursor_and_keep_the_real_author(self):
        self.login()
        item,base=self.made('like')
        self.fake.serve_list('favorite',[[by(aweme(1)),by(aweme(2,image=True),'作者乙','secB')],[aweme(3)]])
        result=self.client.post(base+'/sync').json()
        self.assertEqual((result['fetched'],result['new_videos_count']),(3,3))
        calls=self.fake.calls('/aweme/favorite/')
        self.assertEqual([c.url.params['max_cursor'] for c in calls],['0','1000'])
        self.assertEqual(calls[0].url.params['sec_user_id'],SEC)
        works={w['video_id'][-1]:w for w in self.client.get(base+'/videos').json()['videos']}
        self.assertEqual(works['1']['extra_data']['author']['name'],'原作者')
        self.assertEqual(self.client.get('/api/subscriptions/'+item['id']).json()['runtime']['stored_videos'],3)
        self.assertEqual(self.client.get('/api/tasks?subscription_id='+item['id']).json()['total'],0)    # nothing downloads by itself

    def test_favorites_use_post_with_form_cursor(self):
        self.login()
        item,base=self.made('favorite')
        self.fake.serve_list('collection',[[aweme(1)],[aweme(2)]])
        result=self.client.post(base+'/sync').json()
        self.assertEqual(result['fetched'],2)
        calls=self.fake.calls('/aweme/listcollection/')
        self.assertEqual([c.method for c in calls],['POST','POST'])
        self.assertIn('cursor=1000',calls[1].content.decode());self.assertIn('a_bogus',str(calls[0].url))

    def test_mix_pages_by_cursor(self):
        self.login()
        item,base=self.made('mix',profile_url=MIX,auto_download=False)
        self.fake.serve_list('mix',[[aweme(1)],[aweme(2)],[aweme(3)]])
        self.assertEqual(self.client.post(base+'/sync').json()['fetched'],3)
        self.assertEqual({c.url.params['mix_id'] for c in self.fake.calls('/mix/aweme/')},{MIX})

    def test_personal_lists_pause_longer_between_pages_and_need_the_login(self):
        delays=[]
        async def record(seconds):delays.append(seconds)
        adapter=self.app.state.catalog.registry.get('douyin');adapter.sleep=record;adapter.page_delay=(1.0,1.0)
        self.login()
        like,likes=self.made('like');user=self.subscription(auto_download=False)
        self.fake.serve_list('favorite',[[aweme(1)],[aweme(2)]]);self.fake.serve([[aweme(1)],[aweme(2)]])
        self.client.post(likes+'/sync');personal=list(delays);delays.clear()
        self.client.post('/api/subscriptions/'+user['id']+'/sync')
        self.assertGreater(personal[0],delays[0])
        self.client.delete('/api/network/cookies/douyin')
        failed=self.client.post(likes+'/sync')
        self.assertEqual(failed.status_code,502)
        self.assertTrue(self.client.get(likes).json()['runtime']['auth_expired'])

    def test_incremental_check_of_likes_stops_at_known_pages(self):
        self.login()
        item,base=self.made('like')
        self.fake.serve_list('favorite',[[aweme(1),aweme(2)]]);self.client.post(base+'/check')
        self.fake.serve_list('favorite',[[aweme(3)],[aweme(1),aweme(2)],[aweme(9)]])
        result=self.client.post(base+'/check').json()
        self.assertEqual((result['new_videos_count'],result['pages']),(1,2))
        self.assertEqual(result['queued_count'],0)


class SharedDownloadTests(SourcesCase):
    def complete(self,subscription,work):
        """Pretend the work was downloaded through this subscription."""
        manager=self.app.state.manager
        records=self.client.get(f"/api/subscriptions/{subscription['id']}/videos").json()['videos']
        row=next(r for r in records if r['video_id']==work)
        task=manager.create(row['url'],row['title'],source='douyin',author='x',subscription_id=subscription['id'])
        folder=manager.root/task['id'];folder.mkdir()
        (folder/f'clip [{work}].mp4').write_bytes(b'video')
        with self.app.state.store.connect() as db:
            db.execute("UPDATE tasks SET status='COMPLETED',file_path=? WHERE id=?",(f"{task['id']}/clip [{work}].mp4",task['id']))
            manager.assets.register(db,dict(db.execute('SELECT * FROM tasks WHERE id=?',(task['id'],)).fetchone()))
            manager.event(db,task['id'],'COMPLETED','done')
            db.execute('UPDATE subscription_videos SET download_task_id=? WHERE id=?',(task['id'],row['id']))
        return task

    def setUp(self):
        super().setUp()
        self.login()
        self.work=str(7_000_000_000_000_000_000+1)
        self.like,self.likes=self.made('like')
        self.author=self.subscription(auto_download=True);self.author_base='/api/subscriptions/'+self.author['id']
        self.fake.serve_list('favorite',[[by(aweme(1))]]);self.client.post(self.likes+'/sync')

    def test_work_downloaded_through_likes_is_recognised_by_the_author_subscription(self):
        task=self.complete(self.like,self.work)
        self.fake.serve([[aweme(1),aweme(2)]])
        result=self.client.post(self.author_base+'/check').json()
        self.assertEqual((result['new_videos_count'],result['linked_count'],result['queued_count']),(2,1,1))
        records={r['video_id']:r for r in self.client.get(self.author_base+'/videos').json()['videos']}
        self.assertEqual(records[self.work]['status'],'downloaded');self.assertEqual(records[self.work]['download_task_id'],task['id'])
        self.assertIsNotNone(records[self.work]['asset_id'])
        self.assertEqual(self.client.get('/api/tasks?subscription_id='+self.author['id']).json()['total'],1)    # only the other work

    def test_reverse_direction_and_manual_download_reuse_the_file(self):
        self.fake.serve([[aweme(1)]]);self.client.post(self.author_base+'/sync')
        author_row=self.client.get(self.author_base+'/videos').json()['videos'][0]
        self.assertEqual(author_row['status'],'not_downloaded')
        task=self.complete(self.like,self.work)
        response=self.client.post(f"{self.author_base}/videos/{author_row['id']}/download",json={})
        self.assertEqual(response.status_code,201,response.text);self.assertEqual(response.json()['id'],task['id']);self.assertTrue(response.json()['linked'])
        self.assertEqual(self.client.get(self.author_base+'/videos').json()['videos'][0]['status'],'downloaded')
        self.assertEqual(self.client.get('/api/tasks').json()['total'],1)
        again=self.client.post(f"{self.author_base}/videos/{author_row['id']}/download",json={})
        self.assertEqual(again.status_code,409)
        redo=self.client.post(f"{self.author_base}/videos/{author_row['id']}/download",json={'redownload':True})
        self.assertEqual(redo.status_code,201);self.assertNotEqual(redo.json()['id'],task['id'])

    def test_batch_download_counts_shared_works_separately(self):
        self.complete(self.like,self.work)
        self.fake.serve([[aweme(1),aweme(2)]]);self.client.post(self.author_base+'/sync')
        # sync links the shared one, so only the other is pending
        result=self.client.post(self.author_base+'/videos/download',json={}).json()
        self.assertEqual((result['queued'],result['linked']),(1,0))

    def test_queued_work_uses_the_real_author_for_likes_and_the_nickname_for_authors(self):
        records=self.client.get(self.likes+'/videos').json()['videos']
        task=self.client.post(f"{self.likes}/videos/{records[0]['id']}/download",json={}).json()
        self.assertEqual(self.app.state.manager.get(task['id'])['author'],'原作者')
        self.fake.serve([[aweme(5)]]);self.client.post(self.author_base+'/sync')
        other=self.client.get(self.author_base+'/videos').json()['videos'][0]
        task=self.client.post(f"{self.author_base}/videos/{other['id']}/download",json={}).json()
        self.assertEqual(self.app.state.manager.get(task['id'])['author'],self.author['nickname'])

    def test_shared_work_can_open_its_nfo_from_both_subscriptions(self):
        self.complete(self.like,self.work)
        self.fake.serve([[aweme(1)]]);self.client.post(self.author_base+'/sync')
        author_row=self.client.get(self.author_base+'/videos').json()['videos'][0]
        like_row=self.client.get(self.likes+'/videos').json()['videos'][0]
        task_dir=self.app.state.manager.root/like_row['download_task_id']
        (task_dir/f'clip [{self.work}].nfo').write_text('<movie/>',encoding='utf-8')
        for base,row in ((self.likes,like_row),(self.author_base,author_row)):
            self.assertEqual(self.client.get(f"{base}/videos/{row['id']}/nfo").status_code,200,base)
