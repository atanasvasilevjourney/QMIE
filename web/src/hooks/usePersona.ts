import { useCallback, useEffect, useState } from 'react'

export type DeskPersona = 'observer' | 'spaceman'

const STORAGE_KEY = 'qmie-desk-persona'

export function usePersona() {
  const [persona, setPersonaState] = useState<DeskPersona | null>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw === 'observer' || raw === 'spaceman') return raw
    } catch {
      /* ignore */
    }
    return null
  })

  useEffect(() => {
    try {
      if (persona) localStorage.setItem(STORAGE_KEY, persona)
      else localStorage.removeItem(STORAGE_KEY)
    } catch {
      /* ignore */
    }
  }, [persona])

  const setPersona = useCallback((next: DeskPersona | null) => {
    setPersonaState(next)
  }, [])

  return { persona, setPersona }
}

export function personaLabel(p: DeskPersona): string {
  return p === 'observer' ? 'Space Observer' : 'Spaceman'
}
