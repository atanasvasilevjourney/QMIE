import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useFocusList } from '../hooks/useFocusList'
import type { ChartAlertLevels, JournalFill, ScreenRow, ScreenView } from '../types'
import { formatPrice } from '../lib/formatPrice'
import { ChartsPanel } from './ChartsPanel'
import { ScreenAlertSetup } from './ScreenAlertSetup'
import { EmptyNote, ModuleCard } from './layout/ModuleCard'

const VIEWS: { id: ScreenView | 'focus'; label: string }[] = [
  { id: 'all', label: 'Combo' },
  { id: 'leaders', label: '4h A/A+' },
  { id: 'expansions', label: 'Expansions (spot)' },
  { id: 'coils', label: 'Coils' },
  { id: 'breakouts', label: 'Breakouts' },
  { id: 'book', label: 'Book' },
  { id: 'focus', label: 'Focus' },
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
  { id: 'score', label: 'Score' },
  { id: 'cluster', label: 'Cluster' },
  { id: 'atr_pct', label: 'ATR%' },
  { id: 'adx', label: 'ADX' },
  { id: 'coil_width_pct', label: 'Coil' },
  { id: 'pct_since_flip', label: '% flip' },
  { id: 'timeframe', label: 'TF' },
  { id: 'symbol', label: 'Symbol' },
]

function screenChartTf(r: { timeframe?: string | null; sources?: string[] }, view: string): string {
  if (view === 'breakouts' || view === 'coils' || view === 'expansions') return '1d'
  if (r.sources?.includes('expansions') && !r.sources?.includes('leaders')) return '1d'
  if (r.sources?.includes('breakouts') && !r.sources?.includes('leaders')) return '1d'
  return r.timeframe || '1h'
}

function num(v: number | null | undefined): number {
  return v == null || Number.isNaN(v) ? Number.NEGATIVE_INFINITY : v
}

function ScreenRowCard({
  row,
  active,
  flagged,
  modalHit,
  onSelect,
  onToggleFocus,
}: {
  row: ScreenRow
  active: boolean
  flagged: boolean
  modalHit: boolean
  onSelect: () => void
  onToggleFocus: () => void
}) {
  const side = (row.side || '').toUpperCase()
  const sideClass = side === 'BUY' ? 'screen-row-buy' : side === 'SELL' ? 'screen-row-sell' : ''
  const scorePct = row.score != null ? Math.min(100, Math.max(0, row.score)) : null

  return (
    <div
      role="option"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
      className={`screen-row ${active ? 'screen-row-active' : ''} ${modalHit ? 'screen-row-modal' : ''} ${sideClass}`}
    >
      <div className="screen-row-main">
        <div className="screen-row-head">
          <span className="screen-row-symbol">{row.symbol}</span>
          <span className={`screen-row-side screen-row-side-${side === 'BUY' ? 'buy' : side === 'SELL' ? 'sell' : 'neutral'}`}>
            {side || '—'}
          </span>
          <span className="screen-row-grade">{row.grade || '—'}</span>
          <span className="screen-row-tf">{(row.timeframe || '—').toUpperCase()}</span>
          {flagged && <span className="meta-chip meta-chip-lime">Focus</span>}
        </div>
        <div className="screen-row-levels">
          <span className="screen-row-entry">
            <span className="screen-row-level-label">Entry</span>
            <span className="tabular text-ink">{formatPrice(row.signal_price)}</span>
          </span>
          <span>
            <span className="screen-row-level-label">SL</span>
            <span className="tabular text-magenta">{formatPrice(row.stop_loss)}</span>
          </span>
          <span>
            <span className="screen-row-level-label">TP</span>
            <span className="tabular text-lime">{formatPrice(row.take_profit)}</span>
          </span>
        </div>
        <div className="screen-row-meta">
          {row.cluster && <span className={modalHit ? 'text-cyan' : ''}>{row.cluster}</span>}
          {row.atr_pct != null && <span>ATR {row.atr_pct.toFixed(2)}%</span>}
          {row.adx != null && <span>ADX {row.adx.toFixed(0)}</span>}
          {row.sources.map((s) => (
            <span key={s} className="meta-chip">
              {s}
            </span>
          ))}
        </div>
        {scorePct != null && (
          <div className="screen-row-score" aria-hidden>
            <div className="screen-row-score-bar" style={{ width: `${scorePct}%` }} />
          </div>
        )}
      </div>
      <button
        type="button"
        className="btn btn-sm shrink-0"
        onClick={(e) => {
          e.stopPropagation()
          onToggleFocus()
        }}
      >
        {flagged ? 'Unflag' : 'Flag'}
      </button>
    </div>
  )
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
  const [lastClose, setLastClose] = useState<number | null>(null)
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

  const alertLevels: ChartAlertLevels | null = selected
    ? {
        entry: selected.signal_price,
        stop_loss: selected.stop_loss,
        take_profit: selected.take_profit,
        side: selected.side,
        label: selected.symbol,
      }
    : null

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
        onChart(selected.symbol, screenChartTf(selected, view))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [visible.length, selected, focus, onChart, view])

  const clickSort = (k: SortKey) => {
    if (sort === k) setAsc((a) => !a)
    else {
      setSort(k)
      setAsc(k === 'coil_width_pct' || k === 'symbol')
    }
  }

  return (
    <div className="screens-layout">
      <div className="screens-list-col">
        <ModuleCard
          title="Combo screens"
          subtitle={`${visible.length} symbols · ${note || 'never orders'} · ↑↓ select · Shift+Space focus`}
        >
          <div className="mb-4 flex flex-wrap gap-2">
            {VIEWS.map((v) => (
              <button
                key={v.id}
                type="button"
                onClick={() => setView(v.id)}
                className={`chip ${view === v.id ? 'chip-on' : ''}`}
              >
                {v.label}
                {v.id === 'focus' ? ` ${focus.symbols.length}` : ''}
              </button>
            ))}
          </div>
          <div className="mb-4 flex flex-wrap gap-2">
            {SORTS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => clickSort(s.id)}
                className={`chip ${sort === s.id ? 'chip-alt' : ''}`}
              >
                {s.label}
                {sort === s.id ? (asc ? ' ↑' : ' ↓') : ''}
              </button>
            ))}
          </div>
          {modal && (
            <p className="mb-3 font-mono text-sm text-cyan">Modal cluster {modal} (most common in this view)</p>
          )}
          {err && <p className="mb-3 text-sm text-magenta">{err}</p>}
          <div className="screen-list" role="listbox">
            {visible.map((r, i) => (
              <ScreenRowCard
                key={r.symbol}
                row={r}
                active={i === cursor}
                flagged={focus.has(r.symbol)}
                modalHit={Boolean(modal && r.cluster === modal)}
                onSelect={() => setCursor(i)}
                onToggleFocus={() => focus.toggle(r.symbol)}
              />
            ))}
            {!visible.length && (
              <EmptyNote>{view === 'focus' ? 'Shift+Space to flag names' : 'No rows in this view'}</EmptyNote>
            )}
          </div>
        </ModuleCard>
      </div>

      <div className="screens-detail-col">
        <ScreenAlertSetup row={selected} fills={fills} lastClose={lastClose} />
        <ChartsPanel
          compact
          focusSymbol={selected?.symbol}
          focusTimeframe={selected ? screenChartTf(selected, view) : '1h'}
          fills={fills}
          alertLevels={alertLevels}
          onLastClose={setLastClose}
        />
      </div>
    </div>
  )
}
