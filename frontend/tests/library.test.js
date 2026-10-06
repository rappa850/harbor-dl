import test from 'node:test'
import assert from 'node:assert/strict'
import {snapShape,groupFiles,filterEntries,typeCounts,columnCount,distribute,shapeOf} from '../src/library/library.js'

const f=(id,kind,extra={})=>({id,kind,task_id:null,path:id,name:id+'.x',extension:'.mp4',size:10,title:id,
  created_at:'2026-10-06T10:00:00',is_primary:0,cover:null,ratio:null,...extra})

test('snaps to the nearest common shape on a log scale',()=>{
  assert.equal(snapShape(0.56).id,'9:16')
  assert.equal(snapShape(0.7).id,'3:4')
  assert.equal(snapShape(1.05).id,'1:1')
  assert.equal(snapShape(1.5).id,'4:3')
  assert.equal(snapShape(2.4).id,'16:9')
  assert.equal(snapShape(null).id,'16:9')
  assert.equal(snapShape(undefined,'1:1').id,'1:1')
})

test('merges pictures, motion clips and music of one post',()=>{
  const files=[
    f('a2','image',{task_id:'t1',path:'t1/p_02.webp',extension:'.webp',ratio:0.75}),
    f('a1','image',{task_id:'t1',path:'t1/p_01.webp',extension:'.webp',ratio:0.75,is_primary:1,title:'图集作品'}),
    f('m1','video',{task_id:'t1',path:'t1/p_03.mp4'}),
    f('b1','audio',{task_id:'t1',path:'t1/p_bgm.mp3'}),
    f('v1','video',{task_id:'t2',title:'普通视频'}),
    f('s1','attachment',{task_id:'t2'})
  ]
  const entries=groupFiles(files)
  assert.equal(entries.length,2)
  const post=entries[0]
  assert.equal(post.type,'gallery');assert.equal(post.primary.id,'a1');assert.equal(post.title,'图集作品')
  assert.deepEqual(post.counts,{images:2,motion:1,audio:1});assert.equal(post.size,40)
  assert.equal(post.cover,'/api/files/a1/stream');assert.equal(entries[1].type,'video')
})

test('a lone picture stays an image; a cached cover wins over the picture',()=>{
  const [one]=groupFiles([f('i1','image',{task_id:'t3',is_primary:1,cover:'/api/covers/abc',extension:'.jpg'})])
  assert.equal(one.type,'image');assert.equal(one.cover,'/api/covers/abc')
})

test('filters by type and words, sorts',()=>{
  const entries=groupFiles([f('v1','video',{title:'猫 跳舞',size:5,created_at:'2026-10-01'}),f('v2','video',{title:'狗',size:50,created_at:'2026-10-03'}),f('b','audio',{title:'猫叫',size:1,created_at:'2026-10-02'})])
  assert.deepEqual(typeCounts(entries),{'':3,video:2,audio:1})
  assert.deepEqual(filterEntries(entries,{type:'video'}).map(e=>e.key),['v2','v1'])
  assert.deepEqual(filterEntries(entries,{query:' 猫 '}).map(e=>e.key),['b','v1'])
  assert.deepEqual(filterEntries(entries,{sort:'big'}).map(e=>e.key),['v2','v1','b'])
  assert.deepEqual(filterEntries(entries,{sort:'old'}).map(e=>e.key),['v1','b','v2'])
})

test('columns follow the width and masonry balances heights',()=>{
  assert.equal(columnCount(300),1);assert.equal(columnCount(1100),4);assert.equal(columnCount(5000),5)
  const mk=(key,ratio)=>({key,ratio,type:'image'})
  const lanes=distribute([mk('a',0.5625),mk('b',1.78),mk('c',1.78),mk('d',1.78)],2)
  assert.deepEqual(lanes.map(l=>l.map(e=>e.key)),[['a'],['b','c','d']])
})

test('fixed layouts override the cover shape',()=>{
  const e={ratio:1.78,type:'video'}
  assert.equal(shapeOf(e).id,'16:9');assert.equal(shapeOf(e,'phone').id,'9:16');assert.equal(shapeOf(e,'tablet').id,'3:4')
  assert.equal(shapeOf(e,'bogus').id,'16:9')
  const lanes=distribute([e,e,e,e],2,{layout:'phone'});assert.deepEqual(lanes.map(l=>l.length),[2,2])
})
