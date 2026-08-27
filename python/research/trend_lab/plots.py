"""Plotly + matplotlib helpers. HTML for notebooks, PNG for artifacts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .metrics import rolling_sharpe


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def equity_overlay(series: dict[str, pd.Series], title: str):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    fig = go.Figure()
    for name, s in series.items():
        s = s.dropna()
        if s.empty:
            continue
        norm = s / s.iloc[0]
        fig.add_trace(go.Scatter(x=norm.index, y=norm.values, name=name, mode="lines"))
    fig.update_layout(title=title, yaxis_title="Growth of $1", template="plotly_white", height=420)
    return fig


def rolling_sharpe_fig(nets: dict[str, pd.Series], window: int = 90, title: str = "Rolling Sharpe"):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    fig = go.Figure()
    for name, net in nets.items():
        rs = rolling_sharpe(net, window=window).dropna()
        if rs.empty:
            continue
        fig.add_trace(go.Scatter(x=rs.index, y=rs.values, name=name, mode="lines"))
    fig.add_hline(y=0, line_dash="dot", line_color="gray")
    fig.update_layout(title=title, yaxis_title=f"{window}d Sharpe", template="plotly_white", height=380)
    return fig


def underwater(eq: pd.Series, title: str = "Drawdown"):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    dd = eq / eq.cummax() - 1.0
    fig = go.Figure(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy", name="DD", line=dict(color="#c0392b")))
    fig.update_layout(title=title, yaxis_title="Drawdown", yaxis_tickformat=".0%", template="plotly_white", height=320)
    return fig


def param_heatmap(table: pd.DataFrame, x: str, y: str, z: str, title: str):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    pivot = table.pivot_table(index=y, columns=x, values=z, aggfunc="mean")
    fig = go.Figure(
        data=go.Heatmap(z=pivot.values, x=list(pivot.columns), y=list(pivot.index), colorbar=dict(title=z))
    )
    fig.update_layout(title=title, xaxis_title=x, yaxis_title=y, template="plotly_white", height=400)
    return fig


def df_scatter(table: pd.DataFrame, title: str = "DF neighborhood"):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    fig = go.Figure(
        go.Scatter(
            x=table["sharpe_train"],
            y=table["sharpe_val"],
            mode="markers",
            marker=dict(size=9, opacity=0.75),
            text=table.astype(str).agg(" | ".join, axis=1) if len(table) else None,
        )
    )
    fig.add_hline(y=1.0, line_dash="dot", line_color="gray")
    fig.add_vline(x=1.0, line_dash="dot", line_color="gray")
    fig.update_layout(title=title, xaxis_title="IS-train Sharpe", yaxis_title="Inner-val Sharpe", template="plotly_white")
    return fig


def allocation_fig(weights: dict[str, pd.Series], title: str = "Allocation"):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    fig = go.Figure()
    for name, w in weights.items():
        fig.add_trace(go.Scatter(x=w.index, y=w.values, name=name, mode="lines"))
    fig.update_layout(title=title, yaxis_title="Weight", yaxis_range=[-0.05, 1.05], template="plotly_white", height=380)
    return fig


def price_signals(
    ohlcv: pd.DataFrame,
    *,
    signal: pd.Series | None = None,
    entries: pd.DatetimeIndex | None = None,
    exits: pd.DatetimeIndex | None = None,
    sl: pd.Series | None = None,
    tp: pd.Series | None = None,
    overlays: dict[str, pd.Series] | None = None,
    title: str = "Signals",
    max_bars: int = 800,
):
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return None

    df = ohlcv.iloc[-max_bars:]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.03)
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="OHLC",
        ),
        row=1, col=1,
    )
    if overlays:
        for name, s in overlays.items():
            ss = s.reindex(df.index)
            fig.add_trace(go.Scatter(x=df.index, y=ss.values, name=name, mode="lines"), row=1, col=1)
    if signal is not None:
        held = signal.reindex(df.index).fillna(0)
        fig.add_trace(go.Scatter(x=df.index, y=held.values, name="held", mode="lines"), row=2, col=1)
    if entries is not None and len(entries):
        e = ohlcv.reindex(entries)["close"].dropna()
        fig.add_trace(
            go.Scatter(x=e.index, y=e.values, mode="markers", name="entry", marker=dict(symbol="triangle-up", size=10, color="#27ae60")),
            row=1, col=1,
        )
    if exits is not None and len(exits):
        x = ohlcv.reindex(exits)["close"].dropna()
        fig.add_trace(
            go.Scatter(x=x.index, y=x.values, mode="markers", name="exit", marker=dict(symbol="triangle-down", size=10, color="#c0392b")),
            row=1, col=1,
        )
    fig.update_layout(title=title, template="plotly_white", height=640, xaxis_rangeslider_visible=False)
    return fig


def write_html(fig: Any, path: Path) -> Path:
    if fig is None:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(path), include_plotlyjs="cdn")
    return path


def write_png_mpl(
    series: dict[str, pd.Series],
    path: Path,
    *,
    title: str,
    ylabel: str = "",
    hline: float | None = None,
) -> Path | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for name, s in series.items():
        ss = s.dropna()
        if ss.empty:
            continue
        ax.plot(ss.index, ss.values, label=name, linewidth=1.4)
    if hline is not None:
        ax.axhline(hline, color="gray", linestyle=":", linewidth=1)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
