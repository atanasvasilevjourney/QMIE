"""KPIs a hedge-fund risk book actually reads."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .protocol import ANN_DAYS


def max_dd(eq: pd.Series) -> float:
    eq = eq.dropna()
    if eq.empty:
        return float("nan")
    return float((eq / eq.cummax() - 1.0).min())


def cagr(eq: pd.Series) -> float:
    eq = eq.dropna()
    if len(eq) < 2 or eq.iloc[-1] <= 0:
        return float("nan")
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) if yrs > 0 and eq.iloc[0] > 0 else float("nan")


def sharpe(net: pd.Series, *, ann: int = ANN_DAYS) -> float:
    ex = net.dropna()
    sd = ex.std(ddof=1)
    if sd is None or sd == 0 or np.isnan(sd):
        return float("nan")
    return float(ex.mean() / sd * np.sqrt(ann))


def sortino(net: pd.Series, *, ann: int = ANN_DAYS) -> float:
    ex = net.dropna()
    down = ex[ex < 0]
    dd = down.std(ddof=1)
    if dd is None or dd == 0 or np.isnan(dd):
        return float("nan")
    return float(ex.mean() / dd * np.sqrt(ann))


def calmar(eq: pd.Series) -> float:
    dd = abs(max_dd(eq))
    return float("nan") if dd == 0 or np.isnan(dd) else float(cagr(eq) / dd)


def ulcer(eq: pd.Series) -> float:
    eq = eq.dropna()
    if eq.empty:
        return float("nan")
    dd = eq / eq.cummax() - 1.0
    return float(np.sqrt((dd ** 2).mean()))


def rolling_sharpe(net: pd.Series, window: int = 90, *, ann: int = ANN_DAYS) -> pd.Series:
    mu = net.rolling(window).mean()
    sd = net.rolling(window).std(ddof=1)
    return (mu / sd.replace(0, np.nan) * np.sqrt(ann)).rename("roll_sharpe")


def kpis_from_net(net: pd.Series, *, trades: int | None = None) -> dict[str, float]:
    """Rebuild equity from 1.0 so CAGR/DD describe this window only."""
    net = net.fillna(0.0)
    eq = (1.0 + net).cumprod()
    return kpis(net, eq, trades=trades)


def kpis(net: pd.Series, eq: pd.Series, *, trades: int | None = None) -> dict[str, float]:
    return {
        "sharpe": sharpe(net),
        "sortino": sortino(net),
        "cagr": cagr(eq),
        "max_dd": max_dd(eq),
        "calmar": calmar(eq),
        "ulcer": ulcer(eq),
        "vol": float(net.std(ddof=1) * np.sqrt(ANN_DAYS)) if len(net.dropna()) > 2 else float("nan"),
        "trades": float(trades) if trades is not None else float("nan"),
        "bars": float(len(net.dropna())),
    }


def kpi_table(rows: dict[str, dict[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows).T
