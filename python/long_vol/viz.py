"""Matplotlib visuals for long-vol event study and notebook export."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def save_horizon_means(events: pd.DataFrame, path: Path, *, title: str = "Mean forward return by horizon") -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [c for c in events.columns if c.startswith("ret_") and c.endswith("_pct")]
    if not cols or events.empty:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.text(0.5, 0.5, "No events in window", ha="center", va="center")
        ax.set_title(title)
        fig.savefig(path, dpi=140)
        plt.close(fig)
        return path
    cols = sorted(cols, key=lambda x: int(x.split("_")[1].replace("h", "")))
    means = [events[c].mean() for c in cols]
    labels = [c.replace("ret_", "").replace("_pct", "") for c in cols]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    colors = ["#3498db" if m >= 0 else "#e74c3c" for m in means]
    ax.bar(labels, means, color=colors, edgecolor="black", linewidth=0.5)
    ax.axhline(0, color="gray", linestyle=":", linewidth=1)
    ax.set_ylabel("Mean net return (%)")
    ax.set_xlabel("Hold from next open")
    ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def save_return_hist(events: pd.DataFrame, path: Path, col: str = "ret_24h_pct", *, title: str | None = None) -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    if events.empty or col not in events.columns:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.text(0.5, 0.5, "No events in window", ha="center", va="center")
        ax.set_title(title or col)
        fig.savefig(path, dpi=140)
        plt.close(fig)
        return path
    s = events[col].dropna()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(s, bins=40, color="#2ecc71", edgecolor="white", alpha=0.85)
    ax.axvline(0, color="gray", linestyle="--")
    ax.axvline(s.mean(), color="#c0392b", linestyle="-", label=f"mean={s.mean():.2f}%")
    ax.legend()
    ax.set_xlabel(col)
    ax.set_ylabel("Count")
    ax.set_title(title or f"Distribution of {col}")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def save_gate_funnel(attribution: pd.DataFrame, path: Path, *, title: str = "Gate pass counts (raw triggers)") -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    if attribution.empty:
        return path
    df = attribution[attribution["gate"] != "raw_triggers"].copy()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(df["gate"], df["pass_count"], color="#9b59b6", edgecolor="black", linewidth=0.4)
    ax.set_xlabel("Triggers passing gate")
    ax.set_title(title)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def save_bucket_bars(summary: pd.DataFrame, path: Path, *, title: str = "24h return by dist_atr bucket") -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    if summary.empty:
        return path
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(len(summary))
    ax.bar(x, summary["mean"], color="#1abc9c", edgecolor="black", linewidth=0.4)
    ax.set_xticks(x)
    ax.set_xticklabels([str(b) for b in summary["bucket"]], rotation=25, ha="right", fontsize=8)
    ax.axhline(0, color="gray", linestyle=":")
    ax.set_ylabel("Mean ret_24h_pct")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def save_equity_curve(
    events: pd.DataFrame,
    path: Path,
    *,
    ret_col: str = "r_24h",
    filtered: bool = True,
    title: str = "Synthetic equity (non-overlapping 24h holds)",
) -> Path:
    """Cumulative product of sequential filtered event returns (research only)."""
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    df = events.sort_values("timestamp")
    if filtered and "all_gates" in df.columns:
        df = df[df["all_gates"]]
    r = df[ret_col].dropna()
    if r.empty:
        return path
    # Non-overlapping: skip events within 96 bars (~24h) of prior
    kept = []
    last_ts = None
    for _, row in df.iterrows():
        ts = row["timestamp"]
        if last_ts is not None and (ts - last_ts) < pd.Timedelta(hours=20):
            continue
        if pd.isna(row.get(ret_col)):
            continue
        kept.append(float(row[ret_col]))
        last_ts = ts
    if not kept:
        return path
    eq = (1.0 + pd.Series(kept)).cumprod()
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(eq.values, color="#2980b9", linewidth=1.6)
    ax.set_title(title)
    ax.set_ylabel("Growth of $1")
    ax.set_xlabel("Trade #")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def save_feature_scatter(events: pd.DataFrame, path: Path, x: str = "dist_atr", y: str = "ret_24h_pct") -> Path:
    plt = _mpl()
    path.parent.mkdir(parents=True, exist_ok=True)
    s = events.dropna(subset=[x, y])
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(s[x], s[y], alpha=0.45, s=18, c=s["rvol"] if "rvol" in s.columns else "#34495e")
    ax.axhline(0, color="gray", linestyle=":")
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.set_title(f"{y} vs {x} (color ~ rvol if present)")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path
