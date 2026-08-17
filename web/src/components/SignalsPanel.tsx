import type { SignalRow } from '../types'
import { Empty, PanelShell } from './RadarPanel'

export function SignalsPanel({
  signals,
  selectedId,
  onSelect,
}: {
  signals: SignalRow[]
  selectedId?: number | null
  onSelect: (s: SignalRow) => void
}) {
  return (
    <PanelShell title="Live Signals" subtitle="A/A+ scanner + daily breakout longs · ranked book may filter grades">
      <div className="max-h-[420px] space-y-2 overflow-auto pr-1">
        {signals.map((s) => {
          const active = selectedId === s.id
          const buy = (s.side || '').toUpperCase() === 'BUY'
          const breakout =
            (s.strategy || '').includes('DailyBreakout') ||
            s.setup_type === 'breakout' ||
            (s.reason || '').includes('trend_start')
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => onSelect(s)}
              className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${
                active
                  ? 'border-cyan/50 bg-cyan/10'
                  : breakout
                    ? 'border-amber/30 bg-amber/5 hover:border-amber/50'
                    : 'border-white/5 bg-white/[0.02] hover:border-cyan/25'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-display text-xs tracking-wider text-white">
                  {s.symbol}
                  {breakout && (
                    <span className="ml-2 font-mono text-[9px] tracking-widest text-amber">
                      BREAKOUT
                    </span>
                  )}
                </span>
                <span className={`font-mono text-[11px] ${buy ? 'text-lime' : 'text-magenta'}`}>
                  {breakout ? 'LONG TREND START' : `${s.side || '—'} · ${s.grade || '—'}`}
                </span>
              </div>
              <div className="mt-1 flex justify-between font-mono text-[10px] text-chrome/55">
                <span>
                  #{s.id} · {s.timeframe || s.strategy || 'score'} {s.score ?? ''}
                </span>
                <span>{s.signal_price ?? '—'}</span>
              </div>
            </button>
          )
        })}
        {!signals.length && <Empty>No signals yet — scan or POST /webhook</Empty>}
      </div>
    </PanelShell>
  )
}
