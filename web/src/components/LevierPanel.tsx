import type { LevierGainerRow, LevierLeaderboardResponse } from '../types'
import { Empty, PanelShell } from './RadarPanel'

function fmtUsd(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  return n >= 1e6 ? `$${(n / 1e6).toFixed(2)}M` : `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

function fmtPct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

type Props = {
  snap: LevierLeaderboardResponse | null
  gainers: LevierGainerRow[]
}

export function LevierPanel({ snap, gainers }: Props) {
  const board = snap?.leaderboard ?? []
  const enabled = snap?.enabled ?? false

  return (
    <PanelShell
      title="LevierScan · 30m tape"
      subtitle={
        enabled
          ? `#LevierScan · ${snap?.generated_at?.replace('T', ' ').slice(0, 19) ?? '—'} UTC`
          : 'Enable LEVIER_SCAN_ENABLED on API'
      }
    >
      {!enabled ? (
        <Empty>LevierScan disabled — set LEVIER_SCAN_ENABLED=true in python/.env</Empty>
      ) : board.length === 0 ? (
        <Empty>No leaderboard yet — wait for next 30m close or POST /levier/once</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted border-b border-border">
              <tr>
                <th className="py-2 pr-2">#</th>
                <th className="py-2 pr-2">Symbol</th>
                <th className="py-2 pr-2">cur</th>
                <th className="py-2 pr-2">vwap24</th>
                <th className="py-2 pr-2">dist%</th>
                <th className="py-2 pr-2">atr%</th>
                <th className="py-2 pr-2">rsi</th>
                <th className="py-2 pr-2">adx</th>
                <th className="py-2 pr-2">24h vol</th>
                <th className="py-2">tape</th>
              </tr>
            </thead>
            <tbody>
              {board.map((r) => (
                <tr key={r.symbol} className="border-b border-border/60 font-mono tabular-nums">
                  <td className="py-2 pr-2 text-cyan">{r.rank}</td>
                  <td className="py-2 pr-2 text-ink">
                    {r.symbol.replace('USDT', '')}
                    {r.venue ? <span className="text-muted text-xs ml-1">[{r.venue}]</span> : null}
                    {r.gainer_watch ? <span className="text-lime text-xs ml-1">GAINER</span> : null}
                  </td>
                  <td className="py-2 pr-2">{r.price?.toFixed(4)}</td>
                  <td className="py-2 pr-2">{r.vwap24?.toFixed(4)}</td>
                  <td className={`py-2 pr-2 ${(r.dist_pct ?? 0) >= 0 ? 'text-lime' : 'text-magenta'}`}>
                    {fmtPct(r.dist_pct)}
                  </td>
                  <td className="py-2 pr-2">{fmtPct(r.atr_pct)}</td>
                  <td className="py-2 pr-2">
                    {r.rsi?.toFixed(0)}
                    {r.rsi_delta != null ? ` (${r.rsi_delta >= 0 ? '+' : ''}${r.rsi_delta})` : ''}
                  </td>
                  <td className="py-2 pr-2">{r.adx?.toFixed(0)}</td>
                  <td className="py-2 pr-2">{fmtUsd(r.quote_vol_24h)}</td>
                  <td className="py-2 text-xs text-muted max-w-[140px] truncate" title={r.label}>
                    {r.label?.replace(/_/g, ' ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {gainers.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-ink mb-2">#CryptoGainers — forward from first sighting</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-muted border-b border-border">
                <tr>
                  <th className="py-2 pr-2">Day</th>
                  <th className="py-2 pr-2">Symbol</th>
                  <th className="py-2 pr-2">Yday %</th>
                  <th className="py-2 pr-2">Fwd %</th>
                </tr>
              </thead>
              <tbody>
                {gainers.slice(0, 15).map((g) => (
                  <tr key={`${g.symbol}-${g.gainer_day}`} className="border-b border-border/60 font-mono">
                    <td className="py-2 pr-2 text-muted">{g.gainer_day}</td>
                    <td className="py-2 pr-2">{g.symbol.replace('USDT', '')}</td>
                    <td className="py-2 pr-2 text-lime">{fmtPct(g.yday_pct)}</td>
                    <td className="py-2 pr-2">{fmtPct(g.fwd_ret_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </PanelShell>
  )
}
