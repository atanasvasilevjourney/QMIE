import { useEffect, useState } from 'react'
import type { DeskTheme } from '../types'

const KEY = 'qmie-desk-theme'

export function readStoredTheme(): DeskTheme {
  if (typeof window === 'undefined') return 'dark'
  return window.localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'
}

export function applyTheme(theme: DeskTheme) {
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
  let meta = document.querySelector('meta[name="theme-color"]')
  if (!meta) {
    meta = document.createElement('meta')
    meta.setAttribute('name', 'theme-color')
    document.head.appendChild(meta)
  }
  meta.setAttribute('content', theme === 'light' ? '#eef1f5' : '#0c1017')
}

export function useTheme() {
  const [theme, setTheme] = useState<DeskTheme>(() => readStoredTheme())

  useEffect(() => {
    applyTheme(theme)
    window.localStorage.setItem(KEY, theme)
  }, [theme])

  return {
    theme,
    setTheme,
    toggle: () => setTheme((t) => (t === 'light' ? 'dark' : 'light')),
  }
}
