import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { FlowScreener } from '../types'
import { PanelShell } from './RadarPanel'

export function FlowDeskPanel() {
  const [data, setData] = useState<FlowScreener | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setErr(null)
      try {
        const row = await api.flowScreener()
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
  }, [])

  return (
    <PanelShell
      title="Flow desk"
      subtitle={
        data
          ? `${data.data_source?.toUpperCase() ?? '—'} · ${data.timeframe ?? '4h'} bar-close · ${data.note ?? ''}`
          : 'Spaceman module · derivatives context · signal-only'
      }
    >
      {loading && <p className="text-sm text-muted">Loading flow screener…</p>}
      {err && <p className="text-sm text-magenta">{err}</p>}
      {!loading && !err && data && data.rows.length === 0 && (
        <p className="text-sm text-muted">No symbols in universe yet — wait for scanner boot.</p>
      )}
      {data && data.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-line text-muted">
                <th className="py-2 pr-3 font-medium">Symbol</th>
                <th className="py-2 pr-3 font-medium">OI</th>
                <th className="py-2 pr-3 font-medium">OI Δ4h</th>
                <th className="py-2 pr-3 font-medium">Bar Δ</th>
                <th className="py-2 pr-3 font-medium">CVD slope</th>
                <th className="py-2 pr-3 font-medium">Funding</th>
                <th className="py-2 font-medium">Δ src</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.symbol} className="border-b border-line/60 font-mono tabular">
                  <td className="py-2.5 pr-3 text-ink">{r.symbol}</td>
                  <td className="py-2.5 pr-3 text-muted">{fmtNum(r.open_interest)}</td>
                  <td className={`py-2.5 pr-3 ${tonePct(r.oi_change_pct)}`}>{fmtPct(r.oi_change_pct)}</td>
                  <td className={`py-2.5 pr-3 ${toneNum(r.bar_delta)}`}>{fmtNum(r.bar_delta)}</td>
                  <td className={`py-2.5 pr-3 ${toneNum(r.cvd_slope)}`}>{fmtNum(r.cvd_slope)}</td>
                  <td className="py-2.5 pr-3 text-muted">{fmtFunding(r.funding_rate)}</td>
                  <td className="py-2.5 text-muted">{r.delta_source ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PanelShell>
  )
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

function tonePct(n: number | null | undefined): string {
  return toneNum(n)
}
