"""Load USDT-M Vision klines. Same archive as ``python -m backtest.run``."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from backtest.data_loader import load_klines, load_tf_ohlcv

from .protocol import SPLIT

CORE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT", "LINKUSDT"]
SATELLITES = ["SOLUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT"]  # later listings
DEFAULT_UNIVERSE = CORE + SATELLITES


def load_symbol(
    symbol: str,
    tf: str,
    *,
    start: date | None = None,
    end: date | None = None,
    cache_dir: Path | None = None,
) -> tuple[pd.DataFrame, str]:
    start = start or SPLIT.is_start
    end = end or SPLIT.oos_end
    kw: dict = {}
    if cache_dir is not None:
        kw["cache_dir"] = cache_dir
    df, src = load_tf_ohlcv(symbol, tf, start, end, **kw)
    return df, src


def load_panel(
    symbols: Iterable[str],
    tf: str = "1d",
    *,
    start: date | None = None,
    end: date | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Close panel, columns = symbols. Sources recorded per name."""
    closes: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    for sym in symbols:
        df, src = load_symbol(sym, tf, start=start, end=end)
        sources[sym] = src
        if df.empty:
            continue
        closes[sym] = df["close"].rename(sym)
    if not closes:
        return pd.DataFrame(), sources
    panel = pd.concat(closes.values(), axis=1).sort_index()
    return panel, sources


def coverage_table(symbols: Iterable[str], timeframes: Iterable[str] = ("1d", "4h")) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        for tf in timeframes:
            df, src = load_symbol(sym, tf)
            rows.append({
                "symbol": sym,
                "tf": tf,
                "source": src,
                "bars": int(len(df)),
                "start": None if df.empty else str(df.index[0].date()),
                "end": None if df.empty else str(df.index[-1].date()),
            })
    return pd.DataFrame(rows)


_ETF_CACHE = Path(__file__).resolve().parents[2] / "backtest" / "data" / "cache" / "etf"
_STOOQ = {
    "QQQ": "qqq.us",
    "GLD": "gld.us",
    "SPY": "spy.us",
}


def _normalize_close_index(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    out = s.copy()
    out.index = idx.normalize()
    return out[~out.index.duplicated(keep="last")].sort_index().astype(float)


def _stooq_daily(stooq_sym: str) -> pd.Series:
    from io import StringIO

    last_err = None
    for base in ("https://stooq.com/q/d/l/", "https://stooq.pl/q/d/l/"):
        try:
            resp = requests.get(base, params={"s": stooq_sym, "i": "d"}, timeout=30)
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text))
            if df.empty or "Close" not in df.columns:
                continue
            df["Date"] = pd.to_datetime(df["Date"], utc=True)
            return df.set_index("Date")["Close"].rename("close")
        except Exception as exc:
            last_err = exc
            continue
    raise RuntimeError(f"stooq failed for {stooq_sym}: {last_err}")


def _yahoo_daily(ticker: str) -> pd.Series:
    """Yahoo chart API. ``range=max`` downsamples to monthly — use period1/period2 + 1d."""
    import time

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "period1": 946684800,  # 2000-01-01 UTC
        "period2": int(time.time()),
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()["chart"]["result"][0]
    ts = pd.to_datetime(payload["timestamp"], unit="s", utc=True)
    quote = payload["indicators"]["quote"][0]
    adj = (payload["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    close = adj if adj is not None else quote["close"]
    s = pd.Series(close, index=ts, name="close").dropna()
    if len(s) < 400:
        raise ValueError(f"{ticker} yahoo daily too short ({len(s)} bars) — likely monthly downsample")
    return s


def load_etf(ticker: str, *, cache_dir: Path | None = None) -> tuple[pd.Series, str]:
    """Daily close for QQQ/GLD. Cached parquet. Stooq first, Yahoo fallback."""
    ticker = ticker.upper()
    cache_dir = cache_dir or _ETF_CACHE
    path = cache_dir / f"{ticker}.parquet"
    if path.exists():
        s = pd.read_parquet(path).iloc[:, 0]
        s = _normalize_close_index(s).rename(ticker)
        # reject monthly accident (≤ ~40 bars/year)
        span_years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-6)
        if len(s) / span_years >= 150:
            return s, f"cache:{path.name}"
    src = "stooq"
    try:
        raw = _stooq_daily(_STOOQ.get(ticker, f"{ticker.lower()}.us"))
        if raw.dropna().empty:
            raise ValueError("empty stooq")
    except Exception:
        src = "yahoo"
        raw = _yahoo_daily(ticker)
    s = _normalize_close_index(raw).rename(ticker).dropna()
    cache_dir.mkdir(parents=True, exist_ok=True)
    s.to_frame("close").to_parquet(path)
    return s, src


def mixed_panel(
    *,
    btc_symbol: str = "BTCUSDT",
    etfs: tuple[str, ...] = ("QQQ", "GLD"),
    start: date | None = None,
    end: date | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """BTC (Vision 1d) + ETFs on the US session calendar (ETF index).

    BTC is marked at the last UTC daily close on or before each ETF date.
    That is a few hours off NY 16:00 — documented, not interpolated.
    """
    start = start or SPLIT.is_start
    end = end or SPLIT.oos_end
    sources: dict[str, str] = {}
    btc_df, btc_src = load_symbol(btc_symbol, "1d", start=start, end=end)
    sources["BTC"] = btc_src
    btc = _normalize_close_index(btc_df["close"]).rename("BTC") if not btc_df.empty else pd.Series(dtype=float, name="BTC")
    frames = {"BTC": btc}
    session: pd.DatetimeIndex | None = None
    for t in etfs:
        s, src = load_etf(t)
        sources[t] = src
        s = s.loc[pd.Timestamp(start, tz="UTC"): pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
        frames[t] = s.rename(t)
        session = s.index if session is None else session.union(s.index)
    if session is None or session.empty:
        return pd.DataFrame(), sources
    session = session.sort_values()
    aligned = {}
    for name, s in frames.items():
        aligned[name] = s.reindex(session).ffill()
    panel = pd.DataFrame(aligned).sort_index()
    panel = panel.loc[pd.Timestamp(start, tz="UTC"):]
    panel = panel.dropna(how="any")
    return panel, sources
