"""IS-only Optuna, coarse grid, DF neighborhood, Boruta-lite.

Never pass OOS into ``objective``. DF neighborhood uses an inner
validation slice carved from IS (last 20%), never the true holdout.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from .metrics import kpis
from .protocol import WARMUP_BARS
from .spot_system import SpotParams, spot_signal
from .tema_system import TemaParams, n_liquidations, tema_bar_equity, tema_trades

try:
    import optuna
    from optuna.samplers import TPESampler

    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:  # pragma: no cover
    optuna = None  # type: ignore
    TPESampler = None  # type: ignore


def _after_warmup(frame: pd.DataFrame) -> pd.DataFrame:
    if len(frame) <= WARMUP_BARS:
        return frame.iloc[0:0]
    return frame.iloc[WARMUP_BARS:]


def kpis_spot(fr: pd.DataFrame) -> dict[str, float]:
    ev = _after_warmup(fr)
    if ev.empty:
        return kpis(pd.Series(dtype=float), pd.Series(dtype=float), trades=0)
    n_in = int((ev["signal"].diff().fillna(ev["signal"]) > 0).sum())
    return kpis(ev["net"], ev["equity"], trades=n_in)


def kpis_tema(index: pd.DatetimeIndex, trades: pd.DataFrame) -> dict[str, float]:
    bar = tema_bar_equity(index, trades)
    return {
        **kpis(bar["net"], bar["equity"], trades=int(len(trades))),
        "liquidations": float(n_liquidations(trades)),
        "win_rate": float((trades["pnl"] > 0).mean()) if len(trades) else float("nan"),
        "expectancy_usdt": float(trades["pnl"].mean()) if len(trades) else float("nan"),
    }


# ---------------------------------------------------------------------------
# DF neighborhood (KAMA notebook method, inner-IS only)
# ---------------------------------------------------------------------------


def neighbor_set(center: dict[str, float], steps: dict[str, list[float]]) -> list[dict[str, float]]:
    """Cartesian neighborhood around ``center`` (center included)."""
    from itertools import product

    keys = list(steps)
    grids = []
    for k in keys:
        vals = sorted(set(list(steps[k]) + [center[k]]))
        grids.append(vals)
    out = []
    for combo in product(*grids):
        d = dict(center)
        for k, v in zip(keys, combo):
            d[k] = v
        out.append(d)
    return out


def df_neighborhood_score(
    *,
    is_ohlcv: pd.DataFrame,
    inner_val_start: pd.Timestamp,
    center: dict[str, float],
    neighbor_steps: dict[str, list[float]],
    run_fn: Callable[[pd.DataFrame, dict[str, float]], pd.DataFrame],
    min_is_sharpe: float = 1.0,
) -> dict[str, Any]:
    """Among neighbors with IS-train Sharpe > threshold, pick lowest val Sharpe std.

    ``run_fn(ohlcv, params) -> frame with net, equity``. Must not look at OOS.
    Train = IS before inner_val_start; val = remainder of IS.
    """
    train = is_ohlcv.loc[: inner_val_start - pd.Timedelta(seconds=1)]
    val = is_ohlcv.loc[inner_val_start:]
    neighbors = neighbor_set(center, neighbor_steps)
    rows = []
    for p in neighbors:
        eq_tr = run_fn(train, p)
        eq_va = run_fn(val, p)
        k_tr = kpis(eq_tr["net"], eq_tr["equity"])
        k_va = kpis(eq_va["net"], eq_va["equity"])
        rows.append({**p, "sharpe_train": k_tr["sharpe"], "sharpe_val": k_va["sharpe"]})
    table = pd.DataFrame(rows)
    pool = table[table["sharpe_train"] >= min_is_sharpe]
    if pool.empty:
        return {
            "status": "no_stable_pool",
            "n_neighbors": int(len(table)),
            "val_sharpe_std": float("nan"),
            "table": table,
        }
    std = float(pool["sharpe_val"].std(ddof=1)) if len(pool) > 1 else 0.0
    # DF pick: lowest val-std neighborhood (the pool itself); report best val Sharpe inside it
    best = pool.loc[pool["sharpe_val"].idxmax()]
    return {
        "status": "ok",
        "n_neighbors": int(len(table)),
        "n_stable": int(len(pool)),
        "val_sharpe_std": std,
        "best_params": {k: best[k] for k in center},
        "best_val_sharpe": float(best["sharpe_val"]),
        "table": table,
    }


def _spot_frame(ohlcv: pd.DataFrame, p: SpotParams) -> pd.DataFrame:
    return spot_signal(ohlcv, p)


def _random_spot_search(is_ohlcv: pd.DataFrame, n_trials: int, seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    best_p, best_v, best_k = None, -1e9, {}
    for _ in range(n_trials):
        ef = int(rng.integers(8, 35))
        es = int(rng.integers(max(ef + 5, 50), 201))
        p = SpotParams(
            ema_fast=ef,
            ema_slow=es,
            donchian=int(rng.integers(10, 41)),
            min_adx=float(rng.uniform(12, 28)),
            rsi_max=float(rng.uniform(62, 85)),
            use_kama=bool(rng.integers(0, 2)),
            use_macd=bool(rng.integers(0, 2)),
            use_zscore=bool(rng.integers(0, 2)),
            use_alma=bool(rng.integers(0, 2)),
        )
        k = kpis_spot(_spot_frame(is_ohlcv, p))
        v = -10.0 if (k["bars"] < 80 or not np.isfinite(k["sharpe"])) else float(k["sharpe"])
        if k.get("trades", 0) < 4:
            v -= 1.0
        if v > best_v:
            best_p, best_v, best_k = p, v, k
    return {"params": best_p, "is_kpis": best_k, "best_value": best_v, "n_trials": n_trials, "engine": "random"}


def optimize_spot(
    is_ohlcv: pd.DataFrame,
    *,
    n_trials: int = 28,
    seed: int = 42,
) -> dict[str, Any]:
    if optuna is None:
        return _random_spot_search(is_ohlcv, n_trials, seed)

    def objective(trial: optuna.Trial) -> float:
        p = SpotParams(
            ema_fast=trial.suggest_int("ema_fast", 8, 34),
            ema_slow=trial.suggest_int("ema_slow", 50, 200),
            donchian=trial.suggest_int("donchian", 10, 40),
            min_adx=trial.suggest_float("min_adx", 12.0, 28.0),
            rsi_max=trial.suggest_float("rsi_max", 62.0, 85.0),
            use_kama=trial.suggest_categorical("use_kama", [False, True]),
            use_macd=trial.suggest_categorical("use_macd", [False, True]),
            use_zscore=trial.suggest_categorical("use_zscore", [False, True]),
            use_alma=trial.suggest_categorical("use_alma", [False, True]),
        )
        if p.ema_fast >= p.ema_slow:
            return -10.0
        k = kpis_spot(_spot_frame(is_ohlcv, p))
        if k["bars"] < 80 or not np.isfinite(k["sharpe"]):
            return -10.0
        if k["trades"] < 4:
            return float(k["sharpe"]) - 1.0
        return float(k["sharpe"])

    sampler = TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    bp = study.best_params
    best = SpotParams(
        ema_fast=int(bp["ema_fast"]),
        ema_slow=int(bp["ema_slow"]),
        donchian=int(bp["donchian"]),
        min_adx=float(bp["min_adx"]),
        rsi_max=float(bp["rsi_max"]),
        use_kama=bool(bp["use_kama"]),
        use_macd=bool(bp["use_macd"]),
        use_zscore=bool(bp["use_zscore"]),
        use_alma=bool(bp["use_alma"]),
    )
    return {
        "params": best,
        "is_kpis": kpis_spot(_spot_frame(is_ohlcv, best)),
        "best_value": float(study.best_value),
        "n_trials": n_trials,
        "engine": "optuna",
    }


def grid_spot(is_ohlcv: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ef in (9, 21):
        for es in (50, 90, 199):
            if ef >= es:
                continue
            for dn in (20, 55):
                for adx in (15.0, 20.0):
                    p = SpotParams(ema_fast=ef, ema_slow=es, donchian=dn, min_adx=adx)
                    k = kpis_spot(_spot_frame(is_ohlcv, p))
                    rows.append({"ema_fast": ef, "ema_slow": es, "donchian": dn, "min_adx": adx, **k})
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False)


def _tema_kpis_on(ohlcv: pd.DataFrame, p: TemaParams) -> dict[str, float]:
    warmup_cut = ohlcv.index[min(WARMUP_BARS, len(ohlcv) - 1)]
    trades = tema_trades(ohlcv, p)
    if not trades.empty:
        trades = trades.loc[trades["entry_time"] >= warmup_cut]
    return kpis_tema(ohlcv.index, trades)


def _random_tema_search(is_ohlcv: pd.DataFrame, n_trials: int, seed: int, leverage: float) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    best_p, best_v, best_k = None, -1e9, {}
    for _ in range(n_trials):
        fast = int(rng.integers(5, 22))
        mid = int(rng.integers(max(fast + 8, 34), 121))
        slow = int(rng.integers(max(mid + 20, 150), 251))
        sl = float(rng.uniform(1.0, 2.5))
        tp = float(rng.uniform(max(sl + 0.2, 1.5), 4.0))
        p = TemaParams(
            fast=fast, mid=mid, slow=slow,
            min_adx=float(rng.uniform(12, 28)),
            min_atr_pct=float(rng.uniform(0.2, 0.8)),
            max_atr_pct=float(rng.uniform(2.5, 6.0)),
            sl_atr=sl, tp_atr=tp, leverage=leverage,
        )
        k = _tema_kpis_on(is_ohlcv, p)
        if k["bars"] < 200 or not np.isfinite(k["sharpe"]):
            v = -10.0
        else:
            cal = float(k["calmar"] if np.isfinite(k["calmar"]) else 0.0)
            v = float(k["sharpe"]) + 0.15 * cal
        if v > best_v:
            best_p, best_v, best_k = p, v, k
    frozen = TemaParams(leverage=leverage)
    return {
        "params": best_p,
        "is_kpis": best_k,
        "frozen_9_90_199_is": _tema_kpis_on(is_ohlcv, frozen),
        "best_value": best_v,
        "n_trials": n_trials,
        "do_not_promote": True,
        "engine": "random",
    }


def optimize_tema(
    is_ohlcv: pd.DataFrame,
    *,
    n_trials: int = 24,
    seed: int = 7,
    leverage: float = 10.0,
) -> dict[str, Any]:
    if optuna is None:
        return _random_tema_search(is_ohlcv, n_trials, seed, leverage)

    def objective(trial: optuna.Trial) -> float:
        p = TemaParams(
            fast=trial.suggest_int("fast", 5, 21),
            mid=trial.suggest_int("mid", 34, 120),
            slow=trial.suggest_int("slow", 150, 250),
            min_adx=trial.suggest_float("min_adx", 12.0, 28.0),
            min_atr_pct=trial.suggest_float("min_atr_pct", 0.2, 0.8),
            max_atr_pct=trial.suggest_float("max_atr_pct", 2.5, 6.0),
            sl_atr=trial.suggest_float("sl_atr", 1.0, 2.5),
            tp_atr=trial.suggest_float("tp_atr", 1.5, 4.0),
            leverage=leverage,
        )
        if not (p.fast < p.mid < p.slow):
            return -10.0
        if p.tp_atr <= p.sl_atr:
            return -10.0
        k = _tema_kpis_on(is_ohlcv, p)
        if k["bars"] < 200 or not np.isfinite(k["sharpe"]):
            return -10.0
        return float(k["sharpe"]) + 0.15 * float(k["calmar"] if np.isfinite(k["calmar"]) else 0.0)

    sampler = TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    bp = study.best_params
    best = TemaParams(
        fast=int(bp["fast"]),
        mid=int(bp["mid"]),
        slow=int(bp["slow"]),
        min_adx=float(bp["min_adx"]),
        min_atr_pct=float(bp["min_atr_pct"]),
        max_atr_pct=float(bp["max_atr_pct"]),
        sl_atr=float(bp["sl_atr"]),
        tp_atr=float(bp["tp_atr"]),
        leverage=leverage,
    )
    frozen = TemaParams(leverage=leverage)
    return {
        "params": best,
        "is_kpis": _tema_kpis_on(is_ohlcv, best),
        "frozen_9_90_199_is": _tema_kpis_on(is_ohlcv, frozen),
        "best_value": float(study.best_value),
        "n_trials": n_trials,
        "do_not_promote": True,
        "engine": "optuna",
    }


def grid_tema(is_ohlcv: pd.DataFrame, leverage: float = 10.0) -> pd.DataFrame:
    rows = []
    for fast, mid, slow in ((9, 90, 199), (8, 55, 200), (13, 55, 200)):
        for sl, tp in ((1.5, 2.5), (1.2, 2.0)):
            p = TemaParams(fast=fast, mid=mid, slow=slow, sl_atr=sl, tp_atr=tp, leverage=leverage)
            k = _tema_kpis_on(is_ohlcv, p)
            rows.append({"fast": fast, "mid": mid, "slow": slow, "sl_atr": sl, "tp_atr": tp, **k})
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False)


# ---------------------------------------------------------------------------
# Boruta-lite (shadow-feature RF, IS labels only)
# ---------------------------------------------------------------------------


def boruta_select(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    n_estimators: int = 120,
    n_iter: int = 12,
    alpha: float = 0.05,
    random_state: int = 0,
) -> pd.DataFrame:
    """Shadow-feature selection. Returns per-feature hit rate vs max shadow.

    A feature is **confirmed** if it beat the max shadow in ≥ (1-alpha)
    of iterations. Tentative if hit_rate ≥ 0.5. Rejected otherwise.
    """
    mask = y.notna() & X.notna().all(axis=1)
    Xv = X.loc[mask].astype(float)
    yv = y.loc[mask].astype(int)
    if len(Xv) < 80 or yv.nunique() < 2:
        return pd.DataFrame(
            {"feature": list(X.columns), "hit_rate": np.nan, "decision": "insufficient_data"}
        )

    rng = np.random.default_rng(random_state)
    hits = {c: 0 for c in Xv.columns}
    try:
        from sklearn.ensemble import RandomForestClassifier as _RF
    except ImportError:
        _RF = None  # type: ignore

    def _importance(frame: pd.DataFrame, iter_i: int) -> pd.Series:
        if _RF is not None:
            rf = _RF(
                n_estimators=n_estimators,
                max_depth=5,
                min_samples_leaf=20,
                random_state=random_state + iter_i,
                n_jobs=1,
            )
            rf.fit(frame, yv)
            return pd.Series(rf.feature_importances_, index=frame.columns)
        y_arr = yv.to_numpy(dtype=float)
        out = {}
        for col in frame.columns:
            x = frame[col].to_numpy(dtype=float)
            if np.std(x) < 1e-12 or np.std(y_arr) < 1e-12:
                out[col] = 0.0
            else:
                out[col] = abs(float(np.corrcoef(x, y_arr)[0, 1]))
        return pd.Series(out)

    for i in range(n_iter):
        shadow = Xv.copy()
        for c in shadow.columns:
            shadow[c] = rng.permutation(shadow[c].to_numpy())
        shadow.columns = [f"shadow__{c}" for c in Xv.columns]
        xs = pd.concat([Xv, shadow], axis=1)
        imp = _importance(xs, i)
        max_shadow = float(imp.filter(like="shadow__").max())
        for c in Xv.columns:
            if float(imp[c]) > max_shadow:
                hits[c] += 1
    rows = []
    thresh = 1.0 - alpha
    for c, h in hits.items():
        rate = h / n_iter
        if rate >= thresh:
            dec = "confirmed"
        elif rate >= 0.5:
            dec = "tentative"
        else:
            dec = "rejected"
        rows.append({"feature": c, "hits": h, "hit_rate": rate, "decision": dec})
    return pd.DataFrame(rows).sort_values(["hit_rate", "feature"], ascending=[False, True])


def trend_label(close: pd.Series, horizon: int = 10) -> pd.Series:
    """Binary: next-horizon return > 0. Label at t uses close[t+h]/close[t] — drop tail."""
    fwd = close.shift(-horizon) / close - 1.0
    return (fwd > 0).astype(float).where(fwd.notna())
