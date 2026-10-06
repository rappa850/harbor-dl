// Pure helpers for the immersive feed (kept free of the DOM so they can be tested).

export const SPEEDS = [1, 1.5, 2, 0.75]

export function clampIndex(index, length) {
  if (!length) return 0
  return Math.min(length - 1, Math.max(0, Number.isFinite(index) ? Math.trunc(index) : 0))
}

/** Slides that get real content: the active one and its neighbours; pictures only when active (they start music and a timer). */
export function mountedIndexes(items, active, radius = 1) {
  const result = new Set()
  for (let i = active - radius; i <= active + radius; i++) {
    if (i < 0 || i >= items.length) continue
    if (items[i].kind === 'image' && i !== active) continue
    result.add(i)
  }
  return result
}

/** Index to move to when a work ends, or null to stay (end of the list). */
export function nextIndex(active, length, mode = 'order', random = Math.random) {
  if (!length) return null
  if (mode === 'single') return active
  if (mode === 'random') {
    if (length < 2) return null
    const pick = Math.floor(random() * (length - 1))
    return pick >= active ? pick + 1 : pick
  }
  return active + 1 < length ? active + 1 : null
}

/** Keyboard to action; arrows left/right belong to the picture viewer when a post is showing. */
export function keyAction(key, kind) {
  switch (key) {
    case 'ArrowDown': case 'PageDown': case 'j': return {type: 'move', by: 1}
    case 'ArrowUp': case 'PageUp': case 'k': return {type: 'move', by: -1}
    case ' ': case 'Spacebar': return kind === 'image' ? null : {type: 'toggle'}
    case 'ArrowRight': return kind === 'image' ? null : {type: 'seek', by: 5}
    case 'ArrowLeft': return kind === 'image' ? null : {type: 'seek', by: -5}
    case 'm': case 'M': return {type: 'mute'}
    case 'Escape': return {type: 'close'}
    default: return null
  }
}

export function cycleSpeed(current) {
  const at = SPEEDS.indexOf(current)
  return SPEEDS[(at + 1) % SPEEDS.length]
}

export function clock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const whole = Math.floor(seconds)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}
