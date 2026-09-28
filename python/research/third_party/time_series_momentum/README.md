# Time series momentum (upstream reference)

Vendored from [maxlamberti/time-series-momentum](https://github.com/maxlamberti/time-series-momentum)
(Berkeley MFE / Lim, Zohren & Roberts deep momentum networks).

## What is in this folder

| Path | Purpose |
|---|---|
| `notebooks/` | Original Jupyter notebooks (`Backtest_Baseline`, `Momentum_Analysis`, `MLP_Pipeline_Daily`, …) |
| `utils/` | Small helpers used by those notebooks (`backtest.py`, `features.py`, …) |

**Data:** upstream notebooks expect Pinnacle CLC futures CSVs under `data/clc/`. QMIE does **not**
ship that data. Crypto integration lives in `research/trend_lab/tsmom.py` and
`research/notebooks/08_time_series_momentum_top10_crypto.ipynb` (Binance Vision USDT-M daily).

## QMIE integration (SIGN baseline)

The **SIGN** time-series momentum rule (12-month return sign, vol-scaled weight) is ported to
top-10 USDT perps with:

- `LOOKBACK_DAYS = 365` (crypto 24/7)
- `SIGMA_TARGET = 0.15`, EWM σ span 60 (same structure as `Backtest_Baseline.ipynb`)
- Chronological IS/OOS per `research/trend_lab/protocol.py`
- CLI: `python -m research.trend_lab.run_tsmom_crypto`

The **MLP / DMN** pipeline requires TensorFlow 1.x / Keras and CLC futures — kept here for
reference only; not executed in CI.

## License

Upstream repository has no explicit LICENSE file in the snapshot we vendored; treat as
academic reference code. Do not use DMN weights to retune live QMIE scanner `W_*`.
