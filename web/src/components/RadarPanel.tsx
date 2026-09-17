import { useState, type ReactNode } from 'react'
import type { RadarRow, RadarSnapshot } from '../types'
import { EmptyNote, ModuleCard, StatTile } from './layout/ModuleCard'

function radarBias(green: number, red: number, fallback?: string | null): string {
  if (fallback && fallback !== 'UNKNOWN') return fallback
  if (green > red * 1.2 && green > 0) return 'LONG'
  if (red > green * 1.2 && red > 0) return 'SHORT'
  if (green + red <= 0) return 'UNKNOWN'
  return 'MIXED'
}

export function RadarPanel({ radar }: { radar: RadarSnapshot | null }) {
  if (!radar) {
    return (
      <ModuleCard title="Trend Radar" subtitle="Loading…">
        <EmptyNote>Connecting to /radar</EmptyNote>
      </ModuleCard>
    )
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
  const bias = radarBias(radar.green, radar.red, radar.bias)
  const statusLine = `${radar.status ?? 'Ready'} · closed ${asOf} · ${scanned}/${requested}${coverage != null ? ` · ${coverage}%` : ''}`

  return (
    <ModuleCard
      title="Trend Radar"
      subtitle={`Spot 1D context · ${statusLine} · ADX enter 25 / exit 20 · not a QMIE grade`}
      footer="Trend Radar is the spot book. Expansions are coil-UP/DOWN with prior-box stop. TEMA is the leveraged add. Early long = GREY coil pressing highs. Manual only."
    >
      {incomplete && (
        <p className="empty-note mb-5">
          Incomplete map — {radar.failed ?? 0} symbol{(radar.failed ?? 0) === 1 ? '' : 's'} failed.
          Breadth and Orbit tint are not a full-universe read.
        </p>
      )}
      <div className="mb-6 flex flex-wrap gap-2">
        <span className="meta-chip">bias {bias}</span>
        <span className="meta-chip text-muted">G &gt; 1.2× R</span>
        <span className="meta-chip">BTC {btc ?? '—'}</span>
      </div>
      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile label="Green" value={radar.green} tone="lime" />
        <StatTile label="Grey" value={radar.grey} hint="coil regime" />
        <StatTile label="Red" value={radar.red} tone="magenta" />
        <StatTile label="Coverage" value={coverage != null ? `${coverage}%` : '—'} tone="cyan" />
      </div>
      <RadarBreadth green={radar.green} grey={radar.grey} red={radar.red} />
      <div className="mt-8 grid gap-8 xl:grid-cols-2">
        <Bucket title="Fresh GREEN" rows={radar.fresh_green} render={(r) => `d${r.days_in_state} ${fmtPct(r.pct_since_flip)} ADX${r.adx}`} />
        <Bucket title="Fresh RED" rows={radar.fresh_red} render={(r) => `d${r.days_in_state} ${fmtPct(r.pct_since_flip)} ADX${r.adx}`} />
        <Bucket
          title="Expansions (spot 1D coil-UP)"
          rows={radar.expansions ?? (radar.breakouts || []).filter((r) => r.breakout === 'UP')}
          render={(r) => `UP ADX${r.adx} SL ${r.coil_low ?? '—'}`}
        />
        <Bucket
          title="Expansion shorts (spot coil-DOWN)"
          rows={radar.expansion_shorts ?? (radar.breakouts || []).filter((r) => r.breakout === 'DOWN')}
          render={(r) => `DOWN ADX${r.adx} SL ${r.coil_high ?? '—'}`}
        />
        <Bucket
          title="Early long (coil pressing highs)"
          rows={radar.early_longs ?? []}
          render={(r) => `${r.coil_width_pct?.toFixed?.(1) ?? '—'}% @${r.price}`}
        />
        <Bucket
          title="Early short (coil pressing lows)"
          rows={radar.early_shorts ?? []}
          render={(r) => `${r.coil_width_pct?.toFixed?.(1) ?? '—'}% @${r.price}`}
        />
        <Bucket title="Tight coils" rows={radar.tight_coils} render={(r) => `${r.coil_width_pct?.toFixed?.(1) ?? '—'}%`} />
        <Bucket title="Late GREEN" rows={radar.late_stage_green} render={(r) => `d${r.days_in_state} ADX${r.adx}`} />
        <Bucket title="Late RED" rows={radar.late_stage_red ?? []} render={(r) => `d${r.days_in_state} ADX${r.adx}`} />
      </div>
    </ModuleCard>
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
    <div className="module-bucket">
      <div className="mb-3 flex items-center justify-between gap-3 border-b border-line pb-2">
        <h3 className="text-sm font-semibold tracking-tight text-ink">{title}</h3>
        <span className="font-mono text-sm tabular text-muted">{count}</span>
      </div>
      {count === 0 ? (
        <p className="empty-note">None yet</p>
      ) : (
        <div className="max-h-80 space-y-3 overflow-auto pr-1">
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
          <Fact k="Closed bar" v={row.bar_time ? String(row.bar_time).replace('T', ' ').slice(0, 19) : '—'} />
          <Fact k="Flipped at" v={row.flipped_at ? String(row.flipped_at).replace('T', ' ').slice(0, 19) : '—'} />
          <Fact k="% since flip" v={row.pct_since_flip != null ? `${row.pct_since_flip}` : '—'} />
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

/** @deprecated use ModuleCard — kept for panels not yet migrated */
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
    <ModuleCard title={title} subtitle={subtitle} action={action}>
      {children}
    </ModuleCard>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <EmptyNote>{children}</EmptyNote>
}

function fmtPct(v?: number | null) {
  if (v == null || Number.isNaN(v)) return 'n/a'
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
}
