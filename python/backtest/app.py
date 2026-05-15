"""
QMIE Backtest Dashboard
========================
Streamlit dashboard for exploring backtest results.

Launch:
    cd python
    streamlit run backtest/app.py
"""
from __future__ import annotations

from pathlib import Path

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
            win_pct = (
                round(100 * (closed_g["outcome"] == "WIN").mean(), 1)
                if len(closed_g) else 0.0
            )
            avg_bars = round(closed_g["bars_to_outcome"].mean(), 1) if len(closed_g) else None
            rows.append({
                "Grade": g,
                "Signals": len(all_g),
                "Closed": len(closed_g),
                "Win %": win_pct,
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
