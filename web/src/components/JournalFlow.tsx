import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { JournalFill, JournalStats, SignalRow } from '../types'
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

export function JournalFlow({
  selected,
  fills,
  stats,
  onDone,
  onViewChart,
}: {
  selected: SignalRow | null
  fills: JournalFill[]
  stats: JournalStats | null
  onDone: () => void
  onViewChart?: (symbol: string, timeframe?: string) => void
}) {
  const [fillPrice, setFillPrice] = useState('')
  const [size, setSize] = useState('0.01')
  const [exitPrice, setExitPrice] = useState('')
  const [notes, setNotes] = useState('manual desk fill')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const openFills = useMemo(
    () => fills.filter((f) => !f.exit_price || f.outcome === 'OPEN'),
    [fills],
  )

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
      onDone()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
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
    <div className="grid gap-4 lg:grid-cols-2">
      <PanelShell
        title="Journal Workflow"
        subtitle={
          selected
            ? `Selected signal #${selected.id} ${selected.symbol} ${selected.side}/${selected.grade}`
            : 'Select a signal on OPS (Daily expansion, TEMA BUY, or color-flip DETAILS) to start'
        }
      >
        <ol className="mb-4 space-y-2 text-sm leading-relaxed text-muted">
          <li>1. Pick an alert from OPS strategy tables</li>
          <li>2. Enter your real fill price. Size is coin qty for cash math — not an order</li>
          <li>3. Optional exit → realized R (needs stop_loss on the signal)</li>
          <li>4. Pooled win% is not frozen OOS. Need 30 manual 4h A/A+ fills</li>
        </ol>
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
                <span>
                  {f.fill_price} → {f.exit_price ?? 'open'} · sz {f.size}
                  {f.pnl != null ? ` · PnL ${f.pnl}` : ''}
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
