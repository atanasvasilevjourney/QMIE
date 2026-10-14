import { PanelShell } from './RadarPanel'

/** Active-trader module shell — OI / CVD / flow screener land here next. */
export function FlowDeskPanel() {
  return (
    <PanelShell
      title="Flow desk"
      subtitle="Spaceman module · derivatives context · signal-only"
    >
      <div className="grid gap-4 lg:grid-cols-3">
        <FlowCard
          title="Open interest"
          status="Planned"
          body="Bar-close OI and Δ4h on each A/A+ alert. Crowding and squeeze context without mid-bar noise."
        />
        <FlowCard
          title="CVD"
          status="Planned"
          body="Aggressive buy vs sell from closed kline taker volume. Divergence chips on the flow screener."
        />
        <FlowCard
          title="Value / TPO"
          status="Planned"
          body="Session POC and value area from 30m closed bars — room-to-run next to scanner levels."
        />
      </div>
      <p className="mt-6 text-sm leading-relaxed text-muted">
        Ops and Agents stay live today. This tab is the home for active perps workflow once flow metrics
        ship. Paper book and journal are shared with Space Observer — one edge book, two speeds.
      </p>
    </PanelShell>
  )
}

function FlowCard({ title, status, body }: { title: string; status: string; body: string }) {
  return (
    <div className="card rounded-xl p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[0.9375rem] font-semibold text-ink">{title}</h3>
        <span className="rounded-md border border-cyan/35 bg-cyan/10 px-2 py-0.5 font-mono text-xs text-cyan">
          {status}
        </span>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-muted">{body}</p>
    </div>
  )
}
