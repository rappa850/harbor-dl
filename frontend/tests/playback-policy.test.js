import test from 'node:test'
import assert from 'node:assert/strict'
import {resumeTime,playbackIndex} from '../src/playback-policy.js'

test('resume excludes first five seconds and final ten seconds',()=>{
  assert.equal(resumeTime(5,60),0)
  assert.equal(resumeTime(5.01,60),5.01)
  assert.equal(resumeTime(49.99,60),49.99)
  assert.equal(resumeTime(50,60),0)
  assert.equal(resumeTime(59,60),0)
  assert.equal(resumeTime(12.5,60),12.5)
})

test('unavailable metadata and invalid records cannot trigger a seek',()=>{
  for(const progress of [undefined,null,'12',NaN,Infinity,-1])assert.equal(resumeTime(progress,60),0)
  for(const duration of [undefined,null,NaN,Infinity,0,10,15])assert.equal(resumeTime(6,duration),0)
})

const items=[{work_id:'ended',duration:60},{work_id:'resume',duration:60},{work_id:'unknown',duration:null}]
const record={current_index:2,video_progress:{ended:56,resume:12,unknown:20}}
test('explicit selection precedes reset and saved list position',()=>{
  assert.equal(playbackIndex(items,record,{workId:'ended',resetMode:true}),0)
  assert.equal(playbackIndex(items,record,{workId:'absent'}),-1)
  assert.equal(playbackIndex(items,record),2)
  assert.equal(playbackIndex(items,{current_index:99}),2)
})
test('reset selects first resumable work including unknown-duration fallback',()=>{
  assert.equal(playbackIndex(items,record,{resetMode:true}),1)
  assert.equal(playbackIndex(items,{video_progress:{resume:50,unknown:20}},{resetMode:true}),2)
  assert.equal(playbackIndex(items,{video_progress:{ended:5,resume:50}},{resetMode:true}),0)
})
test('missing record starts at first item',()=>{
  assert.equal(playbackIndex(items,null),0)
  assert.equal(playbackIndex(items,null,{resetMode:true}),0)
})
