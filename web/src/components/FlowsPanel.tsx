import { PanelShell } from './RadarPanel'

const STEPS = [
  {
    title: 'Sync the desk',
    body: 'Confirm Online and the symbol count. Radar warms on boot; use Radar once if empty.',
  },
  {
    title: 'Land on Orbit',
    body: 'Orbit is the 3D universe. Ops holds radar plus Daily expansion, TEMA BUY, TEMA scanner, color-flip, and exit tables.',
  },
  {
    title: 'Read the guide',
    body: 'Guide tab: Daily expansion vs TEMA BUY vs color-flip, paper fills, exit PnL. You still click live size.',
  },
  {
    title: 'Wait for a setup',
    body: 'Ops tables split Daily expansion vs TEMA BUY vs TEMA scanner vs 1D color-flip vs exit. Open Details, then the visualizer.',
  },
  {
    title: 'Paper book',
    body: 'Paper sync fills every entry at signal price. Exit rows show close and PnL. Never an order.',
  },
  {
    title: 'Combo screens',
    body: 'Screens unions 4h A/A+, expansions, color-flip, coils, and the book. Space / Shift+Space. Not a new score.',
  },
  {
    title: 'Confirm on chart',
    body: 'Charts: SVG equity and closed candles with entry, exit, SL, TP. Pine should still match.',
  },
  {
    title: 'Manual live fill',
    body: 'If you take it live, log the real fill in Journal. Need 30 closed fills before retune talk.',
  },
]

export function FlowsPanel() {
  return (
    <PanelShell title="Operator flows" subtitle="Manual trading loop · no broker">
      <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {STEPS.map((s, i) => (
          <li key={s.title} className="card rounded-xl p-4">
            <div className="text-sm font-semibold text-muted">{i + 1}</div>
            <h3 className="mt-1 text-[0.9375rem] font-semibold text-ink">{s.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
          </li>
        ))}
      </ol>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <Tip title="Daily expansion" body="1D coil-UP/DOWN is QMIE-DailyExpansion. Stop is the prior box. TEMA BUY is the graded 4h add. Color-flip is a separate unranked table. You still click size yourself." />
        <Tip title="4h edge" body="Frozen OOS A/A+ was strongest on 4h (49.1% / E[R] +0.309). Pooled journal win% is not that table." />
        <Tip title="Journal R" body="realized_r needs stop_loss on the signal. Size is coin qty for cash math, not an order." />
      </div>
    </PanelShell>
  )
}

function Tip({ title, body }: { title: string; body: string }) {
  return (
    <div className="card rounded-xl p-4">
      <div className="text-sm font-semibold text-ink">{title}</div>
      <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
    </div>
  )
}
