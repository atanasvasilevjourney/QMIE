import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { FlowIdea, FlowRow, FlowScreener, FlowView } from '../types'
import { PanelShell } from './RadarPanel'

const VIEWS: { id: FlowView; label: string }[] = [
  { id: 'combo', label: 'Combo' },
  { id: 'oi', label: 'OI' },
  { id: 'cvd', label: 'CVD' },
  { id: 'vp', label: 'Vol profile' },
  { id: 'tpo', label: 'TPO' },
  { id: 'funding', label: 'Funding' },
]

export function FlowDeskPanel() {
  const [view, setView] = useState<FlowView>('combo')
  const [data, setData] = useState<FlowScreener | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setErr(null)
      try {
        const row = await api.flowScreener('4h', 18, view)
        if (!cancelled) setData(row)
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [view])

  const picked = data?.rows.find((r) => r.symbol === selected) ?? null

  return (
    <PanelShell
      title="Flow screeners"
      subtitle={
        data
          ? `${data.data_source?.toUpperCase() ?? '—'} · ${data.timeframe ?? '4h'} · pure flow · never orders`
          : 'Spaceman · OI · CVD · volume profile · TPO · funding'
      }
    >
      <div className="mb-4 flex flex-wrap gap-1.5" role="tablist" aria-label="Flow screeners">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            type="button"
            role="tab"
            aria-selected={view === v.id}
            className={`nav-tab ${view === v.id ? 'nav-tab-on' : ''}`}
            onClick={() => setView(v.id)}
          >
            {v.label}
          </button>
        ))}
      </div>
      {loading && <p className="text-sm text-muted">Loading {view} screener…</p>}
      {err && <p className="text-sm text-magenta">{err}</p>}
      {!loading && !err && data && data.rows.length === 0 && (
        <p className="text-sm text-muted">No symbols in universe yet — wait for scanner boot.</p>
      )}
      {data && data.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-line text-muted">
                <th className="py-2 pr-3 font-medium">Symbol</th>
                <th className="py-2 pr-3 font-medium">Price Δ</th>
                <th className="py-2 pr-3 font-medium">OI Δ</th>
                <th className="py-2 pr-3 font-medium">CVD slope</th>
                <th className="py-2 pr-3 font-medium">vs POC</th>
                <th className="py-2 pr-3 font-medium">vs TPO</th>
                <th className="py-2 pr-3 font-medium">Funding</th>
                <th className="py-2 font-medium">Idea</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => {
                const on = r.symbol === selected
                const idea = r.ideas?.[0]
                return (
                  <tr
                    key={r.symbol}
                    className={`cursor-pointer border-b border-line/60 font-mono tabular ${on ? 'bg-cyan/10' : ''}`}
                    onClick={() => setSelected(on ? null : r.symbol)}
                  >
                    <td className="py-2.5 pr-3 text-ink">{r.symbol}</td>
                    <td className={`py-2.5 pr-3 ${toneNum(r.price_change_pct)}`}>{fmtPct(r.price_change_pct)}</td>
                    <td className={`py-2.5 pr-3 ${toneNum(r.oi_change_pct)}`}>{fmtPct(r.oi_change_pct)}</td>
                    <td className={`py-2.5 pr-3 ${toneNum(r.cvd_slope)}`}>{fmtNum(r.cvd_slope)}</td>
                    <td className={`py-2.5 pr-3 ${toneNum(r.dist_to_poc_pct)}`}>{fmtPct(r.dist_to_poc_pct)}</td>
                    <td className={`py-2.5 pr-3 ${toneNum(r.dist_to_tpo_poc_pct)}`}>{fmtPct(r.dist_to_tpo_poc_pct)}</td>
                    <td className="py-2.5 pr-3 text-muted">{fmtFunding(r.funding_rate)}</td>
                    <td className="py-2.5 text-ink">{idea ? `${idea.bias} · ${idea.setup}` : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {picked && <FlowReview row={picked} source={data?.data_source} />}
      {data?.note && <p className="mt-4 text-sm leading-relaxed text-muted">{data.note}</p>}
    </PanelShell>
  )
}

function FlowReview({ row, source }: { row: FlowRow; source?: string }) {
  const ideas = row.ideas ?? []
  const tv = `https://www.tradingview.com/chart/?symbol=BINANCE:${row.symbol}.P&interval=240`
  return (
    <section className="mt-5 rounded-xl border border-cyan/30 bg-panel p-4" aria-label={`Review ${row.symbol}`}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-muted">Review</p>
          <h3 className="font-display text-xl font-bold text-ink">{row.symbol}</h3>
          <p className="mt-1 font-mono text-sm tabular text-muted">
            {fmtPx(row.close)} · Δ {fmtPct(row.price_change_pct)} · {source?.toUpperCase() ?? '—'} · {row.delta_source ?? '—'} delta
          </p>
        </div>
        <a className="btn btn-accent" href={tv} target="_blank" rel="noreferrer">
          TradingView
        </a>
      </div>
      <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="OI Δ" value={fmtPct(row.oi_change_pct)} />
        <Stat label="CVD slope" value={fmtNum(row.cvd_slope)} />
        <Stat label="POC / VAH / VAL" value={`${fmtPx(row.poc)} / ${fmtPx(row.vah)} / ${fmtPx(row.val)}`} />
        <Stat label="TPO POC" value={`${fmtPx(row.tpo_poc)}${row.poor_high ? ' · poor high' : ''}${row.poor_low ? ' · poor low' : ''}`} />
      </dl>
      <div className="mt-5 grid gap-3 lg:grid-cols-3">
        {ideas.map((idea, i) => (
          <IdeaCard key={`${idea.setup}-${i}`} idea={idea} primary={i === 0} />
        ))}
      </div>
      <p className="mt-4 text-sm text-muted">
        Ideas are for manual review only. QMIE does not execute or size positions.
      </p>
    </section>
  )
}

function IdeaCard({ idea, primary }: { idea: FlowIdea; primary: boolean }) {
  const tone =
    idea.bias === 'LONG' ? 'text-lime' : idea.bias === 'SHORT' ? 'text-magenta' : 'text-amber'
  return (
    <article className={`card rounded-xl p-4 ${primary ? 'border-cyan/40' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <span className={`font-mono text-sm font-semibold ${tone}`}>{idea.bias}</span>
        <span className="font-mono text-xs text-muted">{idea.confidence}</span>
      </div>
      <h4 className="mt-2 text-[0.9375rem] font-semibold text-ink">{idea.setup}</h4>
      <p className="mt-2 text-sm leading-relaxed text-muted">{idea.thesis}</p>
      <p className="mt-3 text-sm text-ink">
        <span className="text-muted">Invalidation · </span>
        {idea.invalidation}
      </p>
      <p className="mt-2 font-mono text-sm tabular text-muted">
        Entry {fmtPx(idea.entry)} · SL {fmtPx(idea.stop)} · TP {fmtPx(idea.target)}
      </p>
    </article>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 font-mono text-sm tabular text-ink">{value}</dd>
    </div>
  )
}

function fmtPx(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (n >= 1000) return n.toFixed(1)
  if (n >= 1) return n.toFixed(3)
  return n.toPrecision(4)
}

function fmtNum(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}k`
  return n.toFixed(n >= 100 ? 0 : 2)
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function fmtFunding(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(4)}%`
}

function toneNum(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return 'text-muted'
  if (n > 0) return 'text-lime'
  if (n < 0) return 'text-magenta'
  return 'text-muted'
}
