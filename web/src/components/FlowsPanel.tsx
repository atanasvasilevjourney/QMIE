import { PanelShell } from './RadarPanel'

const STEPS = [
  {
    title: 'Sync the desk',
    body: 'Confirm ONLINE + universe count. Radar warms on boot; force RADAR ONCE if empty.',
  },
  {
    title: 'Read Trend Radar',
    body: 'RGG map is context. Fresh GREEN or coil-UP on the daily close is a BREAKOUT LONG / trend-start candidate.',
  },
  {
    title: 'Wait for A/A+ or daily breakout',
    body: 'Live Signals: graded 1H/4H A/A+ or 1D BREAKOUT. Open the TradingView deep-link (visualizer on Daily for trend-start).',
  },
  {
    title: 'Confirm on chart',
    body: 'Pine visualizer should match side/grade. Optional MCP setup review on desktop Cursor.',
  },
  {
    title: 'Manual fill',
    body: 'Execute yourself. Log fill + exit in JOURNAL so live edge can be measured.',
  },
]

export function FlowsPanel() {
  return (
    <PanelShell title="Operator Flows" subtitle="best-path manual trading loop · no broker">
      <div className="relative grid gap-3 md:grid-cols-5">
        {STEPS.map((s, i) => (
          <div
            key={s.title}
            className="relative rounded-2xl border border-cyan/20 bg-gradient-to-b from-cyan/10 to-transparent p-3"
          >
            <div className="font-display text-[10px] tracking-[0.3em] text-magenta">
              STEP 0{i + 1}
            </div>
            <h3 className="mt-2 font-display text-xs tracking-wide text-white">{s.title}</h3>
            <p className="mt-2 font-mono text-[10px] leading-relaxed text-chrome/65">{s.body}</p>
            {i < STEPS.length - 1 && (
              <div className="pointer-events-none absolute -right-2 top-1/2 hidden h-px w-4 bg-cyan/40 md:block" />
            )}
          </div>
        ))}
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <Tip title="Daily breakout" body="1D GREY→GREEN (or coil-UP) = long trend start. Confirm on Daily visualizer, then click the trade yourself." />
        <Tip title="4H edge" body="OOS A/A+ was strongest on 4H — prefer that TF for graded size." />
        <Tip title="Journal R" body="realized_r needs stop_loss on the signal. Otherwise outcome stays OPEN." />
      </div>
    </PanelShell>
  )
}

function Tip({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-magenta/20 bg-magenta/5 p-3">
      <div className="font-display text-[10px] tracking-widest text-magenta uppercase">{title}</div>
      <p className="mt-2 font-mono text-[11px] text-chrome/70">{body}</p>
    </div>
  )
}
