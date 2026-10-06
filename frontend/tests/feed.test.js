import test from 'node:test'
import assert from 'node:assert/strict'
import {clampIndex, mountedIndexes, nextIndex, keyAction, cycleSpeed, clock} from '../src/player/feed.js'

const items = kinds => kinds.map((kind, i) => ({id: String(i), kind}))

test('clamps indexes into the list', () => {
  assert.equal(clampIndex(-3, 5), 0)
  assert.equal(clampIndex(9, 5), 4)
  assert.equal(clampIndex(2.7, 5), 2)
  assert.equal(clampIndex(NaN, 5), 0)
  assert.equal(clampIndex(3, 0), 0)
})

test('mounts the active slide and its neighbours, pictures only when active', () => {
  const list = items(['video', 'video', 'image', 'video', 'audio'])
  assert.deepEqual([...mountedIndexes(list, 1)].sort(), [0, 1])
  assert.deepEqual([...mountedIndexes(list, 2)].sort(), [1, 2, 3])
  assert.deepEqual([...mountedIndexes(list, 4)].sort(), [3, 4])
  assert.deepEqual([...mountedIndexes(list, 0)].sort(), [0, 1])
})

test('next index follows the play mode', () => {
  assert.equal(nextIndex(0, 3, 'order'), 1)
  assert.equal(nextIndex(2, 3, 'order'), null)
  assert.equal(nextIndex(1, 3, 'single'), 1)
  assert.equal(nextIndex(0, 1, 'random'), null)
  assert.equal(nextIndex(1, 4, 'random', () => 0), 0)
  assert.equal(nextIndex(1, 4, 'random', () => 0.99), 3)
  for (let i = 0; i < 50; i++) assert.notEqual(nextIndex(2, 5, 'random'), 2)
  assert.equal(nextIndex(0, 0), null)
})

test('keys map to actions; arrows and space are left to the picture viewer', () => {
  assert.deepEqual(keyAction('ArrowDown', 'video'), {type: 'move', by: 1})
  assert.deepEqual(keyAction('PageUp', 'image'), {type: 'move', by: -1})
  assert.deepEqual(keyAction('ArrowRight', 'video'), {type: 'seek', by: 5})
  assert.equal(keyAction('ArrowRight', 'image'), null)
  assert.equal(keyAction(' ', 'image'), null)
  assert.deepEqual(keyAction(' ', 'video'), {type: 'toggle'})
  assert.deepEqual(keyAction('Escape', 'image'), {type: 'close'})
  assert.equal(keyAction('x', 'video'), null)
})

test('speed cycles and clock formats', () => {
  assert.equal(cycleSpeed(1), 1.5)
  assert.equal(cycleSpeed(0.75), 1)
  assert.equal(cycleSpeed(7), 1)
  assert.equal(clock(65.9), '1:05')
  assert.equal(clock(NaN), '0:00')
})
