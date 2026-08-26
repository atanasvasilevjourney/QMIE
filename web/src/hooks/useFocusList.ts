import { useCallback, useEffect, useState } from 'react'

const KEY = 'qmie-desk-focus'

function readFocus(): string[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return [...new Set(parsed.map((s) => String(s).toUpperCase()).filter(Boolean))]
  } catch {
    return []
  }
}

export function useFocusList() {
  const [symbols, setSymbols] = useState<string[]>(() => readFocus())

  useEffect(() => {
    window.localStorage.setItem(KEY, JSON.stringify(symbols))
  }, [symbols])

  const has = useCallback((sym: string) => symbols.includes(sym.toUpperCase()), [symbols])

  const toggle = useCallback((sym: string) => {
    const s = sym.toUpperCase()
    setSymbols((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]))
  }, [])

  return { symbols, has, toggle }
}
