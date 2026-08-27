import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { JournalFill, JournalStats, SignalRow } from '../types'
import { Empty, PanelShell } from './RadarPanel'

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
            : 'Select a signal on OPS (TEMA or Daily breakout DETAILS) to start'
        }
      >
        <ol className="mb-4 space-y-2 font-mono text-[11px] text-chrome/70">
          <li>1. Pick an alert from OPS strategy tables</li>
          <li>2. Enter your real fill price & size</li>
          <li>3. Optional exit → realized R (needs stop_loss on signal)</li>
          <li>4. Sync — compare vs OOS baseline later</li>
        </ol>
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="Fill price" value={fillPrice} onChange={setFillPrice} placeholder={String(selected?.signal_price ?? '')} />
          <Field label="Size" value={size} onChange={setSize} />
          <Field label="Exit price" value={exitPrice} onChange={setExitPrice} placeholder="optional" />
          <Field label="Notes" value={notes} onChange={setNotes} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!selected || busy}
            onClick={() => void createFill()}
            className="rounded-2xl border border-lime/40 bg-lime/10 px-5 py-3 font-display text-xs tracking-widest text-lime disabled:opacity-40"
          >
            LOG FILL
          </button>
        </div>
        {msg && <p className="mt-3 font-mono text-[11px] text-cyan/80">{msg}</p>}
      </PanelShell>

      <PanelShell
        title="Fills & Stats"
        subtitle={
          stats
            ? `A/A+ win ${stats.win_pct}% · closed ${stats.closed} · avg R ${stats.avg_realized_r ?? '—'}`
            : '—'
        }
      >
        <div className="mb-3 grid grid-cols-3 gap-2">
          <Mini label="FILLS" value={stats?.fills ?? fills.length} />
          <Mini label="WINS" value={stats?.wins ?? 0} />
          <Mini label="LOSSES" value={stats?.losses ?? 0} />
        </div>
        <div className="max-h-64 space-y-2 overflow-auto">
          {fills.map((f) => (
            <div key={f.id} className="card rounded-2xl px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] text-ink">
                  #{f.id} {f.symbol || `sig ${f.signal_id}`} {f.side || ''} {f.grade || ''}{' '}
                  {f.source === 'paper' ? 'PAPER' : ''}
                </span>
                <span className="font-mono text-[10px] text-chrome/60">{f.outcome}</span>
              </div>
              <div className="mt-1 flex items-center justify-between font-mono text-[10px] text-chrome/55">
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
                      className="text-cyan hover:underline"
                    >
                      CHART
                    </button>
                  )}
                  {!f.exit_price && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void closeFill(f.id)}
                      className="text-magenta hover:underline"
                    >
                      CLOSE
                    </button>
                  )}
                </span>
              </div>
            </div>
          ))}
          {!fills.length && <Empty>No journal fills yet</Empty>}
        </div>
        {!!openFills.length && (
          <p className="mt-2 font-mono text-[10px] text-amber">{openFills.length} open fill(s)</p>
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
      <span className="font-display text-[9px] tracking-widest text-chrome/50 uppercase">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
            className="mt-1 w-full rounded-xl border border-line/15 bg-surface px-4 py-3 font-mono text-sm text-ink outline-none focus:border-cyan/50"
      />
    </label>
  )
}

function Mini({ label, value }: { label: string; value: number }) {
  return (
    <div className="card rounded-xl px-2 py-2">
      <div className="font-display text-[9px] tracking-widest text-chrome/50">{label}</div>
      <div className="font-mono text-lg text-cyan">{value}</div>
    </div>
  )
}
