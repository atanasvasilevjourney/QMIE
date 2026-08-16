import type { ReactNode } from 'react'
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
      <div className="mb-3 grid grid-cols-3 gap-2">
        <Stat label="GREEN" value={radar.green} tone="lime" />
        <Stat label="GREY" value={radar.grey} tone="chrome" />
        <Stat label="RED" value={radar.red} tone="magenta" />
      </div>
      <Bucket title="Fresh GREEN" rows={radar.fresh_green} render={(r) => `${r.symbol} d${r.days_in_state} ${fmtPct(r.pct_since_flip)}`} />
      <Bucket title="Fresh RED" rows={radar.fresh_red} render={(r) => `${r.symbol} d${r.days_in_state} ${fmtPct(r.pct_since_flip)}`} />
      <Bucket title="Breakouts" rows={radar.breakouts} render={(r) => `${r.symbol} ${r.breakout} ADX${r.adx}`} />
      <Bucket title="Tight coils" rows={radar.tight_coils} render={(r) => `${r.symbol} ${r.coil_width_pct?.toFixed?.(1) ?? '—'}%`} />
      <Bucket title="Late GREEN" rows={radar.late_stage_green} render={(r) => `${r.symbol} d${r.days_in_state} ADX${r.adx}`} />
      <Bucket title="Late RED" rows={radar.late_stage_red ?? []} render={(r) => `${r.symbol} d${r.days_in_state} ADX${r.adx}`} />
      <p className="mt-3 font-mono text-[10px] leading-relaxed text-chrome/50">
        NOT an entry · NOT a QMIE A/A+ grade · MANUAL ONLY · wait for ranked alert
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
    <div className="mb-3">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="font-display text-[10px] tracking-[0.25em] text-cyan/80 uppercase">{title}</h3>
        <span className="font-mono text-[10px] text-chrome/40">{rows?.length ?? 0}</span>
      </div>
      <div className="max-h-28 space-y-1 overflow-auto pr-1">
        {(rows ?? []).slice(0, 8).map((r, i) => (
          <div
            key={`${title}-${i}-${String(r.symbol)}`}
            className="rounded-lg border border-white/5 bg-white/[0.02] px-2 py-1.5 font-mono text-[11px] text-chrome/85"
          >
            {render(r)}
          </div>
        ))}
        {!rows?.length && <Empty>none</Empty>}
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  const color =
    tone === 'lime' ? 'text-lime border-lime/20' : tone === 'magenta' ? 'text-magenta border-magenta/20' : 'text-chrome/70 border-white/10'
  return (
    <div className={`rounded-xl border bg-black/20 px-2 py-2 ${color}`}>
      <div className="font-display text-[9px] tracking-widest opacity-70">{label}</div>
      <div className="font-mono text-lg">{value}</div>
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
    <section className="neon-border glass relative overflow-hidden rounded-[24px] p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-sm tracking-[0.22em] text-white uppercase">{title}</h2>
          {subtitle && <p className="mt-1 font-mono text-[10px] text-chrome/50">{subtitle}</p>}
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
