export type RadarRow = {
  symbol: string
  color: 'GREEN' | 'GREY' | 'RED'
  days_in_state: number
  state_censored?: boolean
  flipped_at?: string | null
  pct_since_flip?: number | null
  price: number
  bar_time?: string | null
  adx: number
  plus_di: number
  minus_di: number
  coil_width_pct?: number | null
  coil_high?: number | null
  coil_low?: number | null
  breakout?: 'UP' | 'DOWN' | null
  breakout_level?: number | null
  breakout_excess_pct?: number | null
  is_fresh_flip: boolean
  is_tight_coil: boolean
  is_late_stage: boolean
  is_early_long?: boolean
  is_early_short?: boolean
}

export type RadarSnapshot = {
  as_of: string | null
  timeframe: string
  status?: string
  count: number
  requested?: number
  succeeded?: number
  failed?: number
  green: number
  grey: number
  red: number
  fresh_green: RadarRow[]
  fresh_red: RadarRow[]
  tight_coils: RadarRow[]
  breakouts: RadarRow[]
  late_stage_green: RadarRow[]
  late_stage_red?: RadarRow[]
  early_longs?: RadarRow[]
  early_shorts?: RadarRow[]
  rows: RadarRow[]
  failed_symbols?: string[]
  note?: string | null
  enabled?: boolean
  has_actionable?: boolean
  bias?: 'LONG' | 'SHORT' | 'MIXED' | 'UNKNOWN' | string
  btc_color?: string | null
  coverage_pct?: number | null
}

export type SignalRow = {
  id: number
  symbol: string
  side?: string
  grade?: string
  score?: number
  signal_price?: number
  stop_loss?: number
  take_profit?: number
  timeframe?: string
  received_at?: string
  daily_trend?: string
  strategy?: string
  reason?: string
  setup_type?: string
  event?: string
  pnl?: number | null
  realized_r?: number | null
  fill_id?: number | null
  entry_price?: number | null
}

/** Flat slot shape from AllocationPlan.as_dict() — not nested under `result`. */
export type AllocationSlot = {
  rank?: number
  side?: string
  symbol?: string
  cluster?: string
  grade?: string
  score?: number
  weight_pct?: number
  price?: number
  stop_loss?: number | null
  take_profit?: number | null
  daily_trend?: string | null
}

export type AllocationPlan = {
  timeframe?: string | null
  mode?: string
  considered?: number
  skipped_grade?: number
  slots?: AllocationSlot[]
  note?: string
  regime?: string
  defensive?: string | null
}

export type Health = {
  status: string
  uptime_sec: number
  db_ok: boolean
  notifiers: Record<string, string>
  scanner: {
    passes?: number
    alerts_dispatched?: number
    errors?: number
    last_pass_at?: number | null
    radar_passes?: number
    last_radar_at?: number | null
  }
  data_source?: string
  openai_configured?: boolean
  paper?: { enabled?: boolean; places_orders?: boolean }
}

export type JournalFill = {
  id: number
  signal_id: number
  fill_price: number
  size: number
  exit_price?: number | null
  notes?: string | null
  realized_r?: number | null
  outcome?: string
  symbol?: string
  side?: string
  grade?: string
  pnl?: number | null
  source?: string
  exit_reason?: string | null
  timeframe?: string
}

export type JournalStats = {
  fills: number
  closed: number
  wins: number
  losses: number
  win_pct: number
  avg_realized_r?: number | null
  sum_pnl?: number | null
  by_source?: { paper?: number; manual?: number }
  by_timeframe?: Record<string, number>
  manual_4h_closed?: number
  pooled?: boolean
  oos_edge?: string
}

export type DeskTab =
  | 'orbit'
  | 'ops'
  | 'screens'
  | 'charts'
  | 'book'
  | 'journal'
  | 'flows'
  | 'agents'
  | 'guide'

export type ChartEquityPoint = {
  t: number | null
  equity: number
  pnl: number
  n: number
  fill_id?: number
  symbol?: string
  outcome?: string
  source?: string
}

export type ChartBook = {
  places_orders: boolean
  starting_eq: number
  fills: number
  closed: number
  open: number
  sum_pnl: number
  points: ChartEquityPoint[]
  symbols: { symbol: string; fills: number }[]
  timeframes?: { timeframe: string; fills: number }[]
}

export type ChartBar = {
  t: number
  o: number
  h: number
  l: number
  c: number
  v: number
}

export type ChartMark = {
  t: number
  price: number
  i?: number
}

export type ChartTrade = {
  fill_id: number
  symbol?: string
  side: string
  grade?: string | null
  source?: string
  outcome?: string
  size?: number
  timeframe?: string | null
  aligned?: boolean
  on_ohlc?: boolean
  entry: ChartMark
  exit?: { t: number; price: number; i?: number; on_ohlc?: boolean; pnl?: number | null; reason?: string | null } | null
  stop_loss?: number | null
  take_profit?: number | null
}

export type ChartPrice = {
  symbol: string
  timeframe: string
  places_orders: boolean
  bars: ChartBar[]
  trades: ChartTrade[]
  fills: number
  note?: string | null
}

export type DeskTheme = 'dark' | 'light'

export type ChecklistItem = {
  id: string
  passed: boolean
  required: boolean
  detail: string
}

export type ChecklistCard = {
  verdict: 'GO' | 'WATCH' | 'SKIP' | string
  action: string
  symbol: string
  side: string
  grade: string
  timeframe: string
  signal_id?: number | null
  items: ChecklistItem[]
  places_orders?: boolean
}

export type AgentBlock = {
  agent?: string
  ok?: boolean
  headline?: string
  error?: string
  note?: string
  [key: string]: unknown
}

export type AgentBriefing = {
  as_of?: string
  elapsed_ms?: number
  places_orders?: boolean
  summary?: {
    radar_bias?: string
    checklist_headline?: string
    scanner_headline?: string
    review_headline?: string
    analysis_headline?: string
  }
  agents: {
    scanner?: AgentBlock & { aa_count?: number; grades?: Record<string, number> }
    radar?: AgentBlock & {
      bias?: string
      btc_color?: string | null
      buys_allowed?: boolean | null
      green?: number
      grey?: number
      red?: number
      breadth_pct?: { green: number; grey: number; red: number }
    }
    book?: AgentBlock
    checklist?: AgentBlock & { cards?: ChecklistCard[]; mix?: Record<string, number> }
    review?: AgentBlock & {
      proposed_knob?: string | null
      applied?: string | null
    }
    analysis?: AgentBlock & { openai_configured?: boolean }
  }
}

export type DeskDecision = {
  action: 'suggest_long' | 'suggest_short' | 'watch' | 'skip' | string
  quantity: number
  suggested_weight_pct?: number
  confidence?: number
  reasoning?: string
  symbol?: string
  side?: string
  grade?: string
  timeframe?: string
  signal_id?: number | null
  checklist_verdict?: string
  places_orders?: boolean
}

export type DeskGraph = {
  as_of?: string
  elapsed_ms?: number
  places_orders?: boolean
  graph?: { nodes: string[]; edges: string[][]; mermaid?: string }
  summary?: {
    strategy_headline?: string
    risk_headline?: string
    portfolio_headline?: string
  }
  nodes: Record<string, AgentBlock>
  decisions: Record<string, DeskDecision>
  note?: string
}

export type AnalysisLevel = {
  type: string
  price: number
  note: string
}

export type AnalysisCard = {
  ok: boolean
  agent?: string
  source: string
  model?: string | null
  openai_configured?: boolean
  symbol: string
  side: string
  grade: string
  timeframe: string
  signal_id?: number | null
  status: 'BULLISH' | 'BEARISH' | 'MIXED' | string
  zone: string
  take: string
  counter: string
  checklist_verdict?: string
  levels: AnalysisLevel[]
  places_orders?: boolean
  note?: string
}

export type GuideSection = {
  id: string
  title: string
  body: string
  rules?: string[]
}

export type TradingGuide = {
  title: string
  places_orders: boolean
  version?: string
  headline?: string
  sections: GuideSection[]
}

export type PaperSnapshot = {
  enabled: boolean
  notional_usdt: number
  places_orders: boolean
  fills: number
  open: number
  closed: number
  closed_pnl: number
}

export type ScreenView = 'all' | 'leaders' | 'coils' | 'breakouts' | 'book'

export type ScreenRow = {
  symbol: string
  cluster?: string
  sources: string[]
  side?: string | null
  grade?: string | null
  score?: number | null
  timeframe?: string | null
  signal_id?: number | null
  signal_price?: number | null
  stop_loss?: number | null
  take_profit?: number | null
  atr_pct?: number | null
  adx?: number | null
  radar_color?: string | null
  coil_width_pct?: number | null
  pct_since_flip?: number | null
  is_tight_coil?: boolean
  is_fresh_flip?: boolean
  is_early_long?: boolean
  is_early_short?: boolean
  breakout?: string | null
  weight_pct?: number | null
  book_rank?: number | null
  quantity: number
  places_orders: boolean
}

export type ScreenBook = {
  places_orders: boolean
  quantity: number
  view: ScreenView | string
  views: string[]
  count: number
  union_count: number
  modal_cluster?: string | null
  source_counts?: Record<string, number>
  note?: string
  rows: ScreenRow[]
}
