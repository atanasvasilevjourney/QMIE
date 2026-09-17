import { useEffect, useMemo, useState } from 'react'
import type { ChartAlertLevels, JournalFill, RadarRow, RadarSnapshot } from '../types'
import { formatPrice } from '../lib/formatPrice'
import { ChartsPanel } from './ChartsPanel'
import { EmptyNote, ModuleCard, StatTile } from './layout/ModuleCard'

type ScanId =
  | 'all'
  | 'regime_shift'
  | 'fresh'
  | 'fresh_green'
  | 'fresh_red'
  | 'expansion'
  | 'coils'
  | 'early'
  | 'late'

type SortKey = 'days_in_state' | 'pct_since_flip' | 'adx' | 'symbol' | 'price'

const SCANS: { id: ScanId; label: string; hint: string }[] = [
  { id: 'regime_shift', label: 'Regime shift', hint: 'Day 1 in color' },
  { id: 'fresh', label: 'Fresh flips', hint: '≤3d in trend' },
  { id: 'fresh_green', label: 'Fresh GREEN', hint: 'New uptrend' },
  { id: 'fresh_red', label: 'Fresh RED', hint: 'New downtrend' },
  { id: 'expansion', label: 'Expansions', hint: 'Coil break' },
  { id: 'coils', label: 'Tight coils', hint: 'GREY squeeze' },
  { id: 'early', label: 'Early press', hint: 'Watch only' },
  { id: 'late', label: 'Extended', hint: 'Chase risk' },
  { id: 'all', label: 'Full universe', hint: 'All classified' },
]

function tvSpotUrl(symbol: string): string {
  const sym = symbol.toUpperCase().replace('.P', '')
  return `https://www.tradingview.com/chart/?symbol=BINANCE:${sym}&interval=D`
}

function rowTags(r: RadarRow): string[] {
  const t: string[] = []
  if (r.days_in_state === 1 && !r.state_censored) t.push('SHIFT')
  if (r.is_fresh_flip) t.push('FRESH')
  if (r.breakout === 'UP') t.push('COIL↑')
  if (r.breakout === 'DOWN') t.push('COIL↓')
  if (r.is_tight_coil) t.push('COIL')
  if (r.is_early_long) t.push('EARLY-L')
  if (r.is_early_short) t.push('EARLY-S')
  if (r.is_late_stage) t.push('LATE')
  return t
}

function matchesScan(r: RadarRow, scan: ScanId): boolean {
  switch (scan) {
    case 'all':
      return true
    case 'regime_shift':
      return r.days_in_state === 1 && !r.state_censored
    case 'fresh':
      return r.is_fresh_flip
    case 'fresh_green':
      return r.color === 'GREEN' && r.is_fresh_flip
    case 'fresh_red':
      return r.color === 'RED' && r.is_fresh_flip
    case 'expansion':
      return r.breakout === 'UP' || r.breakout === 'DOWN'
    case 'coils':
      return r.is_tight_coil
    case 'early':
      return !!(r.is_early_long || r.is_early_short)
    case 'late':
      return r.is_late_stage
    default:
      return true
  }
}

function fmtPct(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
}

function fmtFlip(iso?: string | null): string {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 10)
}

function colorClass(c: RadarRow['color']): string {
  if (c === 'GREEN') return 'trend-cell-green'
  if (c === 'RED') return 'trend-cell-red'
  return 'trend-cell-grey'
}

function alertLevelsForRow(r: RadarRow | null): ChartAlertLevels | null {
  if (!r) return null
  const side = r.breakout === 'DOWN' || r.color === 'RED' ? 'SELL' : r.breakout === 'UP' ? 'BUY' : null
  let sl: number | null = null
  if (r.breakout === 'UP' && r.coil_low != null) sl = r.coil_low
  if (r.breakout === 'DOWN' && r.coil_high != null) sl = r.coil_high
  return {
    entry: r.price,
    stop_loss: sl,
    take_profit: null,
    side,
    label: rowTags(r).join(' · ') || r.color,
  }
}

export function TrendRadarDesk({
  radar,
  fills,
}: {
  radar: RadarSnapshot | null
  fills: JournalFill[]
}) {
  const [scan, setScan] = useState<ScanId>('regime_shift')
  const [sortKey, setSortKey] = useState<SortKey>('days_in_state')
  const [sortAsc, setSortAsc] = useState(true)
  const [selected, setSelected] = useState<RadarRow | null>(null)
  const [colorFilter, setColorFilter] = useState<'ALL' | 'GREEN' | 'GREY' | 'RED'>('ALL')

  const filtered = useMemo(() => {
    const rows = radar?.rows ?? []
    let list = rows.filter((r) => matchesScan(r, scan))
    if (colorFilter !== 'ALL') list = list.filter((r) => r.color === colorFilter)
    const dir = sortAsc ? 1 : -1
    list = [...list].sort((a, b) => {
      if (sortKey === 'symbol') return dir * a.symbol.localeCompare(b.symbol)
      if (sortKey === 'days_in_state') return dir * (a.days_in_state - b.days_in_state)
      if (sortKey === 'adx') return dir * (a.adx - b.adx)
      if (sortKey === 'price') return dir * (a.price - b.price)
      const pa = a.pct_since_flip ?? -999
      const pb = b.pct_since_flip ?? -999
      return dir * (pa - pb)
    })
    return list
  }, [radar, scan, colorFilter, sortKey, sortAsc])

  useEffect(() => {
    if (!filtered.length) {
      setSelected(null)
      return
    }
    if (!selected || !filtered.some((r) => r.symbol === selected.symbol)) {
      setSelected(filtered[0])
    }
  }, [filtered, selected])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!filtered.length) return
      const idx = selected ? filtered.findIndex((r) => r.symbol === selected.symbol) : 0
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelected(filtered[Math.min(filtered.length - 1, idx + 1)])
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelected(filtered[Math.max(0, idx - 1)])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [filtered, selected])

  if (!radar) {
    return (
      <ModuleCard title="Daily Trend" subtitle="Loading radar…">
        <EmptyNote>Connecting to /radar</EmptyNote>
      </ModuleCard>
    )
  }

  const asOf = radar.as_of ? radar.as_of.slice(0, 10) : '—'
  const scanMeta = SCANS.find((s) => s.id === scan)

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((v) => !v)
    else {
      setSortKey(key)
      setSortAsc(key === 'days_in_state' || key === 'symbol')
    }
  }

  return (
    <div className="trend-desk">
      <header className="trend-desk-header">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-ink">Daily Trend · SPOT 1D</h2>
          <p className="mt-1 text-sm text-muted">
            Closed {asOf} · 🟢{radar.green} ⚪{radar.grey} 🔴{radar.red} · bias {radar.bias ?? '—'} · not
            TEMA A/A+
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile label="Green" value={radar.green} tone="lime" />
          <StatTile label="Grey" value={radar.grey} />
          <StatTile label="Red" value={radar.red} tone="magenta" />
          <StatTile label="Results" value={filtered.length} tone="cyan" />
        </div>
      </header>

      <div className="trend-desk-body">
        <aside className="trend-desk-scans" aria-label="Trend scans">
          <p className="trend-desk-scans-kicker">Scans</p>
          {SCANS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`trend-scan-btn ${scan === s.id ? 'trend-scan-btn-on' : ''}`}
              onClick={() => setScan(s.id)}
            >
              <span className="trend-scan-label">{s.label}</span>
              <span className="trend-scan-hint">{s.hint}</span>
            </button>
          ))}
        </aside>

        <section className="trend-desk-table-wrap">
          <div className="trend-desk-toolbar">
            <span className="meta-chip">{scanMeta?.label ?? scan}</span>
            <span className="meta-chip">{filtered.length} rows</span>
            <div className="flex flex-wrap gap-1">
              {(['ALL', 'GREEN', 'GREY', 'RED'] as const).map((c) => (
                <button
                  key={c}
                  type="button"
                  className={`chip chip-sm ${colorFilter === c ? 'chip-on' : ''}`}
                  onClick={() => setColorFilter(c)}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
          <div className="trend-table-scroll">
            <table className="trend-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Ticker</th>
                  <th>Regime</th>
                  <th>
                    <button type="button" className="trend-th-btn" onClick={() => toggleSort('days_in_state')}>
                      Days {sortKey === 'days_in_state' ? (sortAsc ? '↑' : '↓') : ''}
                    </button>
                  </th>
                  <th>Flipped</th>
                  <th>
                    <button type="button" className="trend-th-btn" onClick={() => toggleSort('pct_since_flip')}>
                      % move {sortKey === 'pct_since_flip' ? (sortAsc ? '↑' : '↓') : ''}
                    </button>
                  </th>
                  <th>
                    <button type="button" className="trend-th-btn" onClick={() => toggleSort('price')}>
                      Price {sortKey === 'price' ? (sortAsc ? '↑' : '↓') : ''}
                    </button>
                  </th>
                  <th>
                    <button type="button" className="trend-th-btn" onClick={() => toggleSort('adx')}>
                      ADX {sortKey === 'adx' ? (sortAsc ? '↑' : '↓') : ''}
                    </button>
                  </th>
                  <th>Tags</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => {
                  const on = selected?.symbol === r.symbol
                  const shift = r.days_in_state === 1 && !r.state_censored
                  const pct = r.pct_since_flip
                  const pctTone =
                    pct == null ? '' : pct >= 0 ? 'trend-pct-up' : 'trend-pct-down'
                  return (
                    <tr
                      key={r.symbol}
                      className={`trend-row ${on ? 'trend-row-on' : ''} ${shift ? 'trend-row-shift' : ''}`}
                      onClick={() => setSelected(r)}
                    >
                      <td className="tabular text-muted">{i + 1}</td>
                      <td className="font-mono font-medium tabular text-ink">{r.symbol.replace('USDT', '')}</td>
                      <td>
                        <span className={`trend-regime-pill ${colorClass(r.color)}`}>{r.color}</span>
                      </td>
                      <td className="tabular">{r.days_in_state}</td>
                      <td className="tabular text-sm text-muted">{fmtFlip(r.flipped_at)}</td>
                      <td className={`tabular font-medium ${pctTone}`}>{fmtPct(pct)}</td>
                      <td className="tabular text-sm">{formatPrice(r.price)}</td>
                      <td className="tabular text-muted">{r.adx.toFixed(1)}</td>
                      <td className="trend-tags">{rowTags(r).join(' ')}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {!filtered.length && <p className="empty-note m-4">No symbols in this scan.</p>}
          </div>
          <p className="mt-2 text-xs text-muted">↑↓ keyboard · click row for chart</p>
        </section>

        <aside className="trend-desk-detail">
          <div className="trend-desk-chart">
            <ChartsPanel
              compact
              focusSymbol={selected?.symbol}
              focusTimeframe="1d"
              fills={fills}
              alertLevels={alertLevelsForRow(selected)}
            />
          </div>
          {selected && (
            <ModuleCard
              title={selected.symbol}
              subtitle="Regime detail · spot book"
              action={
                <a
                  className="btn btn-sm btn-accent"
                  href={tvSpotUrl(selected.symbol)}
                  target="_blank"
                  rel="noreferrer"
                >
                  TradingView
                </a>
              }
            >
              <dl className="trend-detail-grid">
                <Detail k="Regime" v={selected.color} />
                <Detail k="Days in state" v={String(selected.days_in_state)} />
                <Detail k="Regime shift?" v={selected.days_in_state === 1 && !selected.state_censored ? 'Yes — day 1' : 'No'} />
                <Detail k="Flipped at" v={fmtFlip(selected.flipped_at)} />
                <Detail k="Closed bar" v={fmtFlip(selected.bar_time)} />
                <Detail k="% since flip" v={fmtPct(selected.pct_since_flip)} />
                <Detail k="ADX" v={`${selected.adx} (+DI ${selected.plus_di} / −DI ${selected.minus_di})`} />
                <Detail k="Coil width" v={selected.coil_width_pct != null ? `${selected.coil_width_pct.toFixed(1)}%` : '—'} />
                <Detail k="Breakout" v={selected.breakout ? `${selected.breakout} @ ${selected.breakout_level ?? '—'}` : '—'} />
                <Detail k="Coil box" v={
                  selected.coil_high != null && selected.coil_low != null
                    ? `${formatPrice(selected.coil_low)} – ${formatPrice(selected.coil_high)}`
                    : '—'
                } />
              </dl>
              <p className="mt-3 text-xs text-muted">
                SHIFT = first day in new color (watch / optional spot). FRESH = ≤3d. LATE = extended chase
                risk. Leverage add = wait for 4h TEMA A/A+.
              </p>
            </ModuleCard>
          )}
        </aside>
      </div>
    </div>
  )
}

function Detail({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="fact-k">{k}</dt>
      <dd className="fact-v">{v}</dd>
    </div>
  )
}
