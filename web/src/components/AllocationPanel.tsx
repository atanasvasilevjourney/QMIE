import type { AllocationPlan } from '../types'
import { Empty, PanelShell } from './RadarPanel'

export function AllocationPanel({ plan }: { plan: AllocationPlan | null }) {
  const slots = plan?.slots ?? []
  return (
    <PanelShell
      title="Ranked Book"
      subtitle={
        plan?.timeframe
          ? `TF ${plan.timeframe} · considered ${plan.considered ?? 0}${plan.regime ? ` · ${plan.regime}` : ''}`
          : plan?.note || 'no_scan_yet'
      }
    >
      <div className="space-y-2">
        {slots.map((slot, i) => (
          <div
            key={`${slot.symbol ?? 'slot'}-${slot.rank ?? i}`}
            className="card flex items-center justify-between rounded-xl px-4 py-3"
          >
            <div>
              <div className="font-mono text-sm font-medium tabular text-ink">
                #{slot.rank ?? i + 1} {slot.symbol || '—'}
              </div>
              <div className="font-mono text-sm tabular text-muted">
                {slot.side || '—'} · {slot.grade || '—'} · {slot.cluster || '—'}
                {slot.score != null ? ` · ${slot.score}` : ''}
              </div>
            </div>
            <div className="text-right">
              <div className="font-mono text-sm text-cyan">
                {slot.weight_pct != null ? `${slot.weight_pct.toFixed(1)}%` : '—'}
              </div>
              <div className="font-mono text-sm text-muted">suggested</div>
            </div>
          </div>
        ))}
        {!slots.length && <Empty>No allocation slots — wait for a scan pass</Empty>}
      </div>
      <p className="mt-3 text-sm text-muted">
        weight_pct is a risk budget for you — QMIE never places orders.
      </p>
    </PanelShell>
  )
}
