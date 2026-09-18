import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type {
  JournalFill,
  JournalStats,
  SignalDevelopmentThread,
  SignalDevelopments,
  SignalRow,
} from '../types'
import { formatPrice } from '../lib/formatPrice'
import { Empty, PanelShell } from './RadarPanel'

function journalStatsLine(stats: JournalStats): string {
  const paper = stats.by_source?.paper
  const manual = stats.by_source?.manual
  const hasSplit = stats.by_source != null
  const h1 = stats.by_timeframe?.['1h'] ?? stats.by_timeframe?.['1H'] ?? 0
  const h4 = stats.by_timeframe?.['4h'] ?? stats.by_timeframe?.['4H'] ?? 0
  const m4 = stats.manual_4h_closed ?? 0
  const pooled =
    `win ${stats.win_pct}% is pooled journal — not frozen OOS · avg R ${stats.avg_realized_r ?? '—'}`
  if (!hasSplit) {
    return `A/A+ closed ${stats.closed} · ${pooled}`
  }
  return (
    `A/A+ closed ${stats.closed} · paper ${paper ?? 0} / manual ${manual ?? 0} · 1h ${h1} / 4h ${h4} · ` +
    `${pooled} · manual 4h ${m4}/30 · ` +
    (stats.oos_edge || '4h A/A+ OOS 49.1% / E[R] +0.309')
  )
}

function validityClass(status: string): string {
  const s = status.toUpperCase()
  if (s === 'VALID' || s === 'FRESH') return 'dev-valid'
  if (s === 'INVALID') return 'dev-invalid'
  if (s === 'LATE') return 'dev-late'
  if (s === 'WATCH') return 'dev-watch'
  return 'dev-unknown'
}

function fmtPct(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
}

export function JournalFlow({
  selected,
  signals,
  fills,
  stats,
  onSelectSignal,
  onDone,
  onViewChart,
}: {
  selected: SignalRow | null
  signals: SignalRow[]
  fills: JournalFill[]
  stats: JournalStats | null
  onSelectSignal?: (row: SignalRow) => void
  onDone: () => void
  onViewChart?: (symbol: string, timeframe?: string) => void
}) {
  const [fillPrice, setFillPrice] = useState('')
  const [size, setSize] = useState('0.01')
  const [exitPrice, setExitPrice] = useState('')
  const [notes, setNotes] = useState('manual desk fill')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [developments, setDevelopments] = useState<SignalDevelopments | null>(null)
  const [devErr, setDevErr] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .journalDevelopments(2)
      .then((d) => {
        if (!cancelled) setDevelopments(d)
      })
      .catch((e) => {
        if (!cancelled) setDevErr(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [fills.length, stats?.closed])

  const openFills = useMemo(
    () => fills.filter((f) => !f.exit_price || f.outcome === 'OPEN'),
    [fills],
  )

  useEffect(() => {
    if (!selected?.signal_price) {
      setFillPrice('')
      return
    }
    setFillPrice(String(selected.signal_price))
  }, [selected?.id, selected?.signal_price])

  async function createFill() {
    if (!selected) return
    setBusy(true)
    setMsg(null)
    try {
      const payload: {
        signal_id: number
        fill_price: number
        size: number
        exit_price?: number
        notes?: string
      } = {
        signal_id: selected.id,
        fill_price: Number(fillPrice || selected.signal_price || 0),
        size: Number(size),
        notes,
      }
      if (exitPrice) payload.exit_price = Number(exitPrice)
      const row = await api.createFill(payload)
      setMsg(`Fill #${row.id} logged · ${row.outcome || 'OPEN'}`)
      void api.journalDevelopments(2).then(setDevelopments).catch(() => {})
      onDone()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  function pickThread(t: SignalDevelopmentThread) {
    const fromDesk = signals.find((s) => s.id === t.latest_signal_id)
    if (fromDesk && onSelectSignal) {
      onSelectSignal(fromDesk)
      return
    }
    if (onSelectSignal) {
      onSelectSignal({
        id: t.latest_signal_id,
        symbol: t.symbol,
        side: t.side,
        strategy: t.strategy,
        signal_price: t.last_alert_price ?? undefined,
      })
    }
  }

  async function closeFill(id: number) {
    if (!exitPrice) {
      setMsg('Set exit price to close a fill')
      return
    }
    setBusy(true)
    try {
      // Omit notes on close unless the operator edited them — avoids wiping fill notes.
      const closeNotes = notes.trim() && notes !== 'manual desk fill' ? notes : undefined
      const row = await api.closeFill(id, Number(exitPrice), closeNotes)
      setMsg(`Closed #${row.id} · R=${row.realized_r ?? 'n/a'} · ${row.outcome}`)
      onDone()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-4">
      <PanelShell
        title="Repeat alerts · setup development"
        subtitle={
          developments?.radar_as_of
            ? `Same symbol/strategy fired 2+ times · daily radar as of ${developments.radar_as_of}`
            : 'Tracks price since first alert and whether daily Trend Radar still aligns'
        }
      >
        {devErr && <p className="text-sm text-magenta">{devErr}</p>}
        {!devErr && !developments && <p className="text-sm text-muted">Loading developments…</p>}
        {developments && !developments.count && (
          <p className="text-sm text-muted">
            No repeat threads yet. When Discord/qmie-journal sends the same DailyBreakout or scanner
            alert again, it appears here with % move and radar validity.
          </p>
        )}
        <div className="dev-thread-list">
          {developments?.threads.map((t) => {
            const key = `${t.symbol}|${t.strategy}|${t.side}`
            const open = expanded === key
            const on = selected?.id === t.latest_signal_id
            return (
              <div key={key} className={`dev-thread ${on ? 'dev-thread-on' : ''}`}>
                <button type="button" className="dev-thread-head" onClick={() => pickThread(t)}>
                  <span className="font-mono font-semibold text-ink">{t.symbol.replace('USDT', '')}</span>
                  <span className="text-xs text-muted">{t.strategy}</span>
                  <span className={`dev-badge ${validityClass(t.validity_status)}`}>{t.validity_status}</span>
                  <span className="tabular text-sm">
                    {t.alert_count}× · since 1st {fmtPct(t.pct_since_first)} · since last{' '}
                    {fmtPct(t.pct_since_last_alert)}
                  </span>
                </button>
                <p className="dev-detail">{t.validity_detail}</p>
                {t.radar && (
                  <p className="dev-radar text-xs text-muted">
                    Radar {t.radar.color} · {t.radar.days_in_state}d · ADX {t.radar.adx?.toFixed(1) ?? '—'}
                    {t.radar.is_late_stage ? ' · LATE' : ''}
                  </p>
                )}
                <button
                  type="button"
                  className="btn btn-sm dev-expand"
                  onClick={() => setExpanded(open ? null : key)}
                >
                  {open ? 'Hide' : 'Show'} alert timeline
                </button>
                {open && (
                  <ul className="dev-timeline">
                    {t.timeline.map((a) => (
                      <li key={a.id}>
                        #{a.id} · {a.received_at?.slice(0, 10) ?? '—'} · {formatPrice(a.signal_price)}{' '}
                        {a.grade ? `· ${a.grade}` : ''}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
        </div>
      </PanelShell>

      <div className="grid gap-4 lg:grid-cols-2">
      <PanelShell
        title="Journal Workflow"
        subtitle={
          selected
            ? `Selected signal #${selected.id} ${selected.symbol} ${selected.side}/${selected.grade}`
            : 'Select a signal on OPS (spot Daily expansion, leveraged TEMA BUY, or color-flip DETAILS) to start'
        }
      >
        <ol className="mb-4 space-y-2 text-sm leading-relaxed text-muted">
          <li>1. OPS → strategy row → <strong className="text-ink">Journal</strong> (not Details only), or Screens → Track manually</li>
          <li>2. Fill price pre-fills from scanner entry — edit if your fill differed</li>
          <li>3. Optional exit → realized R (uses signal stop_loss)</li>
          <li>4. Pooled win% is not frozen OOS. Need 30 manual 4h A/A+ fills</li>
        </ol>
        {selected && (selected.signal_price != null || selected.stop_loss != null) && (
          <div className="alert-level-grid mb-4">
            <div className="stat-tile stat-tile-cyan">
              <div className="stat-tile-label">Scanner entry</div>
              <div className="stat-tile-value">{formatPrice(selected.signal_price)}</div>
            </div>
            <div className="stat-tile stat-tile-magenta">
              <div className="stat-tile-label">Stop</div>
              <div className="stat-tile-value">{formatPrice(selected.stop_loss)}</div>
            </div>
            <div className="stat-tile stat-tile-lime">
              <div className="stat-tile-label">Target</div>
              <div className="stat-tile-value">{formatPrice(selected.take_profit)}</div>
            </div>
          </div>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="Fill price" value={fillPrice} onChange={setFillPrice} placeholder={String(selected?.signal_price ?? '')} />
          <Field label="Size (base coins, cash math only)" value={size} onChange={setSize} />
          <Field label="Exit price" value={exitPrice} onChange={setExitPrice} placeholder="optional…" />
          <Field label="Notes" value={notes} onChange={setNotes} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!selected || busy}
            onClick={() => void createFill()}
            className="btn btn-ok"
          >
            Log fill
          </button>
        </div>
        {msg && <p className="mt-3 text-sm text-cyan">{msg}</p>}
      </PanelShell>

      <PanelShell
        title="Fills & Stats"
        subtitle={
          stats
            ? journalStatsLine(stats)
            : '—'
        }
      >
        <div className="mb-3 grid grid-cols-3 gap-2">
          <Mini label="Fills" value={stats?.fills ?? fills.length} />
          <Mini label="Wins" value={stats?.wins ?? 0} />
          <Mini label="Losses" value={stats?.losses ?? 0} />
        </div>
        <div className="max-h-64 space-y-2 overflow-auto">
          {fills.map((f) => (
            <div key={f.id} className="card rounded-2xl px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-sm text-ink">
                  #{f.id} {f.symbol || `sig ${f.signal_id}`} {f.side || ''} {f.grade || ''}{' '}
                  {f.source === 'paper' ? 'Paper' : ''}
                </span>
                <span className="font-mono text-sm text-muted">{f.outcome}</span>
              </div>
              <div className="mt-1 flex items-center justify-between font-mono text-sm text-muted">
                <span className="tabular">
                  {formatPrice(f.fill_price)} → {f.exit_price != null ? formatPrice(f.exit_price) : 'open'} · sz {f.size}
                  {f.pnl != null ? ` · PnL ${f.pnl}` : ''}
                  {f.realized_r != null ? ` · ${f.realized_r.toFixed(2)}R` : ''}
                  {f.exit_reason ? ` · ${f.exit_reason}` : ''}
                </span>
                <span className="flex gap-3">
                  {onViewChart && f.symbol && (
                    <button
                      type="button"
                      onClick={() => onViewChart(f.symbol as string, f.timeframe)}
                      className="btn btn-sm btn-accent"
                    >
                      Chart
                    </button>
                  )}
                  {!f.exit_price && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void closeFill(f.id)}
                      className="btn btn-sm btn-warn"
                    >
                      Close
                    </button>
                  )}
                </span>
              </div>
            </div>
          ))}
          {!fills.length && <Empty>No journal fills yet</Empty>}
        </div>
        {!!openFills.length && (
          <p className="mt-2 text-sm text-amber">{openFills.length} open fill(s)</p>
        )}
      </PanelShell>
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <label className="block">
      <span className="field-label">{label}</span>
      <input
        name={label.toLowerCase().replace(/\s+/g, '_')}
        autoComplete="off"
        spellCheck={false}
        inputMode={label.toLowerCase().includes('price') || label === 'Size' ? 'decimal' : undefined}
        value={value}
        placeholder={placeholder || undefined}
        onChange={(e) => onChange(e.target.value)}
        className="field-input"
      />
    </label>
  )
}

function Mini({ label, value }: { label: string; value: number }) {
  return (
    <div className="card rounded-xl px-2 py-2">
      <div className="text-sm font-semibold text-muted">{label}</div>
      <div className="font-mono text-lg tabular text-cyan">{value}</div>
    </div>
  )
}
