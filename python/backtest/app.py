"""
QMIE Backtest Dashboard
========================
Streamlit dashboard for exploring backtest results.

Launch:
    cd python
    streamlit run backtest/app.py
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

_RESULTS_DIR = Path(__file__).parent / "results"
_GRADE_ORDER = ["A+", "A", "B", "C"]


@st.cache_data
def load_results(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def main():
    st.set_page_config(page_title="QMIE Backtest", layout="wide")
    st.title("QMIE Backtest Dashboard")

    # ── File picker ──────────────────────────────────────────────────
    if not _RESULTS_DIR.exists() or not list(_RESULTS_DIR.glob("*.parquet")):
        st.warning("No results found. Run: `python -m backtest.run` first.")
        return

    parquet_files = sorted(_RESULTS_DIR.glob("*.parquet"), reverse=True)
    file_options = {p.name: str(p) for p in parquet_files}
    chosen = st.sidebar.selectbox("Results file", list(file_options.keys()))
    df = load_results(file_options[chosen])

    # ── Sidebar filters ──────────────────────────────────────────────
    st.sidebar.header("Filters")

    symbols = st.sidebar.multiselect(
        "Symbol", sorted(df["symbol"].unique()),
        default=sorted(df["symbol"].unique()),
    )
    tfs = st.sidebar.multiselect(
        "Timeframe", sorted(df["timeframe"].unique()),
        default=sorted(df["timeframe"].unique()),
    )
    grades = st.sidebar.multiselect("Grade", _GRADE_ORDER, default=_GRADE_ORDER)
    side = st.sidebar.radio("Side", ["Both", "BUY", "SELL"])
    trend = st.sidebar.selectbox(
        "Daily Trend", ["All", "bullish", "bearish", "unknown"]
    )

    atr_range = st.sidebar.slider(
        "ATR % range", min_value=0.0, max_value=5.0,
        value=(0.0, 5.0), step=0.1,
        help="Sweet spot: 1.0–4.0% — below=choppy/noise, above=unpredictable extremes",
    )

    min_d = df["timestamp"].dt.date.min()
    max_d = df["timestamp"].dt.date.max()
    date_range = st.sidebar.date_input(
        "Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d
    )

    # ── Apply filters ────────────────────────────────────────────────
    mask = (
        df["symbol"].isin(symbols)
        & df["timeframe"].isin(tfs)
        & df["grade"].isin(grades)
    )
    if side != "Both":
        mask &= df["side"] == side
    if trend != "All":
        mask &= df["daily_trend"] == trend
    if len(date_range) == 2:
        mask &= (df["timestamp"].dt.date >= date_range[0]) & (
            df["timestamp"].dt.date <= date_range[1]
        )
    mask &= (df["atr_pct"] >= atr_range[0]) & (df["atr_pct"] <= atr_range[1])

    filtered = df[mask].copy()
    st.caption(f"{len(filtered)} signals after filters ({len(df)} total)")

    if filtered.empty:
        st.info("No signals match current filters.")
        return

    closed = filtered[filtered["outcome"] != "OPEN"]

    # ── Panel 1: Summary table ───────────────────────────────────────
    st.subheader("Hit Rate by Grade")
    if not closed.empty:
        rows = []
        for g in _GRADE_ORDER:
            all_g = filtered[filtered["grade"] == g]
            closed_g = closed[closed["grade"] == g]
            if len(all_g) == 0:
                continue
            win_rate = (closed_g["outcome"] == "WIN").mean() if len(closed_g) else 0.0
            avg_rr = round(closed_g["rr_ratio"].mean(), 2) if len(closed_g) else None
            expectancy = pf = sqn = avg_mae = avg_mfe = None
            if len(closed_g):
                wins_r = closed_g.loc[closed_g["outcome"] == "WIN", "rr_ratio"].sum()
                losses_n = float(len(closed_g[closed_g["outcome"] == "LOSS"]))
                expectancy = round(win_rate * (avg_rr or 0) - (1 - win_rate) * 1.0, 3)
                pf = round(wins_r / losses_n, 2) if losses_n > 0 else None
                r_series = closed_g["realized_r"].dropna()
                r_std = r_series.std()
                sqn = round(r_series.mean() / r_std * math.sqrt(len(r_series)), 2) if r_std > 0 else 0.0
                if "mae_r" in closed_g.columns:
                    avg_mae = round(closed_g["mae_r"].mean(), 2)
                    avg_mfe = round(closed_g["mfe_r"].mean(), 2)
            avg_bars = round(closed_g["bars_to_outcome"].mean(), 1) if len(closed_g) else None
            sharpe = sortino = None
            try:
                import quantstats as qs
                daily_r = (
                    closed_g.set_index("timestamp")["realized_r"]
                    .dropna()
                    .resample("1D")
                    .sum()
                )
                if len(daily_r) >= 30:
                    sharpe  = round(qs.stats.sharpe(daily_r, annualize=True), 2)
                    sortino = round(qs.stats.sortino(daily_r, annualize=True), 2)
            except Exception:
                pass
            r_eq = closed_g.sort_values("timestamp")["realized_r"].dropna().cumsum()
            max_dd = round((r_eq - r_eq.cummax()).min(), 1) if len(r_eq) else None
            rows.append({
                "Grade": g,
                "Signals": len(all_g),
                "Closed": len(closed_g),
                "Win %": round(100 * win_rate, 1),
                "Avg RR": avg_rr,
                "Expectancy R": expectancy,
                "Prof. Factor": pf,
                "SQN": sqn,
                "Sharpe": sharpe,
                "Sortino": sortino,
                "Max DD R": max_dd,
                "Avg MAE R": avg_mae,
                "Avg MFE R": avg_mfe,
                "Avg bars": avg_bars,
            })
        st.dataframe(
            pd.DataFrame(rows).set_index("Grade"), use_container_width=True
        )

    # ── Panel 2: Hit rate bar chart ──────────────────────────────────
    st.subheader("Win % by Grade")
    if not closed.empty:
        chart_data = (
            closed.groupby("grade")["outcome"]
            .apply(lambda s: round(100 * (s == "WIN").mean(), 1))
            .reindex(_GRADE_ORDER)
            .dropna()
            .reset_index()
        )
        chart_data.columns = ["Grade", "Win %"]
        st.bar_chart(chart_data.set_index("Grade"))

    # ── Panel 2b: Realized-R distribution ───────────────────────────
    st.subheader("Realized R Distribution (closed trades)")
    if not closed.empty and "realized_r" in closed.columns:
        r_data = closed["realized_r"].dropna()
        if len(r_data):
            st.bar_chart(r_data.value_counts(bins=20).sort_index())

    # ── Panel 3: Score distribution ──────────────────────────────────
    st.subheader("Score Distribution: WIN vs LOSS")
    if not closed.empty:
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"WIN  ({(closed['outcome']=='WIN').sum()} signals)")
            wins = closed[closed["outcome"] == "WIN"]["score"]
            if len(wins):
                st.bar_chart(wins.value_counts(bins=10).sort_index())
        with col2:
            st.caption(f"LOSS  ({(closed['outcome']=='LOSS').sum()} signals)")
            losses = closed[closed["outcome"] == "LOSS"]["score"]
            if len(losses):
                st.bar_chart(losses.value_counts(bins=10).sort_index())

    # ── Panel 3b: MAE vs MFE scatter ────────────────────────────────
    if not closed.empty and "mae_r" in closed.columns and closed["mae_r"].notna().any():
        st.subheader("MAE vs MFE by Grade (closed trades)")
        st.caption(
            "MAE = max adverse excursion in R (how far against you before exit). "
            "MFE = max favorable excursion in R (how far in your favour before exit). "
            "Ideal: low MAE, high MFE."
        )
        mae_mfe = (
            closed.groupby("grade")[["mae_r", "mfe_r"]]
            .mean()
            .reindex(_GRADE_ORDER)
            .dropna()
            .round(2)
        )
        st.dataframe(mae_mfe, use_container_width=True)

    # ── Panel 3c: Monthly P&L heatmap ───────────────────────────────
    st.subheader("Monthly Expectancy R (closed trades by grade)")
    if not closed.empty and "realized_r" in closed.columns:
        grade_filter = st.selectbox("Grade for monthly view", _GRADE_ORDER, key="monthly_grade")
        monthly_df = closed[closed["grade"] == grade_filter].copy()
        if not monthly_df.empty:
            monthly_df["year"] = monthly_df["timestamp"].dt.year
            monthly_df["month"] = monthly_df["timestamp"].dt.month
            pivot = (
                monthly_df.groupby(["year", "month"])["realized_r"]
                .mean()
                .unstack(level="month")
                .round(3)
            )
            pivot.columns = [
                ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][m - 1]
                for m in pivot.columns
            ]
            st.dataframe(pivot, use_container_width=True)
            st.caption("Values = avg realized R per month. Green months > 0, red < 0.")

    # ── Panel 3d: Equity Curve + Max Drawdown ───────────────────────
    st.subheader("Equity Curve — Cumulative R (closed trades)")
    if not closed.empty and "realized_r" in closed.columns:
        equity_data = {}
        for g in _GRADE_ORDER:
            g_closed = closed[closed["grade"] == g].sort_values("timestamp")
            r = g_closed["realized_r"].dropna()
            if len(r):
                equity_data[g] = r.cumsum().reset_index(drop=True)
        if equity_data:
            st.line_chart(pd.DataFrame(equity_data))
            # Max drawdown table
            dd_rows = []
            for g, eq in equity_data.items():
                peak = eq.cummax()
                max_dd = round((eq - peak).min(), 2)
                dd_rows.append({"Grade": g, "Max Drawdown R": max_dd,
                                "Final R": round(eq.iloc[-1], 2)})
            st.dataframe(pd.DataFrame(dd_rows).set_index("Grade"), use_container_width=True)
            st.caption("Max Drawdown R = worst peak-to-trough in cumulative R. "
                       "Final R = total R earned across all closed trades in filtered set.")

    # ── Panel 3e: Monte Carlo ────────────────────────────────────────
    st.subheader("Monte Carlo — 1,000 Trade-Order Shuffles")
    if not closed.empty and "realized_r" in closed.columns:
        grade_mc = st.selectbox("Grade", _GRADE_ORDER, key="mc_grade")
        mc_r = closed[closed["grade"] == grade_mc]["realized_r"].dropna()
        if len(mc_r) >= 30:
            N_SIMS = 1000
            arr = mc_r.values
            rng = np.random.default_rng(42)
            sims = np.array([rng.permutation(arr).cumsum() for _ in range(N_SIMS)])
            p5  = np.percentile(sims, 5,  axis=0)
            p50 = np.percentile(sims, 50, axis=0)
            p95 = np.percentile(sims, 95, axis=0)
            st.line_chart(pd.DataFrame({"P5 (worst)": p5, "Median": p50, "P95 (best)": p95}))
            st.caption(
                f"1,000 shuffles of {len(mc_r):,} closed {grade_mc} trades. "
                f"All paths end at the same total R (sum is order-invariant). "
                f"The bands show path variance — wide separation = high sensitivity to "
                f"trade clustering. Narrow bands = robust regardless of when trades hit."
            )
        else:
            st.info(f"Need ≥ 30 closed {grade_mc} trades for Monte Carlo (have {len(mc_r)}).")

    # ── Panel 4: Signal log ──────────────────────────────────────────
    st.subheader("Signal Log")

    def _colour_outcome(val):
        if val == "WIN":   return "background-color: #d4edda"
        if val == "LOSS":  return "background-color: #f8d7da"
        return "background-color: #e2e3e5"

    display = filtered.sort_values("timestamp", ascending=False).head(2000).reset_index(drop=True)
    st.caption(f"Showing latest 2,000 of {len(filtered)} signals")
    st.dataframe(
        display.style.map(_colour_outcome, subset=["outcome"]),
        use_container_width=True,
        height=400,
    )


if __name__ == "__main__":
    main()
