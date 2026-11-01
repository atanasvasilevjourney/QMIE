# Long-Volatility Breakout (24h VWAP + Donchian) — Gate 1 Plan

**Status:** Inspection complete; implementation follows delivery gates 2–9. Lockbox (gate 10) waits for explicit operator approval of frozen `long_vol_v1.yaml`.

## Repo inspection summary

### What QMIE already has

| Area | Location | Relevance to long-vol v1 |
|------|----------|---------------------------|
| Pine-parity indicators (RMA-seeded ATR/RSI/ADX) | `python/scanner/indicators.py` | **Reuse** for `atr15`, `atr1h`, `rsi`, `adx` on resampled frames — do not duplicate math |
| TEMA signal engine (live scanner) | `python/scanner/signal_engine.py` | **Separate path** — long-vol is a new strategy module, not a change to `compute_signal` / `W_*` |
| Ranked allocation (alert book, no orders) | `python/scanner/allocator.py` | **Pattern only** — long-vol needs equity-based `RiskGovernor` (risk %, participation, correlation caps) |
| Live OHLCV REST | `python/scanner/exchange_clients.py` | **Reuse for `scan` CLI** — same schema as backtest DataFrames |
| Vision klines + parquet cache | `python/backtest/data_loader.py` | **Primary backtest I/O** — monthly ZIP → parquet; `resample_ohlcv()` for 1h from 15m |
| Signal-outcome backtest (not portfolio) | `python/backtest/runner.py`, `run.py` | **Different model** — walks `compute_signal`, TP/SL touch; long-vol needs bar loop + fills + equity |
| Paper cash replay on frozen parquet | `python/backtest/cash_sim.py` | **Reference** for max_slots / rank_by_score, not fill semantics |
| Walk-forward / split discipline | `python/research/trend_lab/protocol.py` | **Adapt** for dev/lockbox (20% tail) and walk-forward windows |
| KPI helpers | `python/research/trend_lab/metrics.py` | **Reuse/extend** for Sharpe, Sortino, Calmar, max DD |
| Live config | `python/config.py` (Pydantic Settings) | Live scanner env — long-vol uses **YAML** baseline separate from `.env` |
| Frozen live knobs | `strategy/baseline.yaml` | Unrelated to long-vol v1; do not edit for this strategy |
| Tests | `python/tests/test_indicators.py`, `python/tests/backtest/*` | Parity tolerances and mock Vision download patterns |

### Gaps vs your spec (deviations — conservative)

1. **Data source:** Repo standard is **Binance Vision** (`data.binance.vision`), not `ccxt`. No `ccxt` in `requirements.txt`. **Plan:** pluggable `DataSource` protocol with `VisionSource` (default) and optional `ParquetFolderSource`; document `ccxt` as a future adapter without adding the dependency unless approved.
2. **Package paths:** Spec lists `qmie/data/...` — repo root is `python/` as the package root. **Plan:** `python/long_vol/` namespace (features, signals, risk, backtest subpackages).
3. **CLI:** Spec says `qmie longvol ...` — repo uses `python -m backtest.run`. **Plan:** `python -m long_vol.cli` with subcommands matching the spec (alias documented in README).
4. **Timestamp index:** Vision loader uses **bar open time** (UTC `DatetimeIndex`), matching `exchange_clients.py`. Signals evaluated on **closed** bar `t`; entries/exits at **open** of `t+1` unless intrabar stop.
5. **1h resample:** Use existing `resample_ohlcv(..., "1h")` with `label="left", closed="left"`. Map 1h feature values to 15m bars via **as-of merge on closed 1h timestamps only** (no HTF peek).
6. **Funding / OI:** Vision has funding rate archives; v1 stores optional series, applies funding in engine when present. OI optional cache only.
7. **Survivorship:** Vision includes historical symbols by month; universe recompute is monthly top-N by **past** 30d median daily quote volume — delisted symbols included while parquet months exist.
8. **Pine parity:** Long-vol is research-only initially — **no** `pine/quant_visualizer.pine` change unless we wire live alerts later. Parity tests target `scanner.indicators` vs fixtures (same as TEMA backtest policy for non-scanner strategies).
9. **Allocator:** Do not route long-vol through `allocator.allocate()` — implement `long_vol.risk.governor` with compatible dataclass outputs for desk/reporting only.

### Existing abstractions we will reuse

- `scanner.indicators`: `atr`, `rsi`, `adx`, `rma`, `true_range`
- `backtest.data_loader`: `load_klines`, `load_tf_ohlcv`, `resample_ohlcv`
- `research.trend_lab.metrics`: equity KPIs
- `research.trend_lab.protocol`: chronological split patterns (modified for 80/20 dev-lockbox)
- Test patterns: `tests/backtest/test_data_loader.py` mocks, `tests/test_indicators.py` tolerances

---

## Proposed file plan (mapped to repo)

```
python/
  configs/
    long_vol_v1.yaml                 # FROZEN — never edit; v2+ for changes
  long_vol/
    __init__.py
    config.py                        # Pydantic models load YAML
    manifest.py                      # run_id = hash(config + data fp + git commit)
    data/
      protocol.py                    # DataSource ABC
      vision.py                      # wraps backtest.data_loader + funding fetch
      parquet_dir.py                 # offline folder source
      validate.py                    # monotonic, gaps, bad bars, wick outliers
      fingerprint.py                 # content hash for manifest
      universe.py                    # top-N, liquidity, stablecoin/leveraged filter
    features/
      long_vol_features.py           # pure vectorized features (§1.2)
    signals/
      state.py                       # IDLE → … state machine
      long_vol_breakout.py           # entry/exit intents (pure + stateful wrapper)
    risk/
      governor.py                    # sizing, caps, correlation
    backtest/
      engine.py                      # portfolio bar loop (§4 order of ops)
      costs.py                       # fee, slippage, funding
      metrics.py                     # strategy + robustness stats
      event_study.py                 # attribution + forward returns
      walkforward.py                 # rolling train/test
      lockbox.py                     # --confirm-lockbox guard
      report.py                      # markdown + CSV + PNG
    cli.py                           # eventstudy | backtest | plateau | walkforward | lockbox | scan
  tests/long_vol/
    conftest.py                      # synthetic OHLCV fixtures
    fixtures/                        # optional Pine reference CSV rows
    test_data_validation.py
    test_features_parity.py
    test_no_lookahead.py
    test_state_machine.py
    test_fills_costs.py
    test_engine_accounting.py
    test_determinism.py
    test_governor.py
reports/                             # gitignored output root (or long_vol/reports/)
  long_vol_v1_<run_id>/
    report.md
    manifest.json
    *.csv, *.png
docs/
  long-vol-breakout-v1-plan.md       # this file
  long-vol-breakout-assumptions.md     # conservative choices (gate 3+)
```

### Config immutability

- `long_vol_v1.yaml` is checksum-pinned in manifest; loader rejects edits unless `LONG_VOL_ALLOW_V1_OVERRIDE=1` (test-only).
- Parameter grids (plateau/walk-forward) increment `configs_tried` in manifest for deflated reasoning warning (>20 variants).

### Feature cache

- Parquet keyed by `(config_features_hash, data_fingerprint, symbol)` under `python/backtest/data/cache/long_vol_features/`.

---

## Delivery gates (checklist)

- [x] **Gate 1:** Inspection + file plan (this document)
- [ ] **Gate 2:** Data loader + validation + tests
- [ ] **Gate 3:** Features + parity + no-lookahead tests
- [ ] **Gate 4:** Event study + report (before full backtest)
- [ ] **Gate 5:** Signal state machine + tests
- [ ] **Gate 6:** Engine + costs + accounting tests
- [ ] **Gate 7:** Dev-sample backtest + cost stress + metrics
- [ ] **Gate 8:** Plateau, walk-forward, Monte Carlo, random baseline
- [ ] **Gate 9:** Final report + limitations/verdict
- [ ] **Gate 10:** Lockbox (operator approval only)

---

## Test command

```bash
cd python && pytest tests/long_vol/ -v
```

Full suite: `pytest -v` (must not regress existing 214+ tests).
