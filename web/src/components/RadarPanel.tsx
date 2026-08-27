import { useState, type ReactNode } from 'react'
import type { RadarRow, RadarSnapshot } from '../types'

export function RadarPanel({ radar }: { radar: RadarSnapshot | null }) {
  if (!radar) {
    return <PanelShell title="Trend Radar" subtitle="Loading…"><Empty>Connecting to /radar</Empty></PanelShell>
  }
  const scanned = radar.succeeded ?? radar.count
  const requested = radar.requested || radar.count
  const coverage = radar.coverage_pct != null
    ? radar.coverage_pct
    : requested
      ? Math.round((1000 * scanned) / requested) / 10
      : null
  const asOf = radar.as_of ? radar.as_of.slice(0, 10) : '—'
  const incomplete = radar.status === 'incomplete'
  const btc = radar.btc_color ?? radar.rows?.find((r) => r.symbol === 'BTCUSDT')?.color
  const bias = radar.bias ?? 'UNKNOWN'
  return (
    <PanelShell
      title="Trend Radar — unranked 1D context"
      subtitle={`${radar.status ?? 'Ready'} · closed through ${asOf} · ${scanned} of ${requested}${coverage != null ? ` (${coverage}%)` : ''} · enter 25 / exit 20 · not a QMIE grade`}
    >
      {incomplete && (
        <p className="empty-note mb-3">
          Incomplete map — {radar.failed ?? 0} symbol{(radar.failed ?? 0) === 1 ? '' : 's'} failed.
          Breadth and Orbit tint are not a full-universe read.
        </p>
      )}
      <div className="mb-3 flex flex-wrap gap-2 font-mono text-sm tabular">
        <span className="rounded-md border border-line px-2 py-1 text-ink">bias {bias}</span>
        <span className="rounded-md border border-line px-2 py-1 text-muted">G &gt; 1.2× R · grey ignored</span>
        <span className="rounded-md border border-line px-2 py-1 text-ink">BTC {btc ?? '—'}</span>
      </div>
      <div className="mb-4 grid grid-cols-3 gap-3">
        <Stat label="Green" value={radar.green} tone="lime" />
        <Stat label="Grey" value={radar.grey} tone="chrome" />
        <Stat label="Red" value={radar.red} tone="magenta" />
      </div>
      <RadarBreadth green={radar.green} grey={radar.grey} red={radar.red} />
      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <Bucket title="Fresh GREEN" rows={radar.fresh_green} render={(r) => `d${r.days_in_state} ${fmtPct(r.pct_since_flip)} ADX${r.adx}`} />
        <Bucket title="Fresh RED" rows={radar.fresh_red} render={(r) => `d${r.days_in_state} ${fmtPct(r.pct_since_flip)} ADX${r.adx}`} />
        <Bucket title="Donchian coil break (watch)" rows={radar.breakouts} render={(r) => `${r.breakout} ADX${r.adx}`} />
        <Bucket title="Tight coils" rows={radar.tight_coils} render={(r) => `${r.coil_width_pct?.toFixed?.(1) ?? '—'}%`} />
        <Bucket title="Late GREEN" rows={radar.late_stage_green} render={(r) => `d${r.days_in_state} ADX${r.adx}`} />
        <Bucket title="Late RED" rows={radar.late_stage_red ?? []} render={(r) => `d${r.days_in_state} ADX${r.adx}`} />
      </div>
      <p className="lede mt-4">
        Radar coil-break is a watchlist. OPS Daily breakout dispatches day-1 GREY→GREEN/RED
        {' '}or coil-UP/DOWN as separate unranked setups — not an A/A+ grade.
        Confirm on the 1D visualizer before clicking. Manual only.
      </p>
    </PanelShell>
  )
}

function Bucket({
  title,
  rows,
  render,
}: {
  title: string
  rows: RadarRow[]
  render: (r: RadarRow) => string
}) {
  const count = rows?.length ?? 0
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="text-[0.9375rem] font-semibold text-ink">{title}</h3>
        <span className="font-mono text-sm tabular text-muted">{count}</span>
      </div>
      {count === 0 ? (
        <p className="empty-note">None yet</p>
      ) : (
        <div className="max-h-72 space-y-2 overflow-auto pr-1">
          {rows.slice(0, 12).map((r, i) => (
            <RadarRowCard
              key={`${title}-${i}-${String(r.symbol)}`}
              row={r}
              summary={render(r)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function RadarRowCard({ row, summary }: { row: RadarRow; summary: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card rounded-xl">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        aria-expanded={open}
      >
        <span className="min-w-0 flex-1">
          <span className="block font-mono text-[0.9375rem] font-medium tabular text-ink">{row.symbol}</span>
          <span className="mt-0.5 block font-mono text-sm tabular text-muted">{summary.replace(String(row.symbol), '').trim()}</span>
        </span>
        <span className="btn btn-sm btn-accent shrink-0">{open ? 'Hide' : 'Details'}</span>
      </button>
      {open && (
        <dl className="grid gap-3 border-t border-line px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
          <Fact k="Symbol" v={row.symbol} />
          <Fact k="Color" v={row.color} />
          <Fact k="Days in state" v={String(row.days_in_state)} />
          <Fact k="Price" v={String(row.price)} />
          <Fact k="ADX" v={String(row.adx)} />
          <Fact k="+DI / −DI" v={`${row.plus_di} / ${row.minus_di}`} />
          <Fact k="Coil %" v={row.coil_width_pct != null ? row.coil_width_pct.toFixed(1) : '—'} />
          <Fact k="Breakout" v={row.breakout ? `${row.breakout} @ ${row.breakout_level ?? '—'}` : '—'} />
          <Fact k="Coil high / low" v={row.coil_high != null && row.coil_low != null ? `${row.coil_high} / ${row.coil_low}` : '—'} />
          <Fact k="Excess %" v={row.breakout_excess_pct != null ? `${row.breakout_excess_pct}` : '—'} />
        </dl>
      )}
    </div>
  )
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="fact-k">{k}</dt>
      <dd className="fact-v">{v}</dd>
    </div>
  )
}

function RadarBreadth({ green, grey, red }: { green: number; grey: number; red: number }) {
  const total = green + grey + red
  const gp = total ? (100 * green) / total : 0
  const yp = total ? (100 * grey) / total : 0
  const rp = total ? (100 * red) / total : 0
  return (
    <div className="mb-3 flex h-2.5 overflow-hidden rounded-full border border-line bg-surface">
      <div className="bg-lime" style={{ width: `${gp}%` }} />
      <div className="bg-chrome/40" style={{ width: `${yp}%` }} />
      <div className="bg-magenta" style={{ width: `${rp}%` }} />
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  const color =
    tone === 'lime' ? 'text-lime border-lime/40' : tone === 'magenta' ? 'text-magenta border-magenta/40' : 'text-ink border-line'
  return (
    <div className={`rounded-lg border bg-panel px-4 py-3 ${color}`}>
      <div className="text-sm font-semibold text-muted">{label}</div>
      <div className="font-mono text-2xl tabular">{value}</div>
    </div>
  )
}

export function PanelShell({
  title,
  subtitle,
  children,
  action,
}: {
  title: string
  subtitle?: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <section className="glass relative overflow-hidden rounded-xl p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-bold tracking-tight text-ink">{title}</h2>
          {subtitle && <p className="mt-1 max-w-4xl text-sm leading-relaxed text-muted">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty-note">{children}</p>
}

function fmtPct(v?: number | null) {
  if (v == null || Number.isNaN(v)) return 'n/a'
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
}
