import { useState } from 'react'
import { api } from '../api/client'
import type { AgentBriefing, AnalysisCard, ChecklistCard, ChecklistItem, DeskDecision, DeskGraph } from '../types'
import { Empty, PanelShell } from './RadarPanel'

type AnalysisState = {
  loading?: boolean
  error?: string
  card?: AnalysisCard
}

export function AgentsPanel({
  briefing,
  graph,
  loading,
}: {
  briefing: AgentBriefing | null
  graph?: DeskGraph | null
  loading?: boolean
}) {
  const agents = briefing?.agents
  const radar = agents?.radar
  const checklist = agents?.checklist
  const analysis = agents?.analysis
  const pct = radar?.breadth_pct ?? { green: 0, grey: 0, red: 0 }
  const [analyses, setAnalyses] = useState<Record<number, AnalysisState>>({})

  const runAnalysis = async (signalId: number) => {
    setAnalyses((prev) => ({ ...prev, [signalId]: { loading: true } }))
    try {
      const card = await api.analysis(signalId)
      setAnalyses((prev) => ({ ...prev, [signalId]: { card } }))
    } catch (e) {
      setAnalyses((prev) => ({
        ...prev,
        [signalId]: { error: e instanceof Error ? e.message : String(e) },
      }))
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-12">
      <div className="lg:col-span-12">
        <PanelShell
          title="Multi-agent briefing"
          subtitle={`${briefing?.summary?.radar_bias ?? '—'} · ${briefing?.summary?.checklist_headline ?? 'syncing'} · ${briefing?.elapsed_ms ?? '—'}ms · never orders`}
        >
          <BreadthBar green={pct.green} grey={pct.grey} red={pct.red} />
          <p className="mt-2 text-sm leading-relaxed text-muted">
            Radar breadth is context. Native checklist is TrendSpider Smart Checklist on stored QMIE
            fields. Analyze is an on-demand overlay (template or OpenAI) — not a new score, not MCP,
            not an order. Briefing never calls OpenAI.
          </p>
          <DeskDag graph={graph} />
        </PanelShell>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:col-span-5 lg:grid-cols-1">
        <AgentCard name="Scanner" body={agents?.scanner} />
        <AgentCard name="Radar" body={agents?.radar} extra={radar ? `BTC ${radar.btc_color ?? '—'} (display)` : undefined} />
        <AgentCard name="Book" body={agents?.book} />
        <AgentCard name="Review" body={agents?.review} extra={reviewExtra(agents?.review)} />
        <AgentCard
          name="Analysis"
          body={analysis}
          extra={analysis?.openai_configured ? 'OpenAI key set · on-demand only' : 'Template Take · set OPENAI_API_KEY for LLM'}
        />
      </div>

      <div className="lg:col-span-7">
        <PanelShell
          title="Smart Checklist"
          subtitle={checklist?.note ?? 'GO / WATCH / SKIP overlay'}
        >
          {loading && !checklist ? <Empty>Running agents…</Empty> : null}
          <div className="space-y-3">
            {(checklist?.cards ?? []).map((c, i) => (
              <ChecklistBlock
                key={c.signal_id ?? `${c.symbol}-${c.timeframe}-${c.grade}-${c.side}-${i}`}
                card={c}
                analysis={c.signal_id != null ? analyses[c.signal_id] : undefined}
                onAnalyze={c.signal_id != null ? () => void runAnalysis(c.signal_id as number) : undefined}
              />
            ))}
            {!checklist?.cards?.length && <Empty>No A/A+, Daily expansion, or color-flip rows yet</Empty>}
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
      <div className="mb-1 flex justify-between font-mono text-sm tabular text-muted">
        <span>Green {g.toFixed(1)}%</span>
        <span>Grey {y.toFixed(1)}%</span>
        <span>Red {r.toFixed(1)}%</span>
      </div>
      <div className="flex h-3 overflow-hidden rounded-full border border-line bg-surface">
        {sum <= 0 ? (
          <div className="w-full bg-line" />
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
    <div className={`rounded-xl border px-4 py-3 ${ok ? 'border-line bg-panel' : 'border-magenta/40 bg-magenta/10'}`}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-ink">{name}</span>
        <span className={`font-mono text-sm ${ok ? 'text-lime' : 'text-magenta'}`}>{ok ? 'OK' : 'Fail'}</span>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-muted">{body?.headline || body?.error || '—'}</p>
      {extra ? <p className="mt-1 text-sm text-muted">{extra}</p> : null}
    </div>
  )
}

function ChecklistBlock({
  card,
  analysis,
  onAnalyze,
}: {
  card: ChecklistCard
  analysis?: AnalysisState
  onAnalyze?: () => void
}) {
  const tone =
    card.verdict === 'GO' ? 'border-lime/30 bg-lime/5' : card.verdict === 'SKIP' ? 'border-magenta/30 bg-magenta/5' : 'border-amber/30 bg-amber/5'
  const tag =
    card.verdict === 'GO' ? 'text-lime' : card.verdict === 'SKIP' ? 'text-magenta' : 'text-amber'
  return (
    <div className={`rounded-2xl border px-5 py-4 ${tone}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[0.9375rem] font-medium tabular text-ink">
          {card.symbol} · {card.side} · {card.grade || '—'} · {card.timeframe || '—'}
        </span>
        <span className={`font-mono text-sm font-semibold ${tag}`}>{card.verdict}</span>
      </div>
      <p className="mt-1 text-sm text-muted">{card.action}</p>
      <div className="mt-2 grid gap-1">
        {card.items.map((it) => (
          <CheckLine key={it.id} item={it} />
        ))}
      </div>
      {onAnalyze ? (
        <button
          type="button"
          onClick={onAnalyze}
          disabled={analysis?.loading}
          className="btn btn-accent mt-3"
        >
          {analysis?.loading ? 'Analyzing…' : 'Analyze'}
        </button>
      ) : (
        <p className="mt-3 text-sm text-muted">No signal id — cannot analyze</p>
      )}
      {analysis?.error ? (
        <p className="mt-2 text-sm text-magenta">{analysis.error}</p>
      ) : null}
      {analysis?.card ? <AnalysisBlock card={analysis.card} /> : null}
    </div>
  )
}

function AnalysisBlock({ card }: { card: AnalysisCard }) {
  const tone =
    card.status === 'BULLISH' ? 'text-lime' : card.status === 'BEARISH' ? 'text-magenta' : 'text-amber'
  return (
    <div className="card mt-3 rounded-xl p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`font-mono text-sm font-semibold ${tone}`}>
          {card.symbol} · {card.status}
        </span>
        <span className="font-mono text-sm text-muted">
          {card.source.startsWith('template') ? 'template' : 'openai'} · {card.zone}
        </span>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full font-mono text-sm">
          <thead>
            <tr className="text-muted">
              <th className="py-1.5 text-left font-normal">Level</th>
              <th className="py-1.5 text-left font-normal">Price</th>
              <th className="py-1.5 text-left font-normal">Note</th>
            </tr>
          </thead>
          <tbody>
            {card.levels.map((lv) => (
              <tr key={lv.type} className="border-t border-line text-muted">
                <td className="py-1 pr-2 text-cyan">{lv.type}</td>
                <td className="py-1 pr-2 text-ink">{lv.price}</td>
                <td className="py-1 text-muted">{lv.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm font-semibold text-cyan">Take</p>
      <p className="mt-1 text-sm leading-relaxed text-ink">{card.take}</p>
      <p className="mt-3 text-sm font-semibold text-amber">Counter</p>
      <p className="mt-1 text-sm leading-relaxed text-muted">{card.counter}</p>
      <p className="mt-2 text-sm text-muted">{card.note}</p>
    </div>
  )
}

function CheckLine({ item }: { item: ChecklistItem }) {
  return (
    <div className="flex flex-wrap gap-2 font-mono text-sm">
      <span className={item.passed ? 'text-lime' : item.required ? 'text-magenta' : 'text-amber'}>
        {item.passed ? 'PASS' : item.required ? 'FAIL' : 'INFO'}
      </span>
      <span className="text-muted">{item.id}</span>
      <span className="text-muted">{item.detail}</span>
    </div>
  )
}

function reviewExtra(review?: AgentBriefing['agents']['review']) {
  if (!review) return undefined
  const knob = review.proposed_knob || 'none'
  const applied = review.applied || 'n/a'
  return `knob ${knob} · applied ${applied}`
}

function DeskDag({ graph }: { graph?: DeskGraph | null }) {
  const names = graph?.graph?.nodes ?? ['start', 'data', 'strategy', 'risk', 'portfolio']
  const decisions = Object.values(graph?.decisions ?? {})
  return (
    <div className="mt-4">
      <p className="mb-2 text-sm font-semibold text-ink">
        Desk DAG · quantity always 0 · never orders
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {names.map((name, i) => {
          const node = graph?.nodes?.[name]
          const ok = node?.ok !== false
          return (
            <div key={name} className="flex items-center gap-2">
              <div className={`rounded-xl border px-4 py-3 ${ok ? 'border-cyan/40 bg-cyan/10' : 'border-magenta/40 bg-magenta/10'}`}>
                <div className="text-sm font-semibold capitalize text-ink">{name}</div>
                <div className="mt-1 max-w-[160px] truncate font-mono text-sm text-muted">
                  {node?.headline || node?.error || '—'}
                </div>
              </div>
              {i < names.length - 1 ? <span className="font-mono text-muted">→</span> : null}
            </div>
          )
        })}
      </div>
      {decisions.length ? (
        <div className="mt-3 grid gap-2">
          {decisions.map((d) => (
            <DecisionLine key={`${d.symbol}-${d.action}`} d={d} />
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted">No portfolio decisions yet</p>
      )}
    </div>
  )
}

function DecisionLine({ d }: { d: DeskDecision }) {
  const tone =
    d.action === 'skip'
      ? 'text-magenta'
      : d.action.startsWith('suggest')
        ? 'text-lime'
        : 'text-amber'
  return (
    <div className="card rounded-xl px-3 py-2 font-mono text-sm">
      <span className={`tracking-normal ${tone}`}>{d.action.toUpperCase()}</span>
      <span className="ml-2 text-ink">{d.symbol}</span>
      <span className="ml-2 text-muted">qty {d.quantity}</span>
      <span className="ml-2 text-muted">w {d.suggested_weight_pct ?? 0}%</span>
      <p className="mt-1 text-muted">{d.reasoning}</p>
    </div>
  )
}
