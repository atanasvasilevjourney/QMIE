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

async function settled<T>(p: Promise<T>): Promise<{ ok: true; value: T } | { ok: false; error: string }> {
  try {
    return { ok: true, value: await p }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

export function useQmieDesk(pollMs = 12000) {
  const [state, setState] = useState<DeskState>(empty)

  const refresh = useCallback(async () => {
    const [health, radar, signals, allocation, fills, stats, universe] = await Promise.all([
      settled(api.health()),
      settled(api.radar()),
      settled(api.signals(50)),
      settled(api.allocation()),
      settled(api.journal(40)),
      settled(api.journalStats()),
      settled(api.universe()),
    ])

    const failures = [health, radar, signals, allocation, fills, stats, universe]
      .filter((r) => !r.ok)
      .map((r) => (r as { ok: false; error: string }).error)

    setState((prev) => ({
      health: health.ok ? health.value : prev.health,
      radar: radar.ok ? radar.value : prev.radar,
      signals: signals.ok ? signals.value : prev.signals,
      allocation: allocation.ok ? allocation.value : prev.allocation,
      fills: fills.ok ? fills.value : prev.fills,
      stats: stats.ok ? stats.value : prev.stats,
      universeCount: universe.ok ? universe.value.count : prev.universeCount,
      loading: false,
      error: failures.length ? failures.slice(0, 2).join(' · ') : null,
      lastSync: Date.now(),
    }))
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
