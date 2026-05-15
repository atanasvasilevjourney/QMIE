# Backtest Harness — Design Spec
**Date:** 2026-05-15
**Status:** Approved

---

## Goal

Measure the hit rate of QMIE's fixed signal engine on historical USDT-M futures data, broken down by grade (A+/A/B/C). No weight fitting — we measure, never optimise. Out-of-sample validity is preserved by design.

**Primary metric:** Win % by grade (TP touched before SL).
**Secondary metric:** Average bars-to-outcome per grade.
**Output:** Streamlit dashboard reading from a pre-computed parquet file.

---

## Architecture

```
backtest/
├── data_loader.py    # download + cache klines from data.binance.vision
├── runner.py         # walk bars → compute_signal → evaluate outcomes
├── run.py            # CLI entry point, saves results to parquet
└── app.py            # Streamlit dashboard, reads parquet
```

**Data flow:**
```
data.binance.vision  →  data_loader  →  runner  →  results/latest.parquet
                                                          ↓
                                                      app.py (Streamlit)
```

The CLI and dashboard are fully decoupled. The backtest runs once (or on a schedule), saves results to parquet, and the dashboard is a read-only viewer.

---

## Component 1: `data_loader.py`

### Data source

Binance's official public archive — no API key required, no overfitting risk:
```
https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/{TF}/{SYMBOL}-{TF}-{YYYY-MM}.zip
```
Covers USDT-M perpetual futures. 1H and 4H available from ~2020.

### Behaviour

- Computes required months from the requested date range
- Downloads only missing months; cached months load from disk
- Each ZIP → one CSV → extracted and stored as `backtest/data/cache/{symbol}/{tf}/{YYYY-MM}.parquet`
- The current (incomplete) month is never cached — always re-fetched
- Months concatenated, sorted by UTC timestamp, duplicates dropped
- Returns a single DataFrame with columns `open, high, low, close, volume` and a UTC `DatetimeIndex` — identical shape to `exchange_clients.py` output

### Defaults

- **Start:** 2 years back from today (avoids thin 2019 liquidity)
- **End:** yesterday (last complete day)
- **Warmup:** first 300 bars consumed as warmup, never recorded as signals — matches live scanner's `limit=300` exactly

---

## Component 2: `runner.py`

### Bar walk

- Iterates from bar index 300 to end
- On each bar `i`, calls `compute_signal(df[:i+1], symbol=..., timeframe=..., htf_df=..., daily_df=...)`
- HTF and daily DataFrames are **resampled** from the base DataFrame (e.g. 1H → 4H → 1D via OHLCV resample: open=first, high=max, low=min, close=last, volume=sum). No extra download needed — crypto runs 24/7 so resampling is exact
- Only records signals where `grade != "REJECT"` and `side != "NEUTRAL"`

### Outcome evaluation

For each recorded signal at bar `i`, scans forward bar-by-bar:

| Condition | Outcome |
|---|---|
| BUY: `high >= take_profit` before `low <= stop_loss` | **WIN** |
| BUY: `low <= stop_loss` before `high >= take_profit` | **LOSS** |
| SELL: `low <= take_profit` before `high >= stop_loss` | **WIN** |
| SELL: `high >= stop_loss` before `low <= take_profit` | **LOSS** |
| Neither within 100 bars | **OPEN** |

`bars_to_outcome`: bars from signal bar to first TP/SL touch. `null` for OPEN signals.

### Output DataFrame schema

```
symbol          str
timeframe       str
timestamp       datetime (UTC)
side            str       BUY / SELL
grade           str       A+ / A / B / C
score           float
daily_trend     str       bullish / bearish / unknown
entry           float
stop_loss       float
take_profit     float
atr_pct         float
outcome         str       WIN / LOSS / OPEN
bars_to_outcome int|null
```

### Performance

2 years × 10 symbols × 1H = ~175k `compute_signal` calls. Expected runtime: under 2 minutes, single-threaded. No parallelism needed at this scale.

---

## Component 3: `run.py` (CLI)

```bash
cd python
python -m backtest.run --symbols BTCUSDT ETHUSDT SOLUSDT --tf 1h 4h --start 2023-01-01
```

**Arguments:**

| Arg | Default | Description |
|---|---|---|
| `--symbols` | BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT | Symbols to backtest |
| `--tf` | `1h 4h` | Timeframes |
| `--start` | 2 years ago | Start date (YYYY-MM-DD) |
| `--end` | yesterday | End date (YYYY-MM-DD) |
| `--out` | `backtest/results/` | Output directory |

**Output:**
- `backtest/results/backtest_YYYYMMDD_HHMMSS.parquet` — timestamped run
- `backtest/results/latest.parquet` — always overwritten, used by the dashboard
- Brief summary table printed to stdout on completion

---

## Component 4: `app.py` (Streamlit Dashboard)

**Launch:**
```bash
cd python
streamlit run backtest/app.py
```

Loads `backtest/results/latest.parquet` by default (file picker in sidebar to load older runs).

### Sidebar controls

- Symbol multi-select
- Timeframe multi-select
- Grade multi-select (A+, A, B, C)
- Side toggle (BUY / SELL / Both)
- Date range slider
- Daily trend filter (bullish / bearish / unknown / All)

### Main panels

**1. Summary table**
Hit rate % and avg bars-to-outcome by grade, with signal count per grade.

| Grade | Signals | Win % | Avg bars-to-outcome |
|---|---|---|---|
| A+ | — | —% | — |
| A  | — | —% | — |
| B  | — | —% | — |
| C  | — | —% | — |

**2. Hit rate bar chart**
Grade on X-axis, win % on Y-axis. Colour: green ≥ 55%, amber 45–55%, red < 45%.

**3. Score distribution**
Histogram of signal scores split by WIN vs LOSS. Validates whether higher scores correlate with better outcomes.

**4. Signal log**
Full per-signal table, sortable by any column. Outcome colour-coded: green (WIN), red (LOSS), grey (OPEN).

---

## Dependencies

New:
- `streamlit` — dashboard
- `aiohttp` already present — used by data_loader for async downloads (or `requests` for simplicity since this is a CLI tool, not async)

Decision: use `requests` (sync) in `data_loader.py` — the CLI is not async and adding `asyncio.run()` wrappers for a batch downloader adds noise. `aiohttp` stays for the live scanner only.

`streamlit` added to a new `backtest/requirements.txt` to keep it separate from the server's `requirements.txt`.

---

## Testing

- `tests/backtest/test_data_loader.py` — mock HTTP, verify cache hit/miss logic, column shape
- `tests/backtest/test_runner.py` — synthetic OHLCV, verify WIN/LOSS/OPEN detection, bars_to_outcome counting
- No tests for `app.py` (Streamlit UI) — visual output, not unit-testable

---

## Anti-overfitting guarantee

The signal engine weights (`Weights` dataclass) are **not changed** by this harness. `compute_signal` is called as-is. The backtest measures the engine's historical performance, it does not search for better parameters. If the results look good, that is evidence the edge exists. If they look bad, that is equally valuable information — it means the grading hypothesis needs revisiting, not that we should tune weights until the numbers look good.
