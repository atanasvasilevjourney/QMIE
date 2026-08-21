import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { ChartBook, ChartPrice, ChartTrade, JournalFill } from '../types'
import { Empty, PanelShell } from './RadarPanel'

const TFS = ['1h', '4h', '1d'] as const

export function ChartsPanel({
  focusSymbol,
  focusTimeframe,
  fills,
}: {
  focusSymbol?: string | null
  focusTimeframe?: string | null
  fills: JournalFill[]
}) {
  const [book, setBook] = useState<ChartBook | null>(null)
  const [price, setPrice] = useState<ChartPrice | null>(null)
  const [symbol, setSymbol] = useState(focusSymbol || '')
  const [tf, setTf] = useState((focusTimeframe || '1h').toLowerCase())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const fallbackSymbols = useMemo(() => {
    const c = new Map<string, number>()
    for (const f of fills) {
      if (f.symbol) c.set(f.symbol, (c.get(f.symbol) || 0) + 1)
    }
    return [...c.entries()].sort((a, b) => b[1] - a[1]).map(([s, n]) => ({ symbol: s, fills: n }))
  }, [fills])

  const symbols = book?.symbols?.length ? book.symbols : fallbackSymbols

  useEffect(() => {
    if (focusSymbol) setSymbol(focusSymbol)
    if (focusTimeframe) setTf(focusTimeframe.toLowerCase())
  }, [focusSymbol, focusTimeframe])

  useEffect(() => {
    if (!symbol && symbols[0]?.symbol) setSymbol(symbols[0].symbol)
  }, [symbol, symbols])

  useEffect(() => {
    let cancelled = false
    setBusy(true)
    api
      .chartsBook()
      .then((b) => {
        if (!cancelled) setBook(b)
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setBusy(true)
    setErr(null)
    api
      .chartsPrice(symbol, tf)
      .then((p) => {
        if (!cancelled) setPrice(p)
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => {
      cancelled = true
    }
  }, [symbol, tf])

  const pnlTone =
    (book?.sum_pnl ?? 0) > 0 ? 'text-lime' : (book?.sum_pnl ?? 0) < 0 ? 'text-magenta' : 'text-chrome/70'

  return (
    <div className="grid gap-5">
      <PanelShell
        title="Paper equity"
        subtitle="Cumulative cash PnL from closed fills (paper + manual). Starting 0. Never an order."
      >
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Mini label="CLOSED" value={book?.closed ?? 0} />
          <Mini label="OPEN" value={book?.open ?? 0} />
          <Mini label="PNL USDT" value={book?.sum_pnl ?? 0} tone={pnlTone} />
          <Mini label="FILLS" value={book?.fills ?? fills.length} />
        </div>
        <EquitySvg points={book?.points ?? []} />
        {busy && !book && <p className="mt-2 font-mono text-[11px] text-chrome/50">Loading book…</p>}
      </PanelShell>

      <PanelShell
        title="Price + trade marks"
        subtitle="Closed candles from the scanner data source. ▲ entry · ▼ exit · dashed SL/TP. Fetch only while this tab is open."
      >
        <div className="mb-4 flex flex-wrap gap-2">
          {symbols.map((s) => (
            <button
              key={s.symbol}
              type="button"
              onClick={() => setSymbol(s.symbol)}
              className={`rounded-2xl px-4 py-2 font-mono text-[11px] ${
                symbol === s.symbol
                  ? 'border border-cyan/50 bg-cyan/10 text-cyan'
                  : 'border border-line/15 bg-surface/60 text-chrome/70 hover:border-cyan/30'
              }`}
            >
              {s.symbol} · {s.fills}
            </button>
          ))}
          {!symbols.length && <Empty>No fills yet — PAPER SYNC or JOURNAL first</Empty>}
        </div>
        <div className="mb-4 flex flex-wrap gap-2">
          {TFS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTf(t)}
              className={`rounded-2xl px-4 py-2 font-display text-[10px] tracking-[0.22em] ${
                tf === t
                  ? 'border border-magenta/40 bg-magenta/10 text-magenta'
                  : 'border border-line/15 text-chrome/70'
              }`}
            >
              {t.toUpperCase()}
            </button>
          ))}
        </div>
        {err && <p className="mb-3 font-mono text-[11px] text-magenta">{err}</p>}
        {price?.note && (
          <p className="mb-3 font-mono text-[11px] text-amber">
            {price.note === 'klines_unavailable' || price.note === 'no_klines'
              ? 'No closed klines — showing trade levels only'
              : price.note}
          </p>
        )}
        <PriceSvg bars={price?.bars ?? []} trades={price?.trades ?? []} />
        <TradeLegend trades={price?.trades ?? []} />
      </PanelShell>
    </div>
  )
}

function Mini({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="card rounded-2xl px-4 py-3">
      <div className="font-display text-[10px] tracking-widest text-chrome/50">{label}</div>
      <div className={`mt-1 font-mono text-xl ${tone || 'text-cyan'}`}>{value}</div>
    </div>
  )
}

function EquitySvg({ points }: { points: ChartBook['points'] }) {
  const W = 800
  const H = 220
  const L = 56
  const R = 12
  const T = 16
  const B = 28
  const series = points.filter((p) => p.n > 0)
  if (!series.length) {
    return (
      <div className="rounded-2xl border border-line/10 bg-surface/40 px-4 py-10">
        <Empty>No closed fills with PnL yet — paper exits land here after SL/TP</Empty>
      </div>
    )
  }
  const ys = series.map((p) => p.equity)
  const yMin = Math.min(0, ...ys)
  const yMax = Math.max(0, ...ys)
  const span = yMax - yMin || 1
  const x = (i: number) => L + (i / Math.max(series.length - 1, 1)) * (W - L - R)
  const y = (v: number) => T + ((yMax - v) / span) * (H - T - B)
  const d = series.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join(' ')
  const area = `M${x(0).toFixed(1)},${y(0).toFixed(1)} ${series
    .map((p, i) => `L${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`)
    .join(' ')} L${x(series.length - 1).toFixed(1)},${y(0).toFixed(1)} Z`
  const last = series[series.length - 1]
  const stroke = last.equity >= 0 ? 'var(--color-lime)' : 'var(--color-magenta)'
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Equity curve">
      <rect x="0" y="0" width={W} height={H} fill="var(--color-surface)" rx="12" />
      <line x1={L} y1={y(0)} x2={W - R} y2={y(0)} stroke="var(--color-chrome)" strokeOpacity="0.35" strokeDasharray="4 4" />
      <path d={area} fill={stroke} fillOpacity="0.12" />
      <path d={d} fill="none" stroke={stroke} strokeWidth="2.2" />
      {series.map((p, i) => (
        <circle key={p.fill_id ?? i} cx={x(i)} cy={y(p.equity)} r="3.2" fill={p.pnl >= 0 ? 'var(--color-lime)' : 'var(--color-magenta)'}>
          <title>
            #{p.fill_id} {p.symbol} PnL {p.pnl} · eq {p.equity}
          </title>
        </circle>
      ))}
      <text x="8" y={y(yMax) + 4} fill="var(--color-chrome)" fontSize="10" fontFamily="ui-monospace, monospace">
        {yMax.toFixed(1)}
      </text>
      <text x="8" y={y(yMin) + 4} fill="var(--color-chrome)" fontSize="10" fontFamily="ui-monospace, monospace">
        {yMin.toFixed(1)}
      </text>
    </svg>
  )
}

function PriceSvg({ bars, trades }: { bars: ChartPrice['bars']; trades: ChartTrade[] }) {
  const W = 900
  const H = 340
  const L = 64
  const R = 14
  const T = 18
  const B = 28
  const barPrices: number[] = []
  for (const b of bars) barPrices.push(b.h, b.l)
  const markPrices: number[] = []
  for (const t of trades) {
    markPrices.push(t.entry.price)
    if (t.exit) markPrices.push(t.exit.price)
    if (t.stop_loss != null) markPrices.push(t.stop_loss)
    if (t.take_profit != null) markPrices.push(t.take_profit)
  }
  if (!barPrices.length && !markPrices.length) {
    return (
      <div className="rounded-2xl border border-line/10 bg-surface/40 px-4 py-10">
        <Empty>Pick a symbol with fills to plot candles and marks</Empty>
      </div>
    )
  }
  let pMin: number
  let pMax: number
  if (barPrices.length) {
    pMin = Math.min(...barPrices)
    pMax = Math.max(...barPrices)
    const band = Math.max(pMax - pMin, Math.abs(pMax) * 0.02) * 0.55
    for (const p of markPrices) {
      if (p >= pMin - band && p <= pMax + band) {
        pMin = Math.min(pMin, p)
        pMax = Math.max(pMax, p)
      }
    }
  } else {
    pMin = Math.min(...markPrices)
    pMax = Math.max(...markPrices)
  }
  const times: number[] = bars.map((b) => b.t)
  for (const t of trades) {
    times.push(t.entry.t)
    if (t.exit) times.push(t.exit.t)
  }
  const t0 = Math.min(...times)
  const t1 = Math.max(...times)
  const dt = Math.max(t1 - t0, 1)
  const pad = (pMax - pMin) * 0.06 || pMax * 0.01 || 1
  const yMin = pMin - pad
  const yMax = pMax + pad
  const span = yMax - yMin || 1
  const x = (t: number) => L + ((t - t0) / dt) * (W - L - R)
  const y = (p: number) => T + ((yMax - p) / span) * (H - T - B)
  const cw = bars.length ? Math.max(1.4, ((W - L - R) / bars.length) * 0.62) : 4

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Price chart with trade marks">
      <rect x="0" y="0" width={W} height={H} fill="var(--color-surface)" rx="12" />
      <text x="8" y={T + 4} fill="var(--color-chrome)" fontSize="10" fontFamily="ui-monospace, monospace">
        {yMax.toFixed(yMax >= 100 ? 1 : 4)}
      </text>
      <text x="8" y={H - B} fill="var(--color-chrome)" fontSize="10" fontFamily="ui-monospace, monospace">
        {yMin.toFixed(yMin >= 100 ? 1 : 4)}
      </text>
      {bars.map((b) => {
        const up = b.c >= b.o
        const color = up ? 'var(--color-lime)' : 'var(--color-magenta)'
        const cx = x(b.t)
        const top = y(Math.max(b.o, b.c))
        const bot = y(Math.min(b.o, b.c))
        const bh = Math.max(1, bot - top)
        return (
          <g key={b.t}>
            <line x1={cx} y1={y(b.h)} x2={cx} y2={y(b.l)} stroke={color} strokeWidth="1" />
            <rect x={cx - cw / 2} y={top} width={cw} height={bh} fill={color} opacity="0.92" />
          </g>
        )
      })}
      {trades.map((tr) => {
        const onScale = (p: number) => p >= yMin && p <= yMax
        if (!onScale(tr.entry.price) && !(tr.exit && onScale(tr.exit.price))) {
          return <g key={tr.fill_id} />
        }
        const x0 = x(tr.entry.t)
        const x1 = x(tr.exit?.t ?? t1)
        const win = (tr.exit?.pnl ?? 0) >= 0 && tr.exit != null
        const loss = tr.exit != null && (tr.exit.pnl ?? 0) < 0
        const link = win ? 'var(--color-lime)' : loss ? 'var(--color-magenta)' : 'var(--color-cyan)'
        return (
          <g key={tr.fill_id}>
            {tr.stop_loss != null && (
              <line
                x1={x0}
                y1={y(tr.stop_loss)}
                x2={Math.max(x0 + 8, x1)}
                y2={y(tr.stop_loss)}
                stroke="var(--color-magenta)"
                strokeDasharray="5 4"
                strokeWidth="1.2"
              >
                <title>SL {tr.stop_loss}</title>
              </line>
            )}
            {tr.take_profit != null && (
              <line
                x1={x0}
                y1={y(tr.take_profit)}
                x2={Math.max(x0 + 8, x1)}
                y2={y(tr.take_profit)}
                stroke="var(--color-lime)"
                strokeDasharray="5 4"
                strokeWidth="1.2"
              >
                <title>TP {tr.take_profit}</title>
              </line>
            )}
            {tr.exit && (
              <line
                x1={x0}
                y1={y(tr.entry.price)}
                x2={x1}
                y2={y(tr.exit.price)}
                stroke={link}
                strokeWidth="1.6"
                strokeOpacity="0.85"
              />
            )}
            <polygon
              points={`${x0},${y(tr.entry.price) - 8} ${x0 - 6},${y(tr.entry.price) + 5} ${x0 + 6},${y(tr.entry.price) + 5}`}
              fill="var(--color-cyan)"
            >
              <title>
                ENTRY #{tr.fill_id} {tr.side} {tr.entry.price} {tr.source}
              </title>
            </polygon>
            {tr.exit && (
              <polygon
                points={`${x1},${y(tr.exit.price) + 8} ${x1 - 6},${y(tr.exit.price) - 5} ${x1 + 6},${y(tr.exit.price) - 5}`}
                fill={link}
              >
                <title>
                  EXIT #{tr.fill_id} {tr.exit.price} PnL {tr.exit.pnl ?? '—'} {tr.exit.reason || ''}
                </title>
              </polygon>
            )}
          </g>
        )
      })}
    </svg>
  )
}

function TradeLegend({ trades }: { trades: ChartTrade[] }) {
  if (!trades.length) return null
  return (
    <div className="mt-3 max-h-48 space-y-1 overflow-auto">
      {trades.map((t) => (
        <div key={t.fill_id} className="flex flex-wrap justify-between gap-2 font-mono text-[11px] text-chrome/70">
          <span>
            #{t.fill_id} {t.symbol} {t.side} {t.source === 'paper' ? 'PAPER' : 'MANUAL'} {t.outcome}
          </span>
          <span>
            {t.entry.price}
            {t.exit ? ` → ${t.exit.price}` : ' → open'}
            {t.exit?.pnl != null ? ` · PnL ${t.exit.pnl}` : ''}
          </span>
        </div>
      ))}
    </div>
  )
}
