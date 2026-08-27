import { useMemo, useState } from 'react'
import type { SignalRow } from '../types'
import { Empty, PanelShell } from './RadarPanel'

function isExit(s: SignalRow) {
  const ev = (s.event || '').toLowerCase()
  return (
    ev === 'exit' ||
    ev === 'close' ||
    s.setup_type === 'paper_exit' ||
    (s.strategy || '') === 'QMIE-Paper'
  )
}

function isBreakout(s: SignalRow) {
  if (isExit(s)) return false
  return (
    (s.strategy || '').includes('DailyBreakout') ||
    s.setup_type === 'breakout' ||
    (s.reason || '').includes('trend_start')
  )
}

function breakoutKind(s: SignalRow): 'coil' | 'flip' | 'both' | null {
  if (!isBreakout(s)) return null
  const r = s.reason || ''
  const coil = r.includes('coil_breakout')
  const flip = r.includes('trend_start')
  if (coil && flip) return 'both'
  if (coil) return 'coil'
  if (flip) return 'flip'
  return 'flip'
}

function plannedR(s: SignalRow): string {
  const entry = s.signal_price
  const sl = s.stop_loss
  const tp = s.take_profit
  if (entry == null || sl == null || tp == null) return '—'
  const risk = Math.abs(entry - sl)
  if (risk <= 0) return '—'
  return (Math.abs(tp - entry) / risk).toFixed(2)
}

function chartTimeframe(s: SignalRow): string | undefined {
  if (isBreakout(s)) return '1d'
  return s.timeframe
}

function isTema(s: SignalRow) {
  if (isBreakout(s) || isExit(s)) return false
  const strat = (s.strategy || '').toLowerCase()
  return strat.includes('scanner') || strat.includes('qmie') || Boolean(s.grade)
}

export function SignalsPanel({
  signals,
  selectedId,
  onSelect,
  onChart,
}: {
  signals: SignalRow[]
  selectedId?: number | null
  onSelect: (s: SignalRow) => void
  onChart?: (symbol: string, timeframe?: string) => void
}) {
  const { tema, breakout, exits, other } = useMemo(() => {
    const tema: SignalRow[] = []
    const breakout: SignalRow[] = []
    const exits: SignalRow[] = []
    const other: SignalRow[] = []
    for (const s of signals) {
      if (isExit(s)) exits.push(s)
      else if (isBreakout(s)) breakout.push(s)
      else if (isTema(s)) tema.push(s)
      else other.push(s)
    }
    return { tema, breakout, exits, other }
  }, [signals])

  return (
    <div className="grid gap-5">
      <StrategyTable
        title="TEMA scanner"
        subtitle="TMA 9/90/199 · closed 1h/4h A/A+ · not a tick stream. A 67–68k higher-low only lands here if that bar graded A/A+."
        rows={tema}
        selectedId={selectedId}
        onSelect={onSelect}
        onChart={onChart}
        empty="No TEMA A/A+ alerts yet"
      />
      <StrategyTable
        title="Daily breakout"
        subtitle="Unranked 1D · tagged color-flip vs coil-break · not an A/A+ grade. Chart opens 1D."
        rows={breakout}
        selectedId={selectedId}
        onSelect={onSelect}
        onChart={onChart}
        empty="No daily trend-start longs or shorts yet"
        accent="amber"
      />
      <StrategyTable
        title="Exit"
        subtitle="Paper close · SL first if same bar as TP · cash PnL + R · not a broker fill"
        rows={exits}
        selectedId={selectedId}
        onSelect={onSelect}
        onChart={onChart}
        empty="No paper exits yet — PAPER SYNC marks SL/TP on closed bars"
        accent="lime"
      />
      {other.length > 0 && (
        <StrategyTable
          title="Other inbound"
          subtitle="Webhook / untagged rows"
          rows={other}
          selectedId={selectedId}
          onSelect={onSelect}
          onChart={onChart}
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
  onChart,
}: {
  title: string
  subtitle: string
  rows: SignalRow[]
  selectedId?: number | null
  onSelect: (s: SignalRow) => void
  empty: string
  accent?: 'cyan' | 'amber' | 'lime'
  onChart?: (symbol: string, timeframe?: string) => void
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
            onChart={onChart ? () => onChart(s.symbol, chartTimeframe(s)) : undefined}
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
  onChart,
}: {
  s: SignalRow
  active: boolean
  open: boolean
  accent: 'cyan' | 'amber' | 'lime'
  onToggle: () => void
  onJournal: () => void
  onChart?: () => void
}) {
  const kind = breakoutKind(s)
  const rToTp = plannedR(s)
  const buy = (s.side || '').toUpperCase() === 'BUY'
  const breakout = isBreakout(s)
  const exit = isExit(s)
  const pnl = s.pnl
  const pnlTone = pnl == null ? 'text-muted' : pnl > 0 ? 'text-lime' : 'text-magenta'
  const breakoutLabel =
    kind === 'coil' ? (buy ? 'Coil-UP long' : 'Coil-DOWN short')
    : kind === 'both' ? (buy ? 'Flip + coil long' : 'Flip + coil short')
    : buy ? 'Color-flip long' : 'Color-flip short'
  return (
    <div
      className={`rounded-xl border text-left ${
        active
          ? 'border-cyan/50 bg-cyan/10'
          : exit || accent === 'lime'
            ? 'border-lime/40 bg-lime/10'
            : breakout || accent === 'amber'
              ? 'border-amber/40 bg-amber/10'
              : 'border-line bg-panel'
      }`}
    >
      <button type="button" onClick={onToggle} className="flex w-full items-center gap-4 px-5 py-4" aria-expanded={open}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono text-base font-medium tabular text-ink">{s.symbol}</span>
            <span className={`font-mono text-sm ${exit ? pnlTone : buy ? 'text-lime' : 'text-magenta'}`}>
              {exit
                ? `Exit · PnL ${pnl ?? '—'}${s.realized_r != null ? ` · R ${s.realized_r}` : ''}`
                : breakout
                  ? breakoutLabel
                  : `${s.side || '—'} · ${s.grade || '—'}`}
            </span>
            {breakout && kind === 'coil' && (
              <span className="rounded-md border border-amber/40 bg-amber/10 px-2 py-0.5 font-mono text-sm text-amber">coil</span>
            )}
            {breakout && kind === 'flip' && (
              <span className="rounded-md border border-amber/40 bg-amber/10 px-2 py-0.5 font-mono text-sm text-amber">color flip</span>
            )}
            {breakout && kind === 'both' && (
              <span className="rounded-md border border-amber/40 bg-amber/10 px-2 py-0.5 font-mono text-sm text-amber">flip + coil</span>
            )}
            {exit && (
              <span className="rounded-md border border-lime/40 bg-lime/10 px-2 py-0.5 font-mono text-sm text-lime">Paper close</span>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-sm tabular text-muted">
            <span>#{s.id}</span>
            <span>{(s.timeframe || '—').toUpperCase()}</span>
            {s.score != null && <span>score {s.score}</span>}
            <span>{exit ? 'exit' : 'px'} {s.signal_price ?? '—'}</span>
            {exit && s.entry_price != null && <span>entry {s.entry_price}</span>}
            <span>SL {s.stop_loss ?? '—'}</span>
            <span>TP {s.take_profit ?? '—'}</span>
            {!exit && <span>R to TP {rToTp}</span>}
          </div>
        </div>
        <span className="btn btn-sm btn-accent shrink-0">{open ? 'Hide' : 'Details'}</span>
      </button>
      {open && (
        <div className="border-t border-line px-5 py-4">
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Fact k="Strategy" v={s.strategy || '—'} />
            <Fact k="Reason" v={s.reason || '—'} />
            <Fact k="Side" v={s.side || '—'} />
            <Fact k="Entry" v={s.signal_price == null ? '—' : String(s.signal_price)} />
            <Fact k="Stop" v={s.stop_loss == null ? '—' : String(s.stop_loss)} />
            <Fact k="TP" v={s.take_profit == null ? '—' : String(s.take_profit)} />
            <Fact k="R to TP" v={rToTp} />
            <Fact k="Daily trend" v={s.daily_trend || '—'} />
            <Fact k="Received" v={s.received_at ? s.received_at.replace('T', ' ').slice(0, 19) : '—'} />
            {breakout && !s.stop_loss && (
              <Fact k="R" v="— no stop on this color-flip; not a measured book" />
            )}
            {exit && <Fact k="PnL" v={pnl == null ? '—' : String(pnl)} />}
            {exit && <Fact k="R" v={s.realized_r == null ? 'n/a — no stop on signal' : String(s.realized_r)} />}
            {exit && <Fact k="Fill id" v={s.fill_id == null ? '—' : String(s.fill_id)} />}
          </dl>
          <p className="mt-3 text-sm text-muted">
            Signal-only. QMIE does not place orders. Confirm on quant_visualizer.pine. Plan card only.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {!exit && (
              <button type="button" onClick={onJournal} className="btn btn-accent">
                Log fill in journal
              </button>
            )}
            {onChart && s.symbol && (
              <button type="button" onClick={onChart} className="btn btn-ok">
                View chart
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="fact-k">{k}</dt>
      <dd className="fact-v">{v}</dd>
    </div>
  )
}
