# LeveriScan-style tape inside QMIE (strategy map)

Public #LevierScan posts (~48×/day on **30m** closes) report, per alt:

| Field | QMIE implementation |
|--------|---------------------|
| cur | Last closed 30m `close` |
| 24h VWAP | Rolling 48×30m typical-price VWAP |
| dist | `close − vwap` and `(close/vwap − 1)×100` |
| atr | Wilder ATR(14) on 30m as **% of price** |
| 24h vol | Sum `close×volume` over last 48 bars |
| rsi | Wilder RSI(14) on 30m |
| rsi (+N) | Δ vs previous scan snapshot (in-memory) |
| adx | Wilder ADX(14) on 30m |
| Rank | Bullish **tape score** (dist, momentum, vol, trend) |

**Tape labels** (human-readable; not orders) mirror community wording:

- High RSI + wide VWAP extension → caution / partial-profit tone  
- Low ADX + wide dist → “coiled hot” / breakout tease  
- Very high RSI + ADX → parabolic / FOMO language  

**#CryptoGainers:** prior UTC day top **% movers** on the scan universe; today’s 30m pass flags if symbol was in yesterday’s top‑N (**continuation watch**). Forward stats logged to SQLite/CSV later.

**Not in v1:** Hyperliquid order routing, Kraken bot parity, C++ HFT latencies. QMIE stays **signal-only**; venue tag `[HL]` is display if symbol exists on HL meta list (optional).

**Coexistence:**

| Module | TF | Role |
|--------|-----|------|
| TEMA | 1h/4h | Swing A/A+ book |
| Long-vol | 15m | Compression + Donchian breakout |
| **LevierScan** | **30m** | Tape leaderboard + gainer watch |

Frozen config: `configs/levier_scan_v1.yaml`.
