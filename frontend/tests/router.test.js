import test from 'node:test'
import assert from 'node:assert/strict'
import {parse, build, route, go, setQuery} from '../src/router.js'

test('parses pages, subscription and tab', () => {
  assert.deepEqual(parse('/'), {page: 'dashboard', sub: '', tab: '', query: {}})
  assert.equal(parse('/files').page, 'files')
  assert.equal(parse('/nonsense').page, 'dashboard')
  assert.deepEqual(parse('/subscriptions/abc%20d/settings'), {page: 'subscriptions', sub: 'abc d', tab: 'settings', query: {}})
  assert.equal(parse('/subscriptions/x/unknown').tab, '')
  assert.equal(parse('/tasks/ignored').sub, '')
  assert.deepEqual(parse('/files', '?type=video&q=%E7%8C%AB&empty=').query, {type: 'video', q: '猫'})
})

test('builds the same path back', () => {
  for (const url of ['/', '/tasks', '/profile', '/subscriptions', '/subscriptions/a1', '/subscriptions/a1/settings', '/files?type=video&sort=big']) {
    const [path, search] = url.split('?')
    assert.equal(build(parse(path, search ? '?' + search : '')), url)
  }
})

test('go changes page and clears what belongs to the old one', () => {
  go({page: 'subscriptions', sub: 'a1', tab: 'settings'})
  assert.equal(build(route), '/subscriptions/a1/settings')
  go({page: 'files', query: {type: 'audio'}})
  assert.equal(build(route), '/files?type=audio')
  assert.equal(route.sub, '')
  setQuery({q: '猫', type: ''})
  assert.deepEqual({...route.query}, {q: '猫'})
  go({page: 'dashboard'})
  assert.equal(build(route), '/')
  assert.deepEqual({...route.query}, {})
})
