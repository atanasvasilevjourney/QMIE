import type { DonchianTurtleSnapshot, SignalRow } from '../types'
import { EmptyNote, ModuleCard, StatTile } from './layout/ModuleCard'

function fmt(n: number | null | undefined, digits = 4): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (n >= 1000) return n.toFixed(2)
  return n.toFixed(digits)
}

export function TrendPanel({
  snapshot,
  alerts,
  onSelect,
}: {
  snapshot: DonchianTurtleSnapshot | null
  alerts: SignalRow[]
  onSelect?: (s: SignalRow) => void
}) {
  if (!snapshot) {
    return (
      <ModuleCard title="Donchian turtle" subtitle="Loading…">
        <EmptyNote>Connecting to /donchian/turtle</EmptyNote>
      </ModuleCard>
    )
  }

  const asOf = snapshot.as_of ? snapshot.as_of.slice(0, 10) : '—'
  const rows = snapshot.watchlist ?? []
  const turtleAlerts = alerts.filter(
    (s) => (s.strategy || '').includes('DonchianTurtle') || s.setup_type === 'turtle',
  )

  return (
    <div className="module-grid gap-8">
      <ModuleCard
        title="Donchian turtle"
        subtitle={`Spot 1D · ${snapshot.strategy ?? 'QMIE-DonchianTurtle'} · closed ${asOf} · ${snapshot.requested ?? 0} symbols scanned`}
        footer="55/20 channels (prior bar) + optional VWAP. Not coil expansion. Not TEMA A/A+. Manual entry only."
      >
        {!snapshot.enabled && (
          <p className="empty-note mb-5">Module disabled on API (DONCHIAN_TURTLE_ENABLED=false).</p>
        )}
        <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatTile label="In trend" value={snapshot.in_trend ?? rows.length} tone="lime" />
          <StatTile label="New today" value={snapshot.new_entries ?? 0} tone="cyan" />
          <StatTile label="Watchlist" value={rows.length} />
          <StatTile label="Channel" value="55 / 20" tone="neutral" />
        </div>
        {snapshot.note && rows.length === 0 ? (
          <EmptyNote>{snapshot.note}</EmptyNote>
        ) : null}
        {rows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-sm">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Close</th>
                  <th>55d high</th>
                  <th>20d SL</th>
                  <th>Strength</th>
                  <th>Bar</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.symbol}>
                    <td className="font-mono font-semibold text-ink">{r.symbol}</td>
                    <td className="font-mono tabular">{fmt(r.price, 2)}</td>
                    <td className="font-mono tabular text-muted">{fmt(r.entry_high, 2)}</td>
                    <td className="font-mono tabular text-magenta">{fmt(r.exit_low, 2)}</td>
                    <td className="font-mono tabular text-lime">{(100 * (r.strength ?? 0)).toFixed(2)}%</td>
                    <td className="text-muted">{r.bar_time?.slice(0, 10) ?? '—'}</td>
                    <td>
                      {r.is_new_entry ? (
                        <span className="meta-chip text-cyan">new entry</span>
                      ) : (
                        <span className="meta-chip text-muted">holding</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </ModuleCard>

      <ModuleCard
        title="Dispatched turtle alerts"
        subtitle="Stored ENTRY rows from first-day breakout dispatch"
      >
        {turtleAlerts.length === 0 ? (
          <EmptyNote>No QMIE-DonchianTurtle signals yet — wait for a radar pass with a fresh breakout.</EmptyNote>
        ) : (
          <ul className="space-y-2 text-sm">
            {turtleAlerts.slice(0, 20).map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2 border-b border-line/60 pb-2">
                <span className="font-mono font-semibold">{s.symbol}</span>
                <span className="text-muted">{s.received_at?.slice(0, 10) ?? '—'}</span>
                <span className="font-mono tabular">@{fmt(s.signal_price, 2)}</span>
                <span className="text-muted">SL {fmt(s.stop_loss, 2)}</span>
                {onSelect && s.id != null ? (
                  <button type="button" className="btn btn-accent text-xs" onClick={() => onSelect(s)}>
                    Journal
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </ModuleCard>
    </div>
  )
}
