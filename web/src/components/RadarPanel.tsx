import { useState, type ReactNode } from 'react'
import type { RadarRow, RadarSnapshot } from '../types'

export function RadarPanel({ radar }: { radar: RadarSnapshot | null }) {
  if (!radar) {
    return <PanelShell title="Trend Radar" subtitle="loading…"><Empty>Connecting to /radar</Empty></PanelShell>
  }
  return (
    <PanelShell
      title="Trend Radar"
      subtitle={`UNRANKED · ${radar.status ?? radar.note ?? 'ready'} · ${radar.succeeded ?? radar.count}/${radar.requested || radar.count}`}
    >
      <div className="mb-4 grid grid-cols-3 gap-3">
        <Stat label="GREEN" value={radar.green} tone="lime" />
        <Stat label="GREY" value={radar.grey} tone="chrome" />
        <Stat label="RED" value={radar.red} tone="magenta" />
      </div>
      <RadarBreadth green={radar.green} grey={radar.grey} red={radar.red} />
      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <Bucket title="Fresh GREEN" rows={radar.fresh_green} render={(r) => `${r.symbol} d${r.days_in_state} ${fmtPct(r.pct_since_flip)}`} />
        <Bucket title="Fresh RED" rows={radar.fresh_red} render={(r) => `${r.symbol} d${r.days_in_state} ${fmtPct(r.pct_since_flip)}`} />
        <Bucket title="Breakouts" rows={radar.breakouts} render={(r) => `${r.symbol} ${r.breakout} ADX${r.adx}`} />
        <Bucket title="Tight coils" rows={radar.tight_coils} render={(r) => `${r.symbol} ${r.coil_width_pct?.toFixed?.(1) ?? '—'}%`} />
        <Bucket title="Late GREEN" rows={radar.late_stage_green} render={(r) => `${r.symbol} d${r.days_in_state} ADX${r.adx}`} />
        <Bucket title="Late RED" rows={radar.late_stage_red ?? []} render={(r) => `${r.symbol} d${r.days_in_state} ADX${r.adx}`} />
      </div>
      <p className="mt-3 font-mono text-xs leading-relaxed text-chrome/50">
        Daily GREY→GREEN / coil-UP dispatch as BREAKOUT LONG; GREY→RED / coil-DOWN as
        BREAKOUT SHORT on the Daily breakout table (OPS). Manual only — not an A/A+ grade.
        Confirm on the 1D visualizer before clicking.
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
  return (
    <div className="mb-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-display text-sm tracking-[0.25em] text-cyan/80 uppercase">{title}</h3>
        <span className="font-mono text-sm text-chrome/40">{rows?.length ?? 0}</span>
      </div>
      <div className="max-h-72 space-y-2 overflow-auto pr-1">
        {(rows ?? []).slice(0, 12).map((r, i) => (
          <RadarRowCard
            key={`${title}-${i}-${String(r.symbol)}`}
            row={r}
            summary={render(r)}
          />
        ))}
        {!rows?.length && <Empty>none</Empty>}
      </div>
    </div>
  )
}

function RadarRowCard({ row, summary }: { row: RadarRow; summary: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card rounded-2xl">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-4 px-4 py-3.5 text-left"
      >
        <span className="min-w-0 flex-1 font-mono text-sm text-chrome/90">{summary}</span>
        <span className="shrink-0 font-display text-[11px] tracking-[0.2em] text-cyan">
          {open ? 'HIDE' : 'DETAILS'}
        </span>
      </button>
      {open && (
        <dl className="grid gap-3 border-t border-line/10 px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
          <Fact k="Symbol" v={row.symbol} />
          <Fact k="Color" v={row.color} />
          <Fact k="Days in state" v={String(row.days_in_state)} />
          <Fact k="Price" v={String(row.price)} />
          <Fact k="ADX" v={String(row.adx)} />
          <Fact k="+DI / −DI" v={`${row.plus_di} / ${row.minus_di}`} />
          <Fact k="Coil %" v={row.coil_width_pct != null ? row.coil_width_pct.toFixed(1) : '—'} />
          <Fact k="Breakout" v={row.breakout ? `${row.breakout} @ ${row.breakout_level ?? '—'}` : '—'} />
        </dl>
      )}
    </div>
  )
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="font-display text-[10px] tracking-[0.22em] text-chrome/45">{k}</dt>
      <dd className="mt-1 break-all font-mono text-sm text-chrome/85">{v}</dd>
    </div>
  )
}

function RadarBreadth({ green, grey, red }: { green: number; grey: number; red: number }) {
  const total = green + grey + red
  const gp = total ? (100 * green) / total : 0
  const yp = total ? (100 * grey) / total : 0
  const rp = total ? (100 * red) / total : 0
  return (
    <div className="mb-3 flex h-2 overflow-hidden rounded-full border border-line/15 bg-surface/80">
      <div className="bg-lime" style={{ width: `${gp}%` }} />
      <div className="bg-chrome/40" style={{ width: `${yp}%` }} />
      <div className="bg-magenta" style={{ width: `${rp}%` }} />
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  const color =
    tone === 'lime' ? 'text-lime border-lime/20' : tone === 'magenta' ? 'text-magenta border-magenta/20' : 'text-chrome/70 border-line/15'
  return (
    <div className={`rounded-2xl border bg-surface/80 px-4 py-3 ${color}`}>
      <div className="font-display text-[11px] tracking-widest opacity-70">{label}</div>
      <div className="font-mono text-2xl">{value}</div>
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
    <section className="neon-border glass relative overflow-hidden rounded-[24px] p-6">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg tracking-[0.22em] text-ink uppercase">{title}</h2>
          {subtitle && <p className="mt-1 max-w-4xl font-mono text-sm text-chrome/50">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="font-mono text-[11px] text-chrome/40">{children}</p>
}

function fmtPct(v?: number | null) {
  if (v == null || Number.isNaN(v)) return 'n/a'
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
}
