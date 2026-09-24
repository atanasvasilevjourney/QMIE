"""Matplotlib + Plotly visuals for Top-10 TEMA 4h A/A+ scanner book (research)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from backtest.overlay import summarize

from .tema_prop_universe import (
    TOP10_SYMBOLS,
    SimConfig,
    default_parquet,
    load_oos_book,
    run_paper_sim,
    signal_kpis,
)

ART = Path(__file__).resolve().parents[1] / "artifacts" / "tema_prop" / "plots"
CURSOR = Path("/opt/cursor/artifacts") / "tema_prop_plots"


def _mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _equity_series(sim: dict[str, Any]) -> pd.Series:
    curve = sim.get("curve") or []
    if not curve:
        return pd.Series(dtype=float)
    c = pd.DataFrame(curve)
    c["timestamp"] = pd.to_datetime(c["timestamp"], utc=True)
    c = c.sort_values("timestamp").set_index("timestamp")
    daily = c["equity"].resample("1D").last().ffill()
    return daily


def _daily_r(book: pd.DataFrame) -> pd.Series:
    if book.empty:
        return pd.Series(dtype=float)
    d = book.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d = d.sort_values("timestamp")
    return (
        d.set_index("timestamp")["realized_r"]
        .astype(float)
        .resample("1D")
        .sum()
    )


def symbol_stats(book: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sym, g in book.groupby("symbol"):
        k = summarize(g.to_dict(orient="records"), kept_only=False)
        rows.append(
            {
                "symbol": sym.replace("USDT", ""),
                "n": k["n"],
                "win_pct": k["win_pct"],
                "expectancy_r": k["expectancy_r"],
                "pf": k["pf"],
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("expectancy_r", ascending=True)


def plot_equity_and_drawdown(
    sim: dict[str, Any],
    path: Path,
    *,
    title: str = "Top 10 — paper equity & drawdown (1% stake, max 3 slots)",
) -> Path:
    plt = _mpl()
    eq = _equity_series(sim)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True, height_ratios=[2, 1])
    if eq.empty:
        axes[0].set_title(title + " (no sim curve)")
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    axes[0].plot(eq.index, eq.values, color="#2563eb", linewidth=1.5, label="Equity")
    axes[0].axhline(float(sim.get("start", eq.iloc[0])), color="#94a3b8", linestyle=":", lw=1)
    axes[0].set_ylabel("USD")
    axes[0].set_title(title)
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(loc="upper left", fontsize=8)

    dd = eq - eq.cummax()
    axes[1].fill_between(dd.index, dd.values, 0, color="#dc2626", alpha=0.35)
    axes[1].plot(dd.index, dd.values, color="#b91c1c", linewidth=1)
    axes[1].set_ylabel("Drawdown $")
    axes[1].grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_monthly_r(book: pd.DataFrame, path: Path) -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    daily = _daily_r(book)
    if daily.empty:
        fig, ax = plt.subplots(figsize=(10, 3.5))
        ax.set_title("Monthly cumulative R — Top 10 (no data)")
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    monthly = daily.resample("ME").sum()
    colors = ["#16a34a" if v >= 0 else "#dc2626" for v in monthly.values]
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(monthly.index.strftime("%Y-%m"), monthly.values, color=colors, edgecolor="none")
    ax.axhline(0, color="#64748b", lw=0.8)
    ax.set_title("Top 10 TEMA 4h A/A+ — monthly sum of R (OOS book)")
    ax.set_ylabel("R")
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_monthly_sim_pnl(taken: pd.DataFrame, path: Path) -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 4))
    if taken.empty or "pnl_usd" not in taken.columns:
        ax.set_title("Monthly paper PnL — no taken trades")
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    t = taken.copy()
    t["exit_ts"] = pd.to_datetime(t["exit_ts"], utc=True)
    g = t.groupby(t["exit_ts"].dt.to_period("M"))["pnl_usd"].sum()
    idx = [str(p) for p in g.index]
    colors = ["#16a34a" if v >= 0 else "#dc2626" for v in g.values]
    ax.bar(idx, g.values, color=colors)
    ax.axhline(0, color="#64748b", lw=0.8)
    ax.set_title("Top 10 — monthly paper PnL (sim fills only)")
    ax.set_ylabel("USD")
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_symbol_expectancy(book: pd.DataFrame, path: Path) -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = symbol_stats(book)
    fig, ax = plt.subplots(figsize=(9, 5))
    if stats.empty:
        ax.set_title("Per-symbol E[R] — empty")
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    colors = ["#16a34a" if (x or 0) >= 0 else "#dc2626" for x in stats["expectancy_r"]]
    ax.barh(stats["symbol"], stats["expectancy_r"], color=colors)
    ax.axvline(0, color="#64748b", lw=0.8)
    ax.set_xlabel("Expectancy (R)")
    ax.set_title("Top 10 — per-symbol E[R] (A/A+ OOS book)")
    for yi, (_, row) in enumerate(stats.iterrows()):
        ax.text(
            float(row["expectancy_r"]),
            yi,
            f"  n={int(row['n'])}  {row['win_pct']}%",
            va="center",
            fontsize=7,
            color="#334155",
        )
    ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_win_rate_by_symbol(book: pd.DataFrame, path: Path) -> Path:
    plt = _mpl()
    stats = symbol_stats(book)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5))
    if stats.empty:
        ax.set_title("Win rate by symbol — empty")
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    stats = stats.sort_values("win_pct", ascending=True)
    ax.barh(stats["symbol"], stats["win_pct"], color="#6366f1")
    ax.axvline(50, color="#94a3b8", linestyle="--", lw=1, label="50%")
    ax.set_xlabel("Win %")
    ax.set_title("Top 10 — win rate by symbol")
    ax.legend(fontsize=8)
    ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_grade_mix(book: pd.DataFrame, path: Path) -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    if book.empty:
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    grades = book["grade"].value_counts().reindex(["A+", "A"]).fillna(0)
    axes[0].pie(
        grades.values,
        labels=grades.index,
        autopct="%1.1f%%",
        colors=["#7c3aed", "#2563eb"],
        startangle=90,
    )
    axes[0].set_title("Grade mix")

    b = book.copy()
    b["month"] = pd.to_datetime(b["timestamp"], utc=True).dt.to_period("M").astype(str)
    pivot = b.groupby(["month", "grade"]).size().unstack(fill_value=0)
    for g in ("A+", "A"):
        if g not in pivot.columns:
            pivot[g] = 0
    pivot[["A+", "A"]].plot(kind="bar", stacked=True, ax=axes[1], color=["#7c3aed", "#2563eb"])
    axes[1].set_title("Signals per month")
    axes[1].tick_params(axis="x", rotation=45, labelsize=7)
    axes[1].set_ylabel("Count")
    fig.suptitle("Top 10 TEMA scanner — A vs A+")
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_score_vs_r(book: pd.DataFrame, path: Path) -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    if book.empty:
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    win = book["outcome"].str.upper() == "WIN"
    ax.scatter(
        book.loc[win, "score"],
        book.loc[win, "realized_r"],
        c="#16a34a",
        alpha=0.45,
        s=18,
        label="WIN",
    )
    ax.scatter(
        book.loc[~win, "score"],
        book.loc[~win, "realized_r"],
        c="#dc2626",
        alpha=0.45,
        s=18,
        label="LOSS",
    )
    ax.axhline(0, color="#64748b", lw=0.8)
    ax.set_xlabel("QMIE score")
    ax.set_ylabel("Realized R")
    ax.set_title("Top 10 — score vs outcome (OOS A/A+)")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_cumulative_r(book: pd.DataFrame, path: Path) -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    if book.empty:
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    d = book.sort_values("timestamp").copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    cum = d["realized_r"].astype(float).cumsum()
    ax.plot(d["timestamp"], cum.values, color="#0f766e", lw=1.6)
    ax.fill_between(d["timestamp"], cum.values, 0, alpha=0.12, color="#0f766e")
    ax.axhline(0, color="#64748b", lw=0.8)
    ax.set_ylabel("Cumulative R")
    ax.set_title("Top 10 — cumulative R (signal order, not sim slots)")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_signal_calendar(book: pd.DataFrame, path: Path) -> Path:
    """Weekly heatmap of daily R sums."""
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    daily = _daily_r(book)
    fig, ax = plt.subplots(figsize=(11, 3.8))
    if len(daily) < 2:
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    df = daily.to_frame("r")
    df["week"] = df.index.isocalendar().week.astype(int)
    df["dow"] = df.index.dayofweek
    pivot = df.pivot_table(index="dow", columns="week", values="r", aggfunc="sum")
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn", vmin=-3, vmax=3)
    ax.set_yticks(range(7))
    ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], fontsize=8)
    ax.set_xlabel("ISO week")
    ax.set_title("Top 10 — daily R heatmap (week × weekday)")
    fig.colorbar(im, ax=ax, label="R", shrink=0.85)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_symbol_timeline(book: pd.DataFrame, path: Path, *, max_points: int = 800) -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 5))
    if book.empty:
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path
    d = book.sort_values("timestamp").copy()
    if len(d) > max_points:
        d = d.iloc[:: max(1, len(d) // max_points)]
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    syms = sorted(d["symbol"].unique())
    ymap = {s: i for i, s in enumerate(syms)}
    y = d["symbol"].map(ymap)
    win = d["outcome"].str.upper() == "WIN"
    ax.scatter(
        d.loc[win, "timestamp"],
        y[win],
        c="#16a34a",
        s=12 + d.loc[win, "score"].fillna(0) * 0.05,
        alpha=0.7,
        label="WIN",
    )
    ax.scatter(
        d.loc[~win, "timestamp"],
        y[~win],
        c="#dc2626",
        s=12 + d.loc[~win, "score"].fillna(0) * 0.05,
        alpha=0.7,
        label="LOSS",
    )
    ax.set_yticks(range(len(syms)))
    ax.set_yticklabels([s.replace("USDT", "") for s in syms], fontsize=8)
    ax.set_title("Top 10 — signal timeline (size ∝ score)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plotly_dashboard_html(
    book: pd.DataFrame,
    sim: dict[str, Any],
    path: Path,
    *,
    kpi: Optional[dict[str, Any]] = None,
) -> Optional[Path]:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    eq = _equity_series(sim)
    daily_r = _daily_r(book)
    stats = symbol_stats(book)

    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Paper equity (daily)",
            "Cumulative R (all signals)",
            "Per-symbol E[R]",
            "Monthly R sum",
        ),
        vertical_spacing=0.12,
        horizontal_spacing=0.08,
    )
    if not eq.empty:
        fig.add_trace(
            go.Scatter(x=eq.index, y=eq.values, mode="lines", name="Equity", line=dict(color="#2563eb")),
            row=1,
            col=1,
        )
    if not book.empty:
        d = book.sort_values("timestamp")
        ts = pd.to_datetime(d["timestamp"], utc=True)
        fig.add_trace(
            go.Scatter(
                x=ts,
                y=d["realized_r"].astype(float).cumsum(),
                mode="lines",
                name="Cum R",
                line=dict(color="#0f766e"),
            ),
            row=1,
            col=2,
        )
    if not stats.empty:
        fig.add_trace(
            go.Bar(x=stats["expectancy_r"], y=stats["symbol"], orientation="h", name="E[R]"),
            row=2,
            col=1,
        )
    if not daily_r.empty:
        m = daily_r.resample("ME").sum()
        fig.add_trace(
            go.Bar(x=m.index.astype(str), y=m.values, name="Monthly R"),
            row=2,
            col=2,
        )
    title = "Top 10 TEMA 4h A/A+ scanner"
    if kpi:
        title += (
            f" — n={kpi.get('n')} win={kpi.get('win_pct')}% "
            f"E[R]={kpi.get('expectancy_r')} PF={kpi.get('pf')}"
        )
    fig.update_layout(title=title, height=720, template="plotly_white", showlegend=False)
    fig.write_html(str(path), include_plotlyjs="cdn")
    return path


def render_top10_plots(
    parquet: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    *,
    sim: SimConfig | None = None,
    also_cursor: bool = True,
) -> dict[str, str]:
    """Write PNG/HTML artifacts; returns path map."""
    parquet = parquet or default_parquet()
    out_dir = out_dir or ART
    sim = sim or SimConfig()
    book = load_oos_book(parquet, TOP10_SYMBOLS)
    sim_out, _stake = run_paper_sim(book, sim)
    taken = sim_out.get("taken_rows")
    if not isinstance(taken, pd.DataFrame):
        taken = pd.DataFrame()

    kpi = signal_kpis(book)
    paths = {
        "equity_dd": str(plot_equity_and_drawdown(sim_out, out_dir / "01_equity_drawdown.png")),
        "monthly_r": str(plot_monthly_r(book, out_dir / "02_monthly_r.png")),
        "monthly_pnl": str(plot_monthly_sim_pnl(taken, out_dir / "03_monthly_sim_pnl.png")),
        "symbol_er": str(plot_symbol_expectancy(book, out_dir / "04_symbol_expectancy.png")),
        "symbol_win": str(plot_win_rate_by_symbol(book, out_dir / "05_symbol_win_rate.png")),
        "grade_mix": str(plot_grade_mix(book, out_dir / "06_grade_mix.png")),
        "score_r": str(plot_score_vs_r(book, out_dir / "07_score_vs_r.png")),
        "cum_r": str(plot_cumulative_r(book, out_dir / "08_cumulative_r.png")),
        "calendar": str(plot_signal_calendar(book, out_dir / "09_daily_r_heatmap.png")),
        "timeline": str(plot_symbol_timeline(book, out_dir / "10_signal_timeline.png")),
    }
    html = plotly_dashboard_html(book, sim_out, out_dir / "dashboard.html", kpi=kpi)
    if html:
        paths["dashboard_html"] = str(html)
    if also_cursor:
        cursor_dir = CURSOR
        cursor_dir.mkdir(parents=True, exist_ok=True)
        render_top10_plots(parquet, cursor_dir, sim=sim, also_cursor=False)
    return paths
