// Minimal history router: one reactive `route`, no dependency. The backend already answers every non-API path with
// index.html, so deep links and reloads work.
//   /                     dashboard            /subscriptions/:id/:tab   one author, tab = settings (works is the default)
//   /tasks  /live  /files  /roadmap  /settings   /files?type=video&q=…&sort=big&layout=phone
import {reactive} from 'vue'

export const PAGES = ['dashboard', 'tasks', 'subscriptions', 'live', 'files', 'roadmap', 'settings']
export const SUB_TABS = ['settings']

export function parse(pathname = '/', search = '') {
  const parts = pathname.split('/').filter(Boolean).map(decodeURIComponent)
  const page = parts[0] === undefined ? 'dashboard' : PAGES.includes(parts[0]) ? parts[0] : 'dashboard'
  const route = {page, sub: '', tab: '', query: {}}
  if (page === 'subscriptions') {
    route.sub = parts[1] || ''
    route.tab = SUB_TABS.includes(parts[2]) ? parts[2] : ''
  }
  for (const [key, value] of new URLSearchParams(search)) if (value) route.query[key] = value
  return route
}

export function build(route) {
  let path = route.page === 'dashboard' ? '/' : `/${route.page}`
  if (route.page === 'subscriptions' && route.sub) {
    path += `/${encodeURIComponent(route.sub)}`
    if (SUB_TABS.includes(route.tab)) path += `/${route.tab}`
  }
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(route.query || {})) if (value) query.set(key, value)
  const text = query.toString()
  return text ? `${path}?${text}` : path
}

const here = () => typeof location === 'undefined' ? parse() : parse(location.pathname, location.search)
export const route = reactive(here())

function assign(next) {
  route.page = next.page; route.sub = next.sub; route.tab = next.tab; route.query = next.query
}

/** Move to `patch` applied on the current route. Changing page clears the rest unless the patch sets it. */
export function go(patch, {replace = false} = {}) {
  const next = {page: route.page, sub: route.sub, tab: route.tab, query: route.query, ...patch}
  if (patch.page && patch.page !== route.page) Object.assign(next, {sub: '', tab: '', query: {}}, patch)
  if (!PAGES.includes(next.page)) next.page = 'dashboard'
  if (next.page !== 'subscriptions') { next.sub = ''; next.tab = '' }
  const target = build(next)
  if (typeof history !== 'undefined' && target !== build(route)) history[replace ? 'replaceState' : 'pushState'](null, '', target)
  assign(parse(target.split('?')[0], target.split('?')[1] || ''))
}

/** Update only query parameters without adding a history entry (filters should not fill the back button). */
export function setQuery(values) {
  const query = {...route.query}
  for (const [key, value] of Object.entries(values)) value ? query[key] = String(value) : delete query[key]
  go({query}, {replace: true})
}

if (typeof window !== 'undefined') window.addEventListener('popstate', () => assign(here()))
