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
