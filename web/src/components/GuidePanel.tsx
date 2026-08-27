import type { TradingGuide } from '../types'
import { Empty, PanelShell } from './RadarPanel'

export function GuidePanel({ guide }: { guide: TradingGuide | null }) {
  if (!guide) {
    return (
      <PanelShell title="Trading Guide" subtitle="loading…">
        <Empty>Connecting to /guide</Empty>
      </PanelShell>
    )
  }
  return (
    <div className="grid gap-5">
      <PanelShell title={guide.title} subtitle={`${guide.headline ?? ''} · never orders`}>
        <p className="text-sm leading-relaxed text-muted">
          Paper fills every ENTRY. EXIT rows show close price + cash PnL. You still click live size
          yourself.
        </p>
      </PanelShell>
      <div className="grid gap-4 md:grid-cols-2">
        {guide.sections.map((s) => (
          <section key={s.id} className="card rounded-2xl px-5 py-5">
            <p className="kicker">{s.id}</p>
            <h3 className="mt-2 font-display text-lg font-bold tracking-tight text-ink">{s.title}</h3>
            <p className="mt-3 text-sm leading-relaxed text-muted">{s.body}</p>
            {!!s.rules?.length && (
              <ul className="mt-4 space-y-2">
                {s.rules.map((r) => (
                  <li key={r} className="rounded-lg border border-line bg-surface px-4 py-3 text-sm text-ink">
                    {r}
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
