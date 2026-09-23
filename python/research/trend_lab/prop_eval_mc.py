"""Monte Carlo FTMO-style eval attempts — EV per day vs risk scale (research only).

Uses block bootstrap of daily net returns. Does not create edge; scales it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EvalRules:
    profit_target_pct: float = 0.10
    max_loss_pct: float = 0.10  # static from initial balance
    daily_loss_pct: float = 0.05
    start_capital: float = 100_000.0
    max_calendar_days: int = 365 * 2  # cap attempt length


@dataclass(frozen=True)
class EvalEconomics:
    eval_cost_usd: float = 500.0
    expected_payout_usd: float = 8_000.0  # cumulative before breach (user prior)


@dataclass(frozen=True)
class McParams:
    n_sims: int = 2_000
    block_len: int = 10
    seed: int = 42


def _block_bootstrap(r: np.ndarray, n_days: int, block: int, rng: np.random.Generator) -> np.ndarray:
    if len(r) == 0:
        return np.zeros(n_days)
    out = []
    while len(out) < n_days:
        start = int(rng.integers(0, max(1, len(r) - block + 1)))
        chunk = r[start : start + block]
        out.extend(chunk.tolist())
    return np.array(out[:n_days], dtype=float)


def simulate_one_attempt(
    daily_net: np.ndarray,
    *,
    risk_scale: float,
    rules: EvalRules,
) -> tuple[str, int]:
    """Return (``pass`` | ``fail``, days_used)."""
    cap = rules.start_capital
    initial = cap
    target = initial * (1.0 + rules.profit_target_pct)
    floor_static = initial * (1.0 - rules.max_loss_pct)
    scaled = daily_net * risk_scale
    for i, ret in enumerate(scaled[: rules.max_calendar_days], start=1):
        day_start = cap
        cap *= 1.0 + float(ret)
        if cap <= floor_static:
            return "fail", i
        if cap < day_start * (1.0 - rules.daily_loss_pct):
            return "fail", i
        if cap >= target:
            return "pass", i
    return "fail", rules.max_calendar_days


def run_mc_grid(
    net: pd.Series,
    risk_grid: np.ndarray,
    *,
    rules: EvalRules | None = None,
    econ: EvalEconomics | None = None,
    mc: McParams | None = None,
    sample_from: str = "is",
    is_end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Grid ``risk_scale``; report pass rate, median days, EV per day."""
    rules = rules or EvalRules()
    econ = econ or EvalEconomics()
    mc = mc or McParams()
    net = net.fillna(0.0)
    if sample_from == "is" and is_end is not None:
        sample = net.loc[:is_end].to_numpy(dtype=float)
    else:
        sample = net.to_numpy(dtype=float)
    if len(sample) < mc.block_len * 3:
        raise ValueError("too few returns for bootstrap")

    rng = np.random.default_rng(mc.seed)
    rows = []
    for rs in risk_grid:
        outcomes: list[tuple[str, int]] = []
        for _ in range(mc.n_sims):
            path = _block_bootstrap(sample, rules.max_calendar_days, mc.block_len, rng)
            outcomes.append(simulate_one_attempt(path, risk_scale=float(rs), rules=rules))
        passes = [t for o, t in outcomes if o == "pass"]
        fails = [t for o, t in outcomes if o == "fail"]
        p = len(passes) / mc.n_sims
        t_med = float(np.median(passes)) if passes else float(np.median(fails))
        t_med = max(t_med, 1.0)
        ev_attempt = p * econ.expected_payout_usd - econ.eval_cost_usd
        ev_day = ev_attempt / t_med
        rows.append({
            "risk_scale": float(rs),
            "pass_rate": p,
            "median_days_pass": float(np.median(passes)) if passes else np.nan,
            "median_days_fail": float(np.median(fails)) if fails else np.nan,
            "median_days_resolve": t_med,
            "ev_per_attempt_usd": ev_attempt,
            "ev_per_day_usd": ev_day,
        })
    df = pd.DataFrame(rows)
    best = df.loc[df["ev_per_day_usd"].idxmax()]
    df["best_ev_day"] = df["risk_scale"] == best["risk_scale"]
    return df


def sensitivity_ok(df: pd.DataFrame, *, tol_frac: float = 0.15) -> bool:
    """Neighboring scales within ``tol_frac`` of peak EV/day (anti-overfit check)."""
    if df.empty:
        return False
    peak = df["ev_per_day_usd"].max()
    if peak <= 0:
        return False
    best_rs = float(df.loc[df["ev_per_day_usd"].idxmax(), "risk_scale"])
    neighbors = df[df["risk_scale"].between(best_rs * 0.85, best_rs * 1.15)]
    if len(neighbors) < 2:
        return True
    return bool((neighbors["ev_per_day_usd"] >= peak * (1.0 - tol_frac)).sum() >= 2)
