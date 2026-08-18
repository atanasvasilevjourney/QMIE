import type { AgentBriefing, ChecklistCard, ChecklistItem } from '../types'
import { Empty, PanelShell } from './RadarPanel'

export function AgentsPanel({
  briefing,
  loading,
}: {
  briefing: AgentBriefing | null
  loading?: boolean
}) {
  const agents = briefing?.agents
  const radar = agents?.radar
  const checklist = agents?.checklist
  const pct = radar?.breadth_pct ?? { green: 0, grey: 0, red: 0 }

  return (
    <div className="grid gap-4 lg:grid-cols-12">
      <div className="lg:col-span-12">
        <PanelShell
          title="Multi-agent briefing"
          subtitle={`${briefing?.summary?.radar_bias ?? '—'} · ${briefing?.summary?.checklist_headline ?? 'syncing'} · ${briefing?.elapsed_ms ?? '—'}ms · never orders`}
        >
          <BreadthBar green={pct.green} grey={pct.grey} red={pct.red} />
          <p className="mt-2 font-mono text-[10px] text-chrome/50">
            Radar breadth is context (TredScanner FMI analog). Native checklist is TrendSpider Smart
            Checklist on stored QMIE fields — not a new score, not MCP, not an order.
          </p>
        </PanelShell>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:col-span-5 lg:grid-cols-1">
        <AgentCard name="SCANNER" body={agents?.scanner} />
        <AgentCard name="RADAR" body={agents?.radar} extra={radar ? `BTC ${radar.btc_color ?? '—'}` : undefined} />
        <AgentCard name="BOOK" body={agents?.book} />
        <AgentCard name="REVIEW" body={agents?.review} extra={reviewExtra(agents?.review)} />
      </div>

      <div className="lg:col-span-7">
        <PanelShell
          title="Smart Checklist"
          subtitle={checklist?.note ?? 'GO / WATCH / SKIP overlay'}
        >
          {loading && !checklist ? <Empty>Running agents…</Empty> : null}
          <div className="space-y-3">
            {(checklist?.cards ?? []).map((c) => (
              <ChecklistBlock key={`${c.symbol}-${c.timeframe}-${c.grade}-${c.side}`} card={c} />
            ))}
            {!checklist?.cards?.length && <Empty>No A/A+ or daily-breakout rows yet</Empty>}
          </div>
        </PanelShell>
      </div>
    </div>
  )
}

export function BreadthBar({
  green,
  grey,
  red,
}: {
  green: number
  grey: number
  red: number
}) {
  const g = Math.max(0, green)
  const y = Math.max(0, grey)
  const r = Math.max(0, red)
  const sum = g + y + r
  return (
    <div>
      <div className="mb-1 flex justify-between font-mono text-[10px] text-chrome/60">
        <span>GREEN {g.toFixed(1)}%</span>
        <span>GREY {y.toFixed(1)}%</span>
        <span>RED {r.toFixed(1)}%</span>
      </div>
      <div className="flex h-3 overflow-hidden rounded-full border border-white/10 bg-black/40">
        {sum <= 0 ? (
          <div className="w-full bg-white/5" />
        ) : (
          <>
            <div className="bg-lime" style={{ width: `${g}%` }} />
            <div className="bg-chrome/40" style={{ width: `${y}%` }} />
            <div className="bg-magenta" style={{ width: `${r}%` }} />
          </>
        )}
      </div>
    </div>
  )
}

function AgentCard({
  name,
  body,
  extra,
}: {
  name: string
  body?: { ok?: boolean; headline?: string; error?: string } | null
  extra?: string
}) {
  const ok = body?.ok !== false
  return (
    <div className={`rounded-2xl border px-3 py-3 ${ok ? 'border-white/10 bg-black/25' : 'border-magenta/40 bg-magenta/10'}`}>
      <div className="flex items-center justify-between">
        <span className="font-display text-[10px] tracking-[0.28em] text-cyan">{name}</span>
        <span className={`font-mono text-[10px] ${ok ? 'text-lime' : 'text-magenta'}`}>{ok ? 'OK' : 'FAIL'}</span>
      </div>
      <p className="mt-2 font-mono text-[11px] text-chrome/80">{body?.headline || body?.error || '—'}</p>
      {extra ? <p className="mt-1 font-mono text-[10px] text-chrome/45">{extra}</p> : null}
    </div>
  )
}

function ChecklistBlock({ card }: { card: ChecklistCard }) {
  const tone =
    card.verdict === 'GO' ? 'border-lime/30 bg-lime/5' : card.verdict === 'SKIP' ? 'border-magenta/30 bg-magenta/5' : 'border-amber/30 bg-amber/5'
  const tag =
    card.verdict === 'GO' ? 'text-lime' : card.verdict === 'SKIP' ? 'text-magenta' : 'text-amber'
  return (
    <div className={`rounded-2xl border px-3 py-3 ${tone}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-display text-xs tracking-wider text-white">
          {card.symbol} · {card.side} · {card.grade || '—'} · {card.timeframe || '—'}
        </span>
        <span className={`font-mono text-[11px] tracking-widest ${tag}`}>{card.verdict}</span>
      </div>
      <p className="mt-1 font-mono text-[10px] text-chrome/60">{card.action}</p>
      <div className="mt-2 grid gap-1">
        {card.items.map((it) => (
          <CheckLine key={it.id} item={it} />
        ))}
      </div>
    </div>
  )
}

function CheckLine({ item }: { item: ChecklistItem }) {
  return (
    <div className="flex gap-2 font-mono text-[10px]">
      <span className={item.passed ? 'text-lime' : item.required ? 'text-magenta' : 'text-amber'}>
        {item.passed ? 'PASS' : item.required ? 'FAIL' : 'INFO'}
      </span>
      <span className="text-chrome/45">{item.id}</span>
      <span className="text-chrome/70">{item.detail}</span>
    </div>
  )
}

function reviewExtra(review?: AgentBriefing['agents']['review']) {
  if (!review) return undefined
  const knob = review.proposed_knob || 'none'
  const applied = review.applied || 'n/a'
  return `knob ${knob} · applied ${applied}`
}
