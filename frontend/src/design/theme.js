// Theme preference: 'system' (no attribute, follows the OS), 'light' or 'dark'.
const KEY = 'harbor-theme'
const MODES = ['system', 'light', 'dark']

export function getTheme() {
  try { const v = localStorage.getItem(KEY); return MODES.includes(v) ? v : 'system' } catch { return 'system' }
}

export function applyTheme(mode) {
  const root = document.documentElement
  if (mode === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', mode)
  try { localStorage.setItem(KEY, mode) } catch { /* private mode */ }
}

export function nextTheme(mode) { return MODES[(MODES.indexOf(mode) + 1) % MODES.length] }
export const themeLabel = { system: '跟随系统', light: '浅色', dark: '深色' }
