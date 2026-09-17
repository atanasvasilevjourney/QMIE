import { useMemo } from 'react'
import type { JournalFill, ScreenRow } from '../types'
import { formatPct, formatPrice, riskReward } from '../lib/formatPrice'
import { ModuleCard, StatTile } from './layout/ModuleCard'

function sideTone(side: string | null | undefined): 'lime' | 'magenta' | 'neutral' {
  const s = (side || '').toUpperCase()
  if (s === 'BUY') return 'lime'
  if (s === 'SELL') return 'magenta'
  return 'neutral'
}

function fillForRow(row: ScreenRow | null, fills: JournalFill[]) {
  if (!row) return null
  if (row.signal_id != null) {
    const bySig = fills.find((f) => f.signal_id === row.signal_id)
    if (bySig) return bySig
  }
  return fills.find((f) => f.symbol === row.symbol) ?? null
}

function symbolTrackStats(symbol: string, fills: JournalFill[]) {
  const symFills = fills.filter((f) => f.symbol === symbol)
  const closed = symFills.filter((f) => f.outcome && f.outcome !== 'OPEN')
  const wins = closed.filter((f) => (f.pnl ?? 0) > 0).length
  const losses = closed.filter((f) => (f.pnl ?? 0) < 0).length
  const sumPnl = closed.reduce((a, f) => a + (f.pnl ?? 0), 0)
  const open = symFills.filter((f) => f.outcome === 'OPEN').length
  return { symFills, closed: closed.length, wins, losses, sumPnl, open }
}

export function ScreenAlertSetup({
  row,
  fills,
  lastClose,
  onTrackManual,
  onViewChart,
}: {
  row: ScreenRow | null
  fills: JournalFill[]
  lastClose?: number | null
  onTrackManual?: () => void
  onViewChart?: () => void
}) {
  const fill = useMemo(() => fillForRow(row, fills), [row, fills])
  const stats = useMemo(() => (row ? symbolTrackStats(row.symbol, fills) : null), [row, fills])

  const entry = row?.signal_price ?? fill?.fill_price ?? null
  const sl = row?.stop_loss ?? null
  const tp = row?.take_profit ?? null
  const side = row?.side ?? fill?.side ?? null
  const rr = riskReward(side, entry, sl, tp)

  const driftPct =
    entry != null && lastClose != null && entry > 0 ? ((lastClose - entry) / entry) * 100 : null

  if (!row) {
    return (
      <ModuleCard title="Alert setup" subtitle="Select a symbol from the combo list">
        <p className="empty-note">Entry, stop, and target from the stored scanner alert appear here.</p>
      </ModuleCard>
    )
  }

  return (
    <ModuleCard
      title={row.symbol}
      subtitle={`${(row.grade || '—').toUpperCase()} · ${(row.timeframe || '—').toUpperCase()} · alert #${row.signal_id ?? '—'} · not an order`}
      action={
        <div className="flex flex-wrap items-center gap-2">
          <span className={`alert-side-badge alert-side-${sideTone(side)}`}>{(side || '—').toUpperCase()}</span>
          {onViewChart && (
            <button type="button" className="btn btn-sm" onClick={onViewChart}>
              Charts
            </button>
          )}
          {onTrackManual && row?.signal_id != null && (
            <button type="button" className="btn btn-sm btn-ok" onClick={onTrackManual}>
              Track manually
            </button>
          )}
        </div>
      }
    >
      <div className="alert-level-grid">
        <StatTile label="Entry (signal)" value={formatPrice(entry)} hint="Closed bar at alert" tone="cyan" />
        <StatTile label="Stop loss" value={formatPrice(sl)} hint={rr.riskPct != null ? `Risk ${formatPct(rr.riskPct)}` : undefined} tone="magenta" />
        <StatTile label="Take profit" value={formatPrice(tp)} hint={rr.rewardPct != null ? `Target ${formatPct(rr.rewardPct)}` : undefined} tone="lime" />
        <StatTile
          label="R multiple"
          value={rr.rr != null ? `${rr.rr.toFixed(2)}R` : '—'}
          hint={row.score != null ? `Score ${row.score}` : undefined}
          tone="neutral"
        />
      </div>

      {(lastClose != null || driftPct != null) && entry != null && (
        <div className="alert-context-row">
          <span>
            Last close <strong className="tabular text-ink">{formatPrice(lastClose ?? undefined)}</strong>
          </span>
          {driftPct != null && (
            <span className={driftPct >= 0 ? 'text-lime' : 'text-magenta'}>
              vs entry {formatPct(driftPct)}
            </span>
          )}
        </div>
      )}

      <div className="alert-track-block">
        <h3 className="alert-track-title">Track & forward test</h3>
        <p className="text-sm text-muted">
          Paper book auto-fills at entry on OPS; closed bars hit SL/TP first. Use this to forward-test alerts — not a
          historical backtest engine.
        </p>
        {fill ? (
          <div className="alert-track-fill">
            <div className="flex flex-wrap items-center gap-2">
              <span className="meta-chip">{fill.source === 'paper' ? 'PAPER' : 'MANUAL'}</span>
              <span className="font-mono text-sm tabular text-ink">
                Fill #{fill.id} @ {formatPrice(fill.fill_price)}
              </span>
              <span className={`font-mono text-sm ${fill.outcome === 'OPEN' ? 'text-amber' : 'text-muted'}`}>
                {fill.outcome || '—'}
              </span>
            </div>
            {fill.exit_price != null && (
              <p className="mt-1 font-mono text-sm tabular text-muted">
                Exit {formatPrice(fill.exit_price)}
                {fill.pnl != null ? ` · PnL ${fill.pnl >= 0 ? '+' : ''}${fill.pnl.toFixed(2)} USDT` : ''}
                {fill.realized_r != null ? ` · ${fill.realized_r.toFixed(2)}R` : ''}
              </p>
            )}
          </div>
        ) : (
          <p className="empty-note">No journal row yet — enable paper on the scanner host or log a manual fill.</p>
        )}
        {stats && stats.symFills.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-3 font-mono text-sm tabular text-muted">
            <span>{stats.closed} closed</span>
            <span className="text-lime">{stats.wins}W</span>
            <span className="text-magenta">{stats.losses}L</span>
            <span>{stats.open} open</span>
            {stats.closed > 0 && (
              <span className={stats.sumPnl >= 0 ? 'text-lime' : 'text-magenta'}>
                Σ {stats.sumPnl >= 0 ? '+' : ''}
                {stats.sumPnl.toFixed(2)} USDT
              </span>
            )}
          </div>
        )}
      </div>
    </ModuleCard>
  )
}
