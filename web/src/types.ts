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
  breakout?: 'UP' | 'DOWN' | null
  breakout_level?: number | null
  breakout_excess_pct?: number | null
  is_fresh_flip: boolean
  is_tight_coil: boolean
  is_late_stage: boolean
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
  rows: RadarRow[]
  failed_symbols?: string[]
  note?: string | null
  enabled?: boolean
  has_actionable?: boolean
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
}

export type AllocationSlot = {
  rank?: number
  weight_pct?: number
  cluster?: string
  result?: {
    symbol?: string
    side?: string
    grade?: string
    score?: number
  }
}

export type AllocationPlan = {
  timeframe?: string | null
  considered?: number
  skipped_grade?: number
  slots?: AllocationSlot[]
  note?: string
  regime?: string
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
}

export type JournalStats = {
  fills: number
  closed: number
  wins: number
  losses: number
  win_pct: number
  avg_realized_r?: number | null
}

export type DeskTab = 'desk' | 'book' | 'journal' | 'flows'
