import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DerivativesFlowSnapshot } from '../types'
import { PanelShell } from './RadarPanel'

const ASSETS = ['BTC', 'ETH', 'SOL'] as const

function fmtUsd(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  const a = Math.abs(n)
  const s = n < 0 ? '-' : ''
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`
  return `${s}$${a.toFixed(0)}`
}

function fmtPct(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

function PriceFlowChart({ snap }: { snap: DerivativesFlowSnapshot }) {
  const ch = snap.chart
  const bars = ch.bars_4h
  if (!bars.length) return <p className="text-sm text-muted">No 4h bars in snapshot.</p>
  const W = 720
  const H = 320
  const pad = { l: 48, r: 72, t: 28, b: 36 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b
  const lo = ch.price_lo
  const hi = ch.price_hi
  const yr = hi - lo || 1
  const y = (p: number) => pad.t + ((hi - p) / yr) * ih
  const n = bars.length
  const bw = Math.max(2, iw / n - 1)
  const levels = [
    ...(ch.level_lines.resistance ?? []).map((l) => ({ ...l, kind: 'R' as const, color: l.flipped ? '#ff9800' : '#ef5350' })),
    ...(ch.level_lines.support ?? []).map((l) => ({ ...l, kind: 'S' as const, color: '#26a69a' })),
    ...(ch.level_lines.major_above ?? []).map((l) => ({ ...l, kind: 'M' as const, color: '#ff9800' })),
    ...(ch.level_lines.major_below ?? []).map((l) => ({ ...l, kind: 'M' as const, color: '#26a69a' })),
  ]
  const vp = ch.volume_profile
  const vmax = vp.length ? Math.max(...vp.map((b) => b.norm)) : 1

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full rounded-lg border border-line bg-surface" role="img" aria-label="4h price with levels">
      {levels.map((lv, i) => (
        <g key={`${lv.kind}-${lv.price}-${i}`}>
          <line x1={pad.l} x2={W - pad.r} y1={y(lv.price)} y2={y(lv.price)} stroke={lv.color} strokeDasharray="4 3" strokeWidth={lv.kind === 'M' ? 1.4 : 0.9} opacity={0.85} />
        </g>
      ))}
      {ch.modelled_liq_bands.map((m) => (
        <rect
          key={`${m.side}-${m.price}`}
          x={pad.l}
          width={iw}
          y={y(m.price * 1.002)}
          height={Math.max(2, y(m.price * 0.998) - y(m.price * 1.002))}
          fill="#ab47bc"
          opacity={0.22}
        />
      ))}
      {bars.map((b, i) => {
        const x = pad.l + (i / Math.max(n - 1, 1)) * (iw - bw)
        const up = b.c >= b.o
        const col = up ? '#26a69a' : '#ef5350'
        const top = y(Math.max(b.o, b.c))
        const bot = y(Math.min(b.o, b.c))
        return (
          <g key={b.t}>
            <line x1={x + bw / 2} x2={x + bw / 2} y1={y(b.h)} y2={y(b.l)} stroke={col} strokeWidth={0.6} />
            <rect x={x} y={top} width={bw} height={Math.max(1, bot - top)} fill={col} />
          </g>
        )
      })}
      {vp.map((b, i) => (
        <rect
          key={i}
          x={W - pad.r + 4}
          y={y(b.price)}
          width={(b.norm / vmax) * 48}
          height={Math.max(1, (yr / vp.length) * (ih / Math.max(vp.length, 1)) * 0.8)}
          fill="#5c6bc0"
          opacity={0.35}
        />
      ))}
      <line x1={pad.l} x2={W - pad.r} y1={y(ch.last_price)} y2={y(ch.last_price)} stroke="#ffeb3b" strokeWidth={0.9} />
      <text x={pad.l} y={16} fill="var(--ink)" fontSize={11}>
        4h · last {ch.last_price.toLocaleString()} · model bands = estimate
      </text>
    </svg>
  )
}

function SeriesChart({
  title,
  series,
  colorA,
  colorB,
  labelA,
  labelB,
  unit = 'M',
}: {
  title: string
  series: { a: { t: number; v: number }[]; b: { t: number; v: number }[] }
  colorA: string
  colorB: string
  labelA: string
  labelB: string
  unit?: 'M' | 'B'
}) {
  const W = 480
  const H = 140
  const pad = 12
  const all = [...series.a, ...series.b]
  if (!all.length) return null
  const scale = unit === 'B' ? 1e9 : 1e6
  const minT = Math.min(...all.map((p) => p.t))
  const maxT = Math.max(...all.map((p) => p.t))
  const vals = all.map((p) => p.v / scale)
  const minV = Math.min(0, ...vals)
  const maxV = Math.max(...vals)
  const xr = maxT - minT || 1
  const yr = maxV - minV || 1
  const line = (pts: { t: number; v: number }[], col: string) => {
    if (pts.length < 2) return null
    const d = pts
      .map((p, i) => {
        const x = pad + ((p.t - minT) / xr) * (W - pad * 2)
        const y = pad + ((maxV - p.v / scale) / yr) * (H - pad * 2)
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`
      })
      .join(' ')
    return <path d={d} fill="none" stroke={col} strokeWidth={1.4} />
  }
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <p className="mb-2 text-xs text-muted">{title}</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line x1={pad} x2={W - pad} y1={pad + ((maxV - 0) / yr) * (H - pad * 2)} y2={pad + ((maxV - 0) / yr) * (H - pad * 2)} stroke="var(--line)" strokeWidth={0.5} />
        {line(series.a, colorA)}
        {line(series.b, colorB)}
      </svg>
      <p className="mt-1 text-[10px] text-muted">
        <span style={{ color: colorA }}>{labelA}</span> · <span style={{ color: colorB }}>{labelB}</span>
      </p>
    </div>
  )
}

function LiqBars({ snap }: { snap: DerivativesFlowSnapshot }) {
  const rows = Object.entries(snap.liquidations_24h.by_exchange).filter(([, v]) => !v.error)
  rows.sort((a, b) => (a[1].total_usd ?? 0) - (b[1].total_usd ?? 0))
  const max = Math.max(...rows.map(([, v]) => v.total_usd ?? 0), 1)
  const agg = snap.liquidations_24h.aggregate_of_complete_venues
  const longPct = agg.total_usd ? (agg.long_usd / agg.total_usd) * 100 : 0
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <p className="mb-2 text-xs font-medium text-ink">Liquidations 24h · {fmtUsd(agg.total_usd)} complete venues</p>
      <p className="mb-3 text-[10px] text-muted">Longs {longPct.toFixed(0)}% / Shorts {(100 - longPct).toFixed(0)}%</p>
      <div className="space-y-2">
        {rows.map(([ex, v]) => {
          const tot = (v.total_usd ?? 0) / max
          const lg = (v.long_usd ?? 0) / max
          return (
            <div key={ex} className="font-mono text-xs">
              <div className="mb-0.5 flex justify-between text-muted">
                <span>{ex}</span>
                <span>{fmtUsd(v.total_usd)}</span>
              </div>
              <div className="flex h-3 overflow-hidden rounded bg-surface2">
                <div className="bg-magenta/80" style={{ width: `${lg * 100}%` }} title="longs" />
                <div className="bg-cyan/70" style={{ width: `${Math.max(0, tot - lg) * 100}%` }} title="shorts" />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function DerivativesFlowPanel() {
  const [asset, setAsset] = useState<(typeof ASSETS)[number]>('BTC')
  const [snap, setSnap] = useState<DerivativesFlowSnapshot | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(
    async (refresh = false) => {
      setLoading(true)
      setErr(null)
      try {
        const row = await api.derivativesFlow(asset, refresh)
        setSnap(row)
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [asset],
  )

  useEffect(() => {
    void load(false)
  }, [load])

  const ag = snap?.open_interest.change_from_history?.aggregate_OKX_Gate_HTX

  return (
    <PanelShell
      title="Derivatives flow"
      subtitle={
        snap
          ? `${snap.asset} · ${snap.generated_at_utc}${snap.cached ? ` · cache ${snap.cache_age_sec}s` : ''} · sources: ${(snap.sources_contributed ?? []).slice(0, 6).join(', ') || '—'}`
          : 'Multi-venue OI · CVD · funding · liquidations'
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {ASSETS.map((a) => (
          <button
            key={a}
            type="button"
            className={`nav-tab ${asset === a ? 'nav-tab-on' : ''}`}
            onClick={() => setAsset(a)}
          >
            {a}
          </button>
        ))}
        <button type="button" className="btn-ghost text-xs" onClick={() => void load(true)} disabled={loading}>
          Refresh
        </button>
      </div>
      {loading && <p className="text-sm text-muted">Loading derivatives snapshot…</p>}
      {err && <p className="text-sm text-magenta">{err}</p>}
      {snap && (
        <>
          <SnapshotHeader snap={snap} ag={ag} />
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <PriceFlowChart snap={snap} />
            </div>
            <LiqBars snap={snap} />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <SeriesChart
              title={`CVD cumulative (${fmtUsd(snap.cvd.spot_24h.total_usd)} spot / ${fmtUsd(snap.cvd.perp_24h.total_usd)} perp 24h)`}
              series={{
                a: snap.chart.spot_cvd_cum.map((p) => ({ t: p.t, v: p.cvd_usd })),
                b: snap.chart.perp_cvd_cum.map((p) => ({ t: p.t, v: p.cvd_usd })),
              }}
              colorA="#42a5f5"
              colorB="#ef5350"
              labelA="Spot"
              labelB="Perps"
            />
            <SeriesChart
              title={`OI OKX+Gate+HTX · 1h ${fmtPct(ag?.chg_1h_pct)} · 4h ${fmtPct(ag?.chg_4h_pct)} · 24h ${fmtPct(ag?.chg_24h_pct)}`}
              series={{
                a: snap.chart.oi_aggregate_hourly.map((p) => ({ t: p.t, v: p.oi_usd })),
                b: [],
              }}
              colorA="#ffa726"
              colorB="#ffa726"
              labelA="Aggregate OI"
              labelB=""
              unit="B"
            />
          </div>
          <MetricsGrid snap={snap} />
        </>
      )}
    </PanelShell>
  )
}

function SnapshotHeader({
  snap,
  ag: _ag,
}: {
  snap: DerivativesFlowSnapshot
  ag?: { chg_1h_pct?: number | null; chg_4h_pct?: number | null; chg_24h_pct?: number | null }
}) {
  const p = snap.price
  return (
    <div className="rounded-xl border border-line bg-panel p-4">
      <div className="flex flex-wrap gap-4 font-mono text-sm tabular">
        <span className="text-lg text-ink">{p.spot_last.toLocaleString()}</span>
        <span className={p.change_pct >= 0 ? 'text-cyan' : 'text-magenta'}>{fmtPct(p.change_pct)} 24h</span>
        <span className="text-muted">
          H {p.high.toLocaleString()} / L {p.low.toLocaleString()}
        </span>
        <span className="text-muted">Vol {fmtUsd(p.quote_volume_usd)}</span>
        <span className="text-muted">OI {fmtUsd(snap.open_interest.total_usd_now)}</span>
        <span className="text-muted">
          Funding 8h {snap.funding.oi_weighted_8h_equiv != null ? fmtPct(snap.funding.oi_weighted_8h_equiv * 100, 4) : '—'}
        </span>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-ink/90">{snap.narrative}</p>
      {Object.keys(snap.fetch_errors ?? {}).length > 0 && (
        <p className="mt-2 text-xs text-muted">
          Partial data — failed: {Object.keys(snap.fetch_errors ?? {}).join(', ')}
        </p>
      )}
    </div>
  )
}

function MetricsGrid({ snap }: { snap: DerivativesFlowSnapshot }) {
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <MetricCard title="Long / short">
        <ul className="space-y-1 text-xs text-muted">
          {Object.entries(snap.long_short).map(([k, v]) => (
            <li key={k}>
              {k}:{' '}
              {v.error
                ? 'unavailable'
                : `${v.ratio?.toFixed(2) ?? '—'} (24h ago ${typeof v['24h_ago'] === 'number' ? v['24h_ago'].toFixed(2) : '—'})`}
            </li>
          ))}
        </ul>
      </MetricCard>
      <MetricCard title="Funding by venue">
        <ul className="space-y-1 text-xs font-mono tabular">
          {Object.entries(snap.funding.by_exchange).map(([k, v]) => (
            <li key={k} className="text-muted">
              {k}: {(v['8h_equiv'] * 100).toFixed(4)}% / 8h
            </li>
          ))}
        </ul>
      </MetricCard>
      <MetricCard title="CVD 24h by exchange">
        <p className="text-xs text-muted">Spot</p>
        <ul className="mb-2 space-y-0.5 text-xs font-mono">
          {Object.entries(snap.cvd.spot_24h.by_exchange_usd).map(([k, v]) => (
            <li key={k}>{k}: {fmtUsd(v)}</li>
          ))}
        </ul>
        <p className="text-xs text-muted">Perps</p>
        <ul className="space-y-0.5 text-xs font-mono">
          {Object.entries(snap.cvd.perp_24h.by_exchange_usd).map(([k, v]) => (
            <li key={k}>{k}: {fmtUsd(v)}</li>
          ))}
        </ul>
      </MetricCard>
      <MetricCard title="Missing liq sources">
        <ul className="space-y-1 text-[10px] text-muted">
          {Object.entries(snap.liquidations_24h.missing).map(([k, v]) => (
            <li key={k}>
              <span className="text-ink">{k}:</span> {v}
            </li>
          ))}
        </ul>
      </MetricCard>
      <MetricCard title="Modelled liq pockets (estimate)">
        <p className="mb-1 text-[10px] text-magenta">{snap.modelled_liq_clusters.note}</p>
        <ul className="space-y-0.5 text-xs font-mono">
          {snap.modelled_liq_clusters.clusters.map((c) => (
            <li key={`${c.side}-${c.price}`}>
              {c.side} ~{c.price.toLocaleString()}: {fmtUsd(c.est_notional_usd)}
            </li>
          ))}
        </ul>
      </MetricCard>
      <MetricCard title="Observed liq clusters">
        <ul className="space-y-0.5 text-xs font-mono">
          {(snap.liquidations_24h.observed_price_clusters ?? []).map((o) => (
            <li key={`${o.side}-${o.price}`}>
              {o.side} {o.price.toLocaleString()} · {fmtUsd(o.usd)}
            </li>
          ))}
        </ul>
      </MetricCard>
    </div>
  )
}

function MetricCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">{title}</p>
      {children}
    </div>
  )
}