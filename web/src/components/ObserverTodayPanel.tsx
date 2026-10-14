import type { AgentBriefing, PaperSnapshot, RadarSnapshot, SignalRow } from '../types'
import { PanelShell } from './RadarPanel'

export function ObserverTodayPanel({
  signals,
  radar,
  paper,
  briefing,
  onOpenScreens,
  onOpenGuide,
}: {
  signals: SignalRow[]
  radar: RadarSnapshot | null
  paper: PaperSnapshot | null
  briefing: AgentBriefing | null
  onOpenScreens: () => void
  onOpenGuide: () => void
}) {
  const leaders = signals
    .filter((s) => (s.grade === 'A+' || s.grade === 'A') && (s.timeframe === '4h' || !s.timeframe))
    .slice(0, 5)

  const g = radar?.green ?? 0
  const r = radar?.red ?? 0
  const breadth =
    radar?.status === 'ready' && g + r > 0
      ? `${Math.round((100 * g) / (g + r))}% green names`
      : 'Radar warming'

  return (
    <PanelShell title="Today" subtitle="Space Observer · swing digest · signal-only">
      <div className="grid gap-4 lg:grid-cols-3">
        <TodayCard title="Breadth" value={breadth} hint={radar?.as_of ? `Through ${radar.as_of.slice(0, 10)}` : 'Daily snapshot'} />
        <TodayCard
          title="Paper book"
          value={paper != null ? `${paper.open ?? 0} open · ${fmtPnl(paper.closed_pnl)} closed` : '—'}
          hint="Auto at signal price · never orders"
        />
        <TodayCard
          title="Briefing"
          value={
            (briefing?.summary?.scanner_headline ?? briefing?.agents?.radar?.headline ?? '').slice(0, 48) ||
            (briefing ? 'Ready' : '—')
          }
          hint={briefing?.agents?.radar?.bias ?? 'Sync for agents'}
        />
      </div>

      <section className="mt-6">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <h3 className="text-[0.9375rem] font-semibold text-ink">Top 4h A / A+</h3>
          <button type="button" className="btn btn-accent text-sm" onClick={onOpenScreens}>
            Full screens
          </button>
        </div>
        {leaders.length === 0 ? (
          <p className="text-sm text-muted">No leveraged A/A+ in the last sync — check again after the next 4h close.</p>
        ) : (
          <ul className="grid gap-2">
            {leaders.map((s) => (
              <li key={s.id ?? `${s.symbol}-${s.timeframe}`} className="card flex flex-wrap items-center justify-between gap-2 rounded-xl px-4 py-3">
                <div>
                  <span className="font-mono text-base font-medium tabular text-ink">{s.symbol}</span>
                  <span className="ml-2 font-mono text-sm text-muted">{s.grade}</span>
                </div>
                <div className="font-mono text-sm tabular text-muted">
                  {s.signal_price != null ? s.signal_price.toPrecision(5) : '—'}
                  {s.side ? ` · ${s.side}` : ''}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="mt-6 flex flex-wrap gap-2">
        <button type="button" className="btn" onClick={onOpenGuide}>
          Open playbook
        </button>
      </div>
    </PanelShell>
  )
}

function TodayCard({ title, value, hint }: { title: string; value: string; hint: string }) {
  return (
    <div className="card rounded-xl p-4">
      <p className="text-sm font-semibold text-muted">{title}</p>
      <p className="mt-2 font-mono text-lg tabular text-ink">{value}</p>
      <p className="mt-1 text-sm text-muted">{hint}</p>
    </div>
  )
}

function fmtPnl(n: number | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(2)} USDT`
}
