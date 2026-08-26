import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type {
  AgentBriefing,
  AllocationPlan,
  DeskGraph,
  Health,
  JournalFill,
  JournalStats,
  RadarSnapshot,
  SignalRow,
  PaperSnapshot,
  TradingGuide,
} from '../types'

type DeskState = {
  health: Health | null
  radar: RadarSnapshot | null
  signals: SignalRow[]
  allocation: AllocationPlan | null
  fills: JournalFill[]
  stats: JournalStats | null
  universeCount: number
  briefing: AgentBriefing | null
  desk: DeskGraph | null
  guide: TradingGuide | null
  paper: PaperSnapshot | null
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
  briefing: null,
  desk: null,
  guide: null,
  paper: null,
  loading: true,
  error: null,
  lastSync: null,
}

async function settled<T>(p: Promise<T>): Promise<{ ok: true; value: T } | { ok: false; error: string }> {
  try {
    return { ok: true, value: await p }
  } catch (e) {
    const raw = e instanceof Error ? e.message : String(e)
    const error =
      raw === 'Failed to fetch' || raw.includes('NetworkError')
        ? 'desk API unreachable — open http://127.0.0.1:5173 (Vite /qmie → :8080)'
        : raw
    return { ok: false, error }
  }
}

export function useQmieDesk(pollMs = 12000) {
  const [state, setState] = useState<DeskState>(empty)

  const refresh = useCallback(async () => {
    const [health, radar, signals, allocation, fills, stats, universe, briefing, desk, guide, paper] = await Promise.all([
      settled(api.health()),
      settled(api.radar()),
      settled(api.signals(80)),
      settled(api.allocation()),
      settled(api.journal(80)),
      settled(api.journalStats()),
      settled(api.universe()),
      settled(api.briefing()),
      settled(api.desk()),
      settled(api.guide()),
      settled(api.paper()),
    ])

    const failures = [...new Set(
      [health, radar, signals, allocation, fills, stats, universe, briefing, desk, guide, paper]
        .filter((r) => !r.ok)
        .map((r) => (r as { ok: false; error: string }).error),
    )]

    setState((prev) => ({
      health: health.ok ? health.value : prev.health,
      radar: radar.ok ? radar.value : prev.radar,
      signals: signals.ok ? signals.value : prev.signals,
      allocation: allocation.ok ? allocation.value : prev.allocation,
      fills: fills.ok ? fills.value : prev.fills,
      stats: stats.ok ? stats.value : prev.stats,
      universeCount: universe.ok ? universe.value.count : prev.universeCount,
      briefing: briefing.ok ? briefing.value : prev.briefing,
      desk: desk.ok ? desk.value : prev.desk,
      guide: guide.ok ? guide.value : prev.guide,
      paper: paper.ok ? paper.value : prev.paper,
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

  const forcePaper = useCallback(async () => {
    const result = await api.paperSync()
    await refresh()
    return result
  }, [refresh])

  return { ...state, refresh, forceRadar, forcePaper }
}
