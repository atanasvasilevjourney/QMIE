import { useMemo, useState } from 'react'
import type { SignalRow } from '../types'
import { Empty, PanelShell } from './RadarPanel'

function isBreakout(s: SignalRow) {
  return (
    (s.strategy || '').includes('DailyBreakout') ||
    s.setup_type === 'breakout' ||
    (s.reason || '').includes('trend_start')
  )
}

function isTema(s: SignalRow) {
  if (isBreakout(s)) return false
  const strat = (s.strategy || '').toLowerCase()
  return strat.includes('scanner') || strat.includes('qmie') || Boolean(s.grade)
}

export function SignalsPanel({
  signals,
  selectedId,
  onSelect,
}: {
  signals: SignalRow[]
  selectedId?: number | null
  onSelect: (s: SignalRow) => void
}) {
  const { tema, breakout, other } = useMemo(() => {
    const tema: SignalRow[] = []
    const breakout: SignalRow[] = []
    const other: SignalRow[] = []
    for (const s of signals) {
      if (isBreakout(s)) breakout.push(s)
      else if (isTema(s)) tema.push(s)
      else other.push(s)
    }
    return { tema, breakout, other }
  }, [signals])

  return (
    <div className="grid gap-5">
      <StrategyTable
        title="TEMA scanner"
        subtitle="TMA 9/90/199 · closed 1h/4h A/A+ · not a tick stream. A 67–68k higher-low only lands here if that bar graded A/A+."
        rows={tema}
        selectedId={selectedId}
        onSelect={onSelect}
        empty="No TEMA A/A+ alerts yet"
      />
      <StrategyTable
        title="Daily breakout"
        subtitle="1D GREY→GREEN / coil-UP · unranked · not an A/A+ grade"
        rows={breakout}
        selectedId={selectedId}
        onSelect={onSelect}
        empty="No daily trend-start longs yet"
        accent="amber"
      />
      {other.length > 0 && (
        <StrategyTable
          title="Other inbound"
          subtitle="Webhook / untagged rows"
          rows={other}
          selectedId={selectedId}
          onSelect={onSelect}
          empty="—"
        />
      )}
    </div>
  )
}

function StrategyTable({
  title,
  subtitle,
  rows,
  selectedId,
  onSelect,
  empty,
  accent = 'cyan',
}: {
  title: string
  subtitle: string
  rows: SignalRow[]
  selectedId?: number | null
  onSelect: (s: SignalRow) => void
  empty: string
  accent?: 'cyan' | 'amber'
}) {
  const [openId, setOpenId] = useState<number | null>(null)
  return (
    <PanelShell title={title} subtitle={`${subtitle} · ${rows.length} row${rows.length === 1 ? '' : 's'}`}>
      <div className="space-y-3">
        {rows.map((s) => (
          <SignalCard
            key={s.id}
            s={s}
            active={selectedId === s.id}
            open={openId === s.id}
            accent={accent}
            onToggle={() => setOpenId((id) => (id === s.id ? null : s.id))}
            onJournal={() => onSelect(s)}
          />
        ))}
        {!rows.length && <Empty>{empty}</Empty>}
      </div>
    </PanelShell>
  )
}

function SignalCard({
  s,
  active,
  open,
  accent,
  onToggle,
  onJournal,
}: {
  s: SignalRow
  active: boolean
  open: boolean
  accent: 'cyan' | 'amber'
  onToggle: () => void
  onJournal: () => void
}) {
  const buy = (s.side || '').toUpperCase() === 'BUY'
  const breakout = isBreakout(s)
  return (
    <div
      className={`rounded-2xl border text-left transition ${
        active
          ? 'border-cyan/50 bg-cyan/10'
          : breakout || accent === 'amber'
            ? 'border-amber/35 bg-amber/5'
            : 'border-white/10 bg-white/[0.03]'
      }`}
    >
      <button type="button" onClick={onToggle} className="flex w-full items-center gap-4 px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-display text-base tracking-wider text-white">{s.symbol}</span>
            <span className={`font-mono text-sm ${buy ? 'text-lime' : 'text-magenta'}`}>
              {breakout ? 'LONG TREND START' : `${s.side || '—'} · ${s.grade || '—'}`}
            </span>
            {breakout && (
              <span className="font-mono text-[11px] tracking-widest text-amber">BREAKOUT</span>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-sm text-chrome/70">
            <span>#{s.id}</span>
            <span>{(s.timeframe || '—').toUpperCase()}</span>
            {s.score != null && <span>score {s.score}</span>}
            <span>px {s.signal_price ?? '—'}</span>
            <span>SL {s.stop_loss ?? '—'}</span>
            <span>TP {s.take_profit ?? '—'}</span>
          </div>
        </div>
        <span className="shrink-0 font-display text-[11px] tracking-[0.2em] text-cyan">
          {open ? 'HIDE' : 'DETAILS'}
        </span>
      </button>
      {open && (
        <div className="border-t border-white/10 px-5 py-4">
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Fact k="Strategy" v={s.strategy || '—'} />
            <Fact k="Reason" v={s.reason || '—'} />
            <Fact k="Daily trend" v={s.daily_trend || '—'} />
            <Fact k="Received" v={s.received_at ? s.received_at.replace('T', ' ').slice(0, 19) : '—'} />
          </dl>
          <p className="mt-3 font-mono text-xs text-chrome/50">
            Signal-only. Confirm on quant_visualizer.pine. DETAILS does not place an order.
          </p>
          <button
            type="button"
            onClick={onJournal}
            className="mt-4 rounded-2xl border border-cyan/40 bg-cyan/10 px-5 py-3 font-display text-xs tracking-[0.22em] text-cyan"
          >
            LOG FILL IN JOURNAL
          </button>
        </div>
      )}
    </div>
  )
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="font-display text-[10px] tracking-[0.22em] text-chrome/45">{k}</dt>
      <dd className="mt-1 break-all font-mono text-sm text-chrome/85">{v}</dd>
    </div>
  )
}
