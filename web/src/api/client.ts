import type {
  AgentBriefing,
  AllocationPlan,
  ChecklistCard,
  Health,
  JournalFill,
  JournalStats,
  RadarSnapshot,
  SignalRow,
} from '../types'

const BASE = '/qmie'

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${path}: ${text || res.statusText}`)
  }
  return res.json() as Promise<T>
}

async function sendJson<T>(
  path: string,
  method: 'POST' | 'PATCH',
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${path}: ${text || res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => getJson<Health>('/health'),
  radar: () => getJson<RadarSnapshot>('/radar'),
  radarOnce: (notify = false) =>
    sendJson<{ ok: boolean; queued?: boolean; already_running?: boolean }>(
      `/radar/once?notify=${notify}`,
      'POST',
    ),
  signals: (limit = 40) => getJson<SignalRow[]>(`/signals?limit=${limit}`),
  allocation: () => getJson<AllocationPlan>('/allocation'),
  universe: () => getJson<{ count: number; symbols: string[]; timeframes: string[] }>('/universe'),
  journal: (limit = 30) => getJson<JournalFill[]>(`/journal?limit=${limit}`),
  journalStats: () => getJson<JournalStats>('/journal/stats?grades=A%2B,A'),
  createFill: (payload: {
    signal_id: number
    fill_price: number
    size: number
    exit_price?: number
    notes?: string
  }) => sendJson<JournalFill>('/journal', 'POST', payload),
  closeFill: (id: number, exit_price: number, notes?: string) =>
    sendJson<JournalFill>(`/journal/${id}`, 'PATCH', { exit_price, notes }),
  briefing: () => getJson<AgentBriefing>('/agents/briefing'),
  checklist: (signalId: number) => getJson<ChecklistCard>(`/agents/checklist/${signalId}`),
}
