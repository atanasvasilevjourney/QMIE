import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useFocusList } from '../hooks/useFocusList'
import type { JournalFill, ScreenRow, ScreenView } from '../types'
import { ChartsPanel } from './ChartsPanel'
import { Empty, PanelShell } from './RadarPanel'

const VIEWS: { id: ScreenView | 'focus'; label: string }[] = [
  { id: 'all', label: 'COMBO' },
  { id: 'leaders', label: '4H A/A+' },
  { id: 'coils', label: 'COILS' },
  { id: 'breakouts', label: 'BREAKOUTS' },
  { id: 'book', label: 'BOOK' },
  { id: 'focus', label: 'FOCUS' },
]

type SortKey =
  | 'score'
  | 'cluster'
  | 'atr_pct'
  | 'adx'
  | 'coil_width_pct'
  | 'pct_since_flip'
  | 'timeframe'
  | 'symbol'

const SORTS: { id: SortKey; label: string }[] = [
  { id: 'score', label: 'SCORE' },
  { id: 'cluster', label: 'CLUSTER' },
  { id: 'atr_pct', label: 'ATR%' },
  { id: 'adx', label: 'ADX' },
  { id: 'coil_width_pct', label: 'COIL' },
  { id: 'pct_since_flip', label: '%FLIP' },
  { id: 'timeframe', label: 'TF' },
  { id: 'symbol', label: 'SYM' },
]

function num(v: number | null | undefined): number {
  return v == null || Number.isNaN(v) ? Number.NEGATIVE_INFINITY : v
}

export function ScreensPanel({
  lastSync,
  fills,
  onChart,
}: {
  lastSync?: number | null
  fills: JournalFill[]
  onChart: (symbol: string, timeframe?: string) => void
}) {
  const [view, setView] = useState<ScreenView | 'focus'>('all')
  const [sort, setSort] = useState<SortKey>('score')
  const [asc, setAsc] = useState(false)
  const [cursor, setCursor] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const [rows, setRows] = useState<ScreenRow[]>([])
  const [modal, setModal] = useState<string | null>(null)
  const [note, setNote] = useState<string>('')
  const focus = useFocusList()

  const apiView: ScreenView = view === 'focus' ? 'all' : view

  useEffect(() => {
    let cancelled = false
    api
      .screens(apiView)
      .then((pack) => {
        if (cancelled) return
        setRows(pack.rows || [])
        setModal(pack.modal_cluster ?? null)
        setNote(pack.note || '')
        setErr(null)
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [apiView, lastSync])

  const visible = useMemo(() => {
    const base = view === 'focus' ? rows.filter((r) => focus.has(r.symbol)) : rows
    const copy = [...base]
    copy.sort((a, b) => {
      let cmp = 0
      if (sort === 'symbol' || sort === 'cluster' || sort === 'timeframe') {
        cmp = String(a[sort] || '').localeCompare(String(b[sort] || ''))
      } else if (sort === 'coil_width_pct') {
        const av = a.coil_width_pct
        const bv = b.coil_width_pct
        cmp = (av ?? 999) - (bv ?? 999)
      } else {
        cmp = num(a[sort] as number) - num(b[sort] as number)
      }
      return asc ? cmp : -cmp
    })
    return copy
  }, [rows, view, focus, sort, asc])

  useEffect(() => {
    setCursor((c) => (visible.length ? Math.min(c, visible.length - 1) : 0))
  }, [visible.length])

  const selected = visible[cursor] || null

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON') return
      if (e.key === 'ArrowDown' || e.key === ' ') {
        if (e.key === ' ' && e.shiftKey) {
          e.preventDefault()
          if (selected) focus.toggle(selected.symbol)
          return
        }
        e.preventDefault()
        setCursor((c) => Math.min(c + 1, Math.max(0, visible.length - 1)))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setCursor((c) => Math.max(0, c - 1))
      } else if (e.key === 'Enter' && selected) {
        e.preventDefault()
        onChart(selected.symbol, selected.timeframe || undefined)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [visible.length, selected, focus, onChart])

  const clickSort = (k: SortKey) => {
    if (sort === k) setAsc((a) => !a)
    else {
      setSort(k)
      setAsc(k === 'coil_width_pct' || k === 'symbol')
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <PanelShell
        title="Combo screens"
        subtitle={`${visible.length} unique · ${note || 'never orders'} · Space next · Shift+Space flag · Enter chart`}
      >
        <div className="mb-3 flex flex-wrap gap-2">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setView(v.id)}
              className={`rounded-2xl px-4 py-2 font-display text-xs tracking-tight ${
                view === v.id
                  ? 'border border-cyan/50 bg-cyan/10 text-cyan'
                  : 'border border-line/15 text-muted hover:border-cyan/30'
              }`}
            >
              {v.label}
              {v.id === 'focus' ? ` ${focus.symbols.length}` : ''}
            </button>
          ))}
        </div>
        <div className="mb-3 flex flex-wrap gap-2">
          {SORTS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => clickSort(s.id)}
              className={`rounded-xl px-3 py-1.5 font-mono text-xs tracking-tight ${
                sort === s.id
                  ? 'border border-magenta/40 bg-magenta/10 text-magenta'
                  : 'border border-line/15 text-muted'
              }`}
            >
              {s.label}
              {sort === s.id ? (asc ? ' ↑' : ' ↓') : ''}
            </button>
          ))}
        </div>
        {modal && (
          <p className="mb-3 font-mono text-xs text-cyan">
            Modal cluster {modal} (most common in this view)
          </p>
        )}
        {err && <p className="mb-3 font-mono text-xs text-magenta">{err}</p>}
        <div className="max-h-[min(62vh,720px)] space-y-2 overflow-auto" role="listbox">
          {visible.map((r, i) => {
            const active = i === cursor
            const flagged = focus.has(r.symbol)
            const modalHit = Boolean(modal && r.cluster === modal)
            return (
              <div
                key={r.symbol}
                role="option"
                aria-selected={active}
                tabIndex={active ? 0 : -1}
                onClick={() => setCursor(i)}
                onDoubleClick={() => onChart(r.symbol, r.timeframe || undefined)}
                className={`flex w-full items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-left ${
                  active
                    ? 'border-cyan/50 bg-cyan/10'
                    : modalHit
                      ? 'border-cyan/25 bg-cyan/5'
                      : 'border-line/15 bg-surface/60'
                }`}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-display text-sm tracking-tight text-ink">{r.symbol}</span>
                    <span className="font-mono text-xs text-muted">
                      {(r.side || '—')} · {r.grade || 'coil'} · {(r.timeframe || '—').toUpperCase()}
                    </span>
                    {flagged && <span className="font-mono text-xs tracking-normal text-lime">FOCUS</span>}
                    {r.sources.map((s) => (
                      <span key={s} className="font-mono text-xs uppercase text-magenta/80">
                        {s}
                      </span>
                    ))}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-muted">
                    <span className={modalHit ? 'text-cyan' : ''}>{r.cluster || '—'}</span>
                    {r.score != null && <span>score {r.score}</span>}
                    {r.atr_pct != null && <span>ATR {r.atr_pct.toFixed(2)}%</span>}
                    {r.adx != null && <span>ADX {r.adx.toFixed(0)}</span>}
                    {r.coil_width_pct != null && <span>coil {r.coil_width_pct.toFixed(1)}%</span>}
                    {r.pct_since_flip != null && <span>flip {r.pct_since_flip.toFixed(1)}%</span>}
                    {r.radar_color && <span>{r.radar_color}</span>}
                    {r.weight_pct != null && <span>book {r.weight_pct.toFixed(1)}%</span>}
                    <span>qty {r.quantity}</span>
                  </div>
                </div>
                <button
                  type="button"
                  className="shrink-0 rounded-xl border border-line/20 px-3 py-2 font-display text-xs tracking-normal text-muted"
                  onClick={(e) => {
                    e.stopPropagation()
                    focus.toggle(r.symbol)
                  }}
                >
                  {flagged ? 'UNFLAG' : 'FLAG'}
                </button>
              </div>
            )
          })}
          {!visible.length && <Empty>{view === 'focus' ? 'Shift+Space to flag names' : 'No rows in this view'}</Empty>}
        </div>
      </PanelShell>
      <ChartsPanel
        compact
        focusSymbol={selected?.symbol}
        focusTimeframe={selected?.timeframe || '1h'}
        fills={fills}
      />
    </div>
  )
}
