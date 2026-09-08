import type {
  AgentBriefing,
  AllocationPlan,
  ChecklistCard,
  DeskGraph,
  Health,
  JournalFill,
  JournalStats,
  RadarSnapshot,
  SignalRow,
  AnalysisCard,
  TradingGuide,
  PaperSnapshot,
  ChartBook,
  ChartPrice,
  ScreenBook,
} from '../types'
import { RENDER_API, resolveApiBases } from './bases'

const BASES = resolveApiBases(import.meta.env.VITE_QMIE_API)

function clipBody(text: string): string {
  const plain = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
  if (/NOT_FOUND|The page could not be found/i.test(plain)) {
    return 'this host is the Vercel SPA, not FastAPI'
  }
  return plain.slice(0, 140)
}

function describeNetworkError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err)
  if (raw.includes('Vercel SPA') || raw.includes('NOT_FOUND')) {
    return `desk API missed FastAPI (Vercel has no scanner). Use ${RENDER_API} — cold start can take ~30s`
  }
  if (raw === 'Failed to fetch' || raw.includes('NetworkError') || raw.includes('Failed to fetch')) {
    const env = (import.meta.env.VITE_QMIE_API || '').trim()
    if (env) {
      return `desk API unreachable — VITE_QMIE_API=${env} (scanner is not Vercel; host FastAPI with Docker)`
    }
    return 'desk API unreachable — open http://127.0.0.1:5173 (Vite /qmie → :8080) or :8080 directly'
  }
  return raw
}

async function parseScannerJson<T>(res: Response, path: string): Promise<T> {
  const ct = res.headers.get('content-type') || ''
  if (!res.ok || !ct.includes('application/json')) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${path}: ${clipBody(text) || res.statusText || ct || 'non-JSON'}`)
  }
  return res.json() as Promise<T>
}

async function getJson<T>(path: string): Promise<T> {
  let last: Error | null = null
  for (const base of BASES) {
    try {
      const res = await fetch(`${base}${path}`)
      return await parseScannerJson<T>(res, path)
    } catch (e) {
      last = e instanceof Error ? e : new Error(String(e))
    }
  }
  throw new Error(describeNetworkError(last))
}

async function sendJson<T>(
  path: string,
  method: 'POST' | 'PATCH',
  body?: unknown,
): Promise<T> {
  let last: Error | null = null
  for (const base of BASES) {
    try {
      const res = await fetch(`${base}${path}`, {
        method,
        headers: body ? { 'content-type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      })
      return await parseScannerJson<T>(res, path)
    } catch (e) {
      last = e instanceof Error ? e : new Error(String(e))
    }
  }
  throw new Error(describeNetworkError(last))
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
  desk: () => getJson<DeskGraph>('/agents/desk'),
  checklist: (signalId: number) => getJson<ChecklistCard>(`/agents/checklist/${signalId}`),
  analysis: (signalId: number) => getJson<AnalysisCard>(`/agents/analysis/${signalId}`),
  guide: () => getJson<TradingGuide>('/guide'),
  paper: () => getJson<PaperSnapshot>('/paper'),
  paperSync: () =>
    sendJson<{ opened?: number; closed?: number; checked?: number; places_orders?: boolean }>(
      '/paper/sync',
      'POST',
    ),
  chartsBook: (limit = 500) => getJson<ChartBook>(`/charts/book?limit=${limit}`),
  chartsPrice: (symbol: string, timeframe = '1h', limit = 180) =>
    getJson<ChartPrice>(
      `/charts/price?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`,
    ),
  screens: (view = 'all') => getJson<ScreenBook>(`/screens?view=${encodeURIComponent(view)}`),
}
