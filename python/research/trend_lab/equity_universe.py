"""US equity panels for research (survivorship-biased current index members)."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from .data import load_etf
from .protocol import SPLIT

log = logging.getLogger(__name__)
_CACHE = Path(__file__).resolve().parents[1] / "data" / "equity_cache"


def sp500_tickers() -> list[str]:
    """Current S&P 500 symbols (point-in-time membership **not** applied)."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0 (QMIE research)"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    syms = tables[0]["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    return sorted(set(syms))


def _load_one(ticker: str, start: date, end: date) -> tuple[str, pd.Series | None]:
    try:
        s, _ = load_etf(ticker)
        s = s.loc[pd.Timestamp(start, tz="UTC") : pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
        if len(s) < 252:
            return ticker, None
        return ticker, s
    except Exception as exc:
        log.debug("skip %s: %s", ticker, exc)
        return ticker, None


def load_equity_panel(
    tickers: list[str] | None = None,
    *,
    start: date | None = None,
    end: date | None = None,
    max_workers: int = 12,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Daily close panel; drops names with insufficient history."""
    start = start or date(2010, 1, 1)
    end = end or SPLIT.oos_end
    tickers = tickers or sp500_tickers()
    _CACHE.mkdir(parents=True, exist_ok=True)
    cols: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_load_one, t, start, end): t for t in tickers}
        for fut in as_completed(futs):
            t, s = fut.result()
            if s is not None and not s.empty:
                cols[t] = s
                sources[t] = "yahoo/stooq"
    if not cols:
        return pd.DataFrame(), sources
    panel = pd.DataFrame(cols).sort_index().ffill()
    panel = panel.dropna(how="all")
    return panel, sources
