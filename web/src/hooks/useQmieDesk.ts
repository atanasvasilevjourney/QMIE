import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type {
  AllocationPlan,
  Health,
  JournalFill,
  JournalStats,
  RadarSnapshot,
  SignalRow,
} from '../types'

type DeskState = {
  health: Health | null
  radar: RadarSnapshot | null
  signals: SignalRow[]
  allocation: AllocationPlan | null
  fills: JournalFill[]
  stats: JournalStats | null
  universeCount: number
  loading: boolean
  error: string | null
  lastSync: number | null
}

const empty: DeskState = {
  health: null,
  radar: null,
  signals: [],
  allocation: null,
  fills: [],
  stats: null,
  universeCount: 0,
  loading: true,
  error: null,
  lastSync: null,
}

export function useQmieDesk(pollMs = 12000) {
  const [state, setState] = useState<DeskState>(empty)

  const refresh = useCallback(async () => {
    try {
      const [health, radar, signals, allocation, fills, stats, universe] =
        await Promise.all([
          api.health(),
          api.radar(),
          api.signals(50),
          api.allocation(),
          api.journal(40),
          api.journalStats(),
          api.universe(),
        ])
      setState({
        health,
        radar,
        signals,
        allocation,
        fills,
        stats,
        universeCount: universe.count,
        loading: false,
        error: null,
        lastSync: Date.now(),
      })
    } catch (e) {
      setState((s) => ({
        ...s,
        loading: false,
        error: e instanceof Error ? e.message : String(e),
      }))
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => void refresh(), pollMs)
    return () => window.clearInterval(id)
  }, [refresh, pollMs])

  const forceRadar = useCallback(async () => {
    await api.radarOnce(false)
    await refresh()
  }, [refresh])

  return { ...state, refresh, forceRadar }
}
