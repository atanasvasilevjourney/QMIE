/** Crypto-friendly price formatting (matches server notifier precision rules). */
export function formatPrice(price: number | null | undefined, opts?: { compact?: boolean }): string {
  if (price == null || Number.isNaN(price)) return '—'
  const abs = Math.abs(price)
  let p = 6
  if (abs >= 100) p = 2
  else if (abs >= 1) p = 4
  else if (abs >= 0.0001) p = 6
  else p = 8
  const s = price.toLocaleString(undefined, {
    minimumFractionDigits: Math.min(p, 2),
    maximumFractionDigits: p,
  })
  if (opts?.compact && abs >= 1000) {
    return s.replace(/\.00$/, '')
  }
  return s
}

export function formatPct(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}%`
}

/** Risk distance and R-multiple for long/short from entry → SL/TP. */
export function riskReward(
  side: string | null | undefined,
  entry: number | null | undefined,
  sl: number | null | undefined,
  tp: number | null | undefined,
): { riskPct: number | null; rewardPct: number | null; rr: number | null } {
  if (entry == null || sl == null || tp == null || entry <= 0) {
    return { riskPct: null, rewardPct: null, rr: null }
  }
  const buy = (side || 'BUY').toUpperCase() === 'BUY'
  const risk = buy ? entry - sl : sl - entry
  const reward = buy ? tp - entry : entry - tp
  if (risk <= 0 || reward <= 0) return { riskPct: null, rewardPct: null, rr: null }
  return {
    riskPct: (risk / entry) * 100,
    rewardPct: (reward / entry) * 100,
    rr: reward / risk,
  }
}
