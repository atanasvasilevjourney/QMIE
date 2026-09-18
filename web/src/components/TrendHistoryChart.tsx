import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { RadarBreadthHistory } from '../types'
import { ModuleCard } from './layout/ModuleCard'

export type TrendHistoryRange = '3m' | '6m' | '1y' | '5y'

const RANGES: { id: TrendHistoryRange; label: string }[] = [
  { id: '3m', label: '3M' },
  { id: '6m', label: '6M' },
  { id: '1y', label: '1Y' },
  { id: '5y', label: '5Y' },
]

const LS_KEY = 'qmie-trend-history-range'

function loadRange(): TrendHistoryRange {
  try {
    const v = localStorage.getItem(LS_KEY)
    if (v === '3m' || v === '6m' || v === '1y' || v === '5y') return v
  } catch {
    /* ignore */
  }
  return '3m'
}

type Hover = {
  x: number
  yGreen: number
  yRed: number
  point: RadarBreadthHistory['points'][number]
}

export function TrendHistoryChart() {
  const [range, setRange] = useState<TrendHistoryRange>(loadRange)
  const [data, setData] = useState<RadarBreadthHistory | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [hover, setHover] = useState<Hover | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, range)
    } catch {
      /* ignore */
    }
  }, [range])

  useEffect(() => {
    let cancelled = false
    setErr(null)
    api
      .radarHistory(range)
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [range])

  const chart = useMemo(() => {
    const pts = data?.points ?? []
    if (pts.length < 2) return null
    const w = 640
    const h = 200
    const pad = { l: 36, r: 12, t: 16, b: 28 }
    const iw = w - pad.l - pad.r
    const ih = h - pad.t - pad.b
    const n = pts.length
    const xAt = (i: number) => pad.l + (i / (n - 1)) * iw
    const yAt = (pct: number) => pad.t + ih - (pct / 100) * ih
    const greenPath = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xAt(i)} ${yAt(p.green_pct)}`).join(' ')
    const redPath = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xAt(i)} ${yAt(p.red_pct)}`).join(' ')
    const greenArea = `${greenPath} L ${xAt(n - 1)} ${yAt(0)} L ${xAt(0)} ${yAt(0)} Z`
    const redArea = `${redPath} L ${xAt(n - 1)} ${yAt(0)} L ${xAt(0)} ${yAt(0)} Z`
    const tickEvery = Math.max(1, Math.floor(n / 6))
    const xTicks = pts
      .map((p, i) => ({ p, i }))
      .filter(({ i }) => i % tickEvery === 0 || i === n - 1)
    return { w, h, pad, pts, xAt, yAt, greenPath, redPath, greenArea, redArea, xTicks, iw }
  }, [data])

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!chart) return
    const rect = e.currentTarget.getBoundingClientRect()
    const sx = ((e.clientX - rect.left) / rect.width) * chart.w
    const rel = (sx - chart.pad.l) / chart.iw
    const idx = Math.round(rel * (chart.pts.length - 1))
    const i = Math.max(0, Math.min(chart.pts.length - 1, idx))
    const p = chart.pts[i]
    setHover({
      x: chart.xAt(i),
      yGreen: chart.yAt(p.green_pct),
      yRed: chart.yAt(p.red_pct),
      point: p,
    })
  }

  return (
    <ModuleCard
      title="Trend history"
      subtitle="Share of classified universe in uptrend vs downtrend (daily 1D RGG)"
      action={
        <div className="trend-history-range" role="group" aria-label="Chart range">
          {RANGES.map((r) => (
            <button
              key={r.id}
              type="button"
              className={`chip chip-sm ${range === r.id ? 'chip-on' : ''}`}
              onClick={() => setRange(r.id)}
            >
              {r.label}
            </button>
          ))}
        </div>
      }
    >
      {err && <p className="text-sm text-magenta">{err}</p>}
      {!err && !chart && (
        <p className="text-sm text-muted">
          {data?.count === 1
            ? 'One day recorded — history fills after each daily radar close.'
            : 'Loading breadth history…'}
        </p>
      )}
      {chart && (
        <div className="trend-history-chart-wrap">
          <div className="trend-history-legend">
            <span className="trend-legend-up">Uptrend (GREEN)</span>
            <span className="trend-legend-down">Downtrend (RED)</span>
          </div>
          <svg
            className="trend-history-svg"
            viewBox={`0 0 ${chart.w} ${chart.h}`}
            preserveAspectRatio="none"
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
            role="img"
            aria-label="Market breadth over time"
          >
            {[0, 25, 50, 75, 100].map((pct) => (
              <g key={pct}>
                <line
                  x1={chart.pad.l}
                  x2={chart.w - chart.pad.r}
                  y1={chart.yAt(pct)}
                  y2={chart.yAt(pct)}
                  className="trend-history-grid"
                />
                <text x={4} y={chart.yAt(pct) + 4} className="trend-history-axis-y">
                  {pct}%
                </text>
              </g>
            ))}
            <path d={chart.greenArea} className="trend-history-fill-up" />
            <path d={chart.redArea} className="trend-history-fill-down" />
            <path d={chart.greenPath} className="trend-history-line-up" fill="none" />
            <path d={chart.redPath} className="trend-history-line-down" fill="none" />
            {chart.xTicks.map(({ p, i }) => (
              <text
                key={p.date}
                x={chart.xAt(i)}
                y={chart.h - 6}
                className="trend-history-axis-x"
                textAnchor="middle"
              >
                {p.date.slice(5)}
              </text>
            ))}
            {hover && (
              <>
                <line
                  x1={hover.x}
                  x2={hover.x}
                  y1={chart.pad.t}
                  y2={chart.h - chart.pad.b}
                  className="trend-history-cursor"
                />
                <circle cx={hover.x} cy={hover.yGreen} r={3} className="trend-history-dot-up" />
                <circle cx={hover.x} cy={hover.yRed} r={3} className="trend-history-dot-down" />
              </>
            )}
          </svg>
          {hover && (
            <p className="trend-history-tip">
              <strong>{hover.point.date}</strong> · GREEN {hover.point.green} ({hover.point.green_pct}%) · RED{' '}
              {hover.point.red} ({hover.point.red_pct}%)
            </p>
          )}
        </div>
      )}
    </ModuleCard>
  )
}
