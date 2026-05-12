# HTF Daily Trend Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `daily_trend` field (bullish/bearish/unknown) to every QMIE scan result, computed from EMA200 on 1D klines, and display it as an informational label in Discord and Telegram alerts.

**Architecture:** `compute_signal()` receives an optional `daily_df` (1D candles), computes EMA200 on it, and stores the result in `ScanResult.daily_trend`. The scheduler supplies `daily_df` by reusing the already-fetched `htf_df` when HTF is 1D (4H scans), or fetching 1D klines separately for 1H scans. The dispatcher injects `daily_trend` into the TVSignal dict (same pattern as `chart_url`) and the notifiers display it.

**Tech Stack:** Python 3.12, pandas, pytest, aiohttp (no new dependencies)

---

## File Map

| File | Change |
|---|---|
| `python/scanner/signal_engine.py` | Add `daily_trend` to `ScanResult`; add `daily_df` param to `compute_signal()` |
| `python/scanner/scheduler.py` | Determine and pass `daily_df` in `scan_one()` |
| `python/scanner/dispatcher.py` | Inject `daily_trend` into `sig_dict` before `model_validate` |
| `python/notifiers/discord.py` | Add "Daily Trend" embed field in `_build_embed()` |
| `python/notifiers/telegram.py` | Add "Daily Trend" line in `_format()` |
| `python/tests/test_signal_engine.py` | Add 4 tests for `daily_trend` computation |

---

## Task 1: Add `daily_trend` to `ScanResult` and compute it in `signal_engine.py`

**Files:**
- Modify: `python/scanner/signal_engine.py`
- Test: `python/tests/test_signal_engine.py`

- [ ] **Step 1: Write the four failing tests**

Open `python/tests/test_signal_engine.py` and add this block at the end of the file (after the last existing test class):

```python
# ─── Daily trend tests ───────────────────────────────────────────────────

def _make_daily_df(n: int = 250, close: float = 100.0) -> pd.DataFrame:
    """Synthetic daily OHLCV with uniform close."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1D")
    return pd.DataFrame(
        {"open": close, "high": close * 1.001, "low": close * 0.999,
         "close": close, "volume": 1_000_000.0},
        index=idx,
    )


class TestDailyTrend:
    def test_bullish_when_close_above_ema200(self, bull_trend_df):
        """Last daily close well above EMA200 → daily_trend == 'bullish'."""
        daily = _make_daily_df(250, close=100.0)
        # Bump only the last bar: EMA200 ≈ 100, last close = 200 → bullish
        daily.iloc[-1, daily.columns.get_loc("close")] = 200.0
        result = compute_signal(
            bull_trend_df, symbol="BTCUSDT", timeframe="1h", daily_df=daily
        )
        assert result is not None
        assert result.daily_trend == "bullish"

    def test_bearish_when_close_below_ema200(self, bull_trend_df):
        """Last daily close well below EMA200 → daily_trend == 'bearish'."""
        daily = _make_daily_df(250, close=100.0)
        # Drop only the last bar: EMA200 ≈ 100, last close = 50 → bearish
        daily.iloc[-1, daily.columns.get_loc("close")] = 50.0
        result = compute_signal(
            bull_trend_df, symbol="BTCUSDT", timeframe="1h", daily_df=daily
        )
        assert result is not None
        assert result.daily_trend == "bearish"

    def test_unknown_when_no_daily_df(self, bull_trend_df):
        """daily_df=None → daily_trend == 'unknown'."""
        result = compute_signal(
            bull_trend_df, symbol="BTCUSDT", timeframe="1h", daily_df=None
        )
        assert result is not None
        assert result.daily_trend == "unknown"

    def test_unknown_when_insufficient_daily_data(self, bull_trend_df):
        """daily_df with < 200 rows → daily_trend == 'unknown' (EMA can't seed)."""
        daily = _make_daily_df(150, close=100.0)
        result = compute_signal(
            bull_trend_df, symbol="BTCUSDT", timeframe="1h", daily_df=daily
        )
        assert result is not None
        assert result.daily_trend == "unknown"
```

> `bull_trend_df` is the existing session-scoped fixture in `tests/conftest.py` — a 400-bar uptrend OHLCV DataFrame, well above the 220-bar minimum for `compute_signal`. `compute_signal` is already imported at the top of this test file.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd python
pytest tests/test_signal_engine.py::TestDailyTrend -v
```

Expected: 4 failures — `TypeError: compute_signal() got an unexpected keyword argument 'daily_df'`

- [ ] **Step 3: Add `daily_trend` field to `ScanResult`**

In `python/scanner/signal_engine.py`, the `ScanResult` dataclass ends with:
```python
    components:    dict = field(default_factory=dict)  # per-module raw votes
    reason:        str = ""
```

Add `daily_trend` immediately after `reason`:
```python
    components:    dict = field(default_factory=dict)  # per-module raw votes
    reason:        str = ""
    daily_trend:   str = "unknown"     # "bullish" / "bearish" / "unknown"
```

- [ ] **Step 4: Add `daily_df` parameter to `compute_signal()`**

The current signature (line ~105):
```python
def compute_signal(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    htf_df: Optional[pd.DataFrame] = None,
    weights: Weights = Weights(),
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.5,
) -> Optional[ScanResult]:
```

Add `daily_df` after `htf_df`:
```python
def compute_signal(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    htf_df: Optional[pd.DataFrame] = None,
    daily_df: Optional[pd.DataFrame] = None,
    weights: Weights = Weights(),
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.5,
) -> Optional[ScanResult]:
```

- [ ] **Step 5: Compute `daily_trend` before the `return ScanResult(...)`**

The function currently ends with SL/TP computation then `return ScanResult(...)`.
Insert this block between SL/TP and the return:

```python
    # ─── Daily trend (EMA200 on 1D) ──────────────────────────────────────
    daily_trend = "unknown"
    if daily_df is not None and len(daily_df) >= 200:
        d_ema200 = ema(daily_df["close"], 200)
        d_e200_last = float(d_ema200.iloc[-1])
        d_close_last = float(daily_df["close"].iloc[-1])
        if not pd.isna(d_e200_last):
            if d_close_last > d_e200_last:
                daily_trend = "bullish"
            elif d_close_last < d_e200_last:
                daily_trend = "bearish"
```

- [ ] **Step 6: Pass `daily_trend` into the `ScanResult` constructor**

The `return ScanResult(...)` call currently ends with:
```python
        reason=_explain(side, st_d, ema_d, rsi_d, adx_d, htf_d, sr_d),
    )
```

Add `daily_trend` as the last argument:
```python
        reason=_explain(side, st_d, ema_d, rsi_d, adx_d, htf_d, sr_d),
        daily_trend=daily_trend,
    )
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd python
pytest tests/test_signal_engine.py::TestDailyTrend -v
```

Expected: 4 PASSED

- [ ] **Step 8: Run the full test suite to check for regressions**

```bash
cd python
pytest -v
```

Expected: all 109 existing tests still pass + 4 new = 113 PASSED

- [ ] **Step 9: Commit**

```bash
cd python/..
git add python/scanner/signal_engine.py python/tests/test_signal_engine.py
git commit -m "feat: add daily_trend field to ScanResult via EMA200 on 1D klines"
```

---

## Task 2: Supply `daily_df` from the scheduler

**Files:**
- Modify: `python/scanner/scheduler.py`
- Test: `python/tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Open `python/tests/test_scheduler.py` and add this test at the end of the file:

```python
class TestDailyDfRouting:
    """Verify that scan_one passes the correct daily_df to compute_signal."""

    @pytest.mark.asyncio
    async def test_4h_scan_reuses_htf_as_daily_df(self, monkeypatch):
        """For a 4H scan (HTF=1d), daily_df must equal htf_df — no extra fetch."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import pandas as pd

        captured: dict = {}

        def fake_compute(df, *, symbol, timeframe, htf_df=None, daily_df=None, **kw):
            captured["daily_df"] = daily_df
            captured["htf_df"] = htf_df
            return None  # skip full scoring

        fake_df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=pd.date_range("2024-01-01", periods=300, freq="1h"),
        )
        fake_daily = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=pd.date_range("2024-01-01", periods=300, freq="1D"),
        )

        async def fake_fetch(sym, tf, limit=300):
            if tf == "4h":
                return fake_df
            if tf == "1d":
                return fake_daily
            return fake_df

        client = AsyncMock()
        client.fetch_klines = fake_fetch

        from scanner.dispatcher import SignalDispatcher
        from scanner.symbol_universe import SymbolUniverse
        from scanner.scheduler import ScannerScheduler

        universe = MagicMock()
        universe.get = AsyncMock(return_value=["BTCUSDT"])
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=False)

        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["4h"],
            htf_map={"4h": "1d"},
        )

        with patch("scanner.scheduler.compute_signal", side_effect=fake_compute):
            await scheduler._scan_pass("4h")

        # For 4H, htf="1d" so daily_df should be the same object as htf_df
        assert captured.get("daily_df") is captured.get("htf_df")

    @pytest.mark.asyncio
    async def test_1h_scan_fetches_daily_separately(self, monkeypatch):
        """For a 1H scan (HTF=4h), daily_df is a separate fetch of '1d'."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import pandas as pd

        captured: dict = {}
        fetched_tfs: list = []

        def fake_compute(df, *, symbol, timeframe, htf_df=None, daily_df=None, **kw):
            captured["daily_df"] = daily_df
            captured["htf_df"] = htf_df
            return None

        fake_df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=pd.date_range("2024-01-01", periods=300, freq="1h"),
        )

        async def fake_fetch(sym, tf, limit=300):
            fetched_tfs.append(tf)
            return fake_df

        client = AsyncMock()
        client.fetch_klines = fake_fetch

        from scanner.symbol_universe import SymbolUniverse
        from scanner.scheduler import ScannerScheduler

        universe = MagicMock()
        universe.get = AsyncMock(return_value=["BTCUSDT"])
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=False)

        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
        )

        with patch("scanner.scheduler.compute_signal", side_effect=fake_compute):
            await scheduler._scan_pass("1h")

        assert "1d" in fetched_tfs, "Expected a separate 1d fetch for 1H scan"
        assert captured.get("daily_df") is not None
        assert captured.get("daily_df") is not captured.get("htf_df")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd python
pytest tests/test_scheduler.py::TestDailyDfRouting -v
```

Expected: 2 failures — scheduler does not yet pass `daily_df`

- [ ] **Step 3: Update `scan_one` in `scheduler.py`**

In `python/scanner/scheduler.py`, find the `scan_one` inner function inside `_scan_pass`. The current body is:

```python
        async def scan_one(sym: str) -> None:
            async with self.sem:
                try:
                    df = await self.client.fetch_klines(sym, tf, limit=300)
                    if df is None or len(df) < 220:
                        return
                    htf_df = None
                    if htf:
                        try:
                            htf_df = await self.client.fetch_klines(sym, htf, limit=300)
                        except Exception:
                            htf_df = None
                    res = compute_signal(
                        df, symbol=sym, timeframe=tf,
                        htf_df=htf_df, weights=self.weights,
                    )
```

Replace it with:

```python
        async def scan_one(sym: str) -> None:
            async with self.sem:
                try:
                    df = await self.client.fetch_klines(sym, tf, limit=300)
                    if df is None or len(df) < 220:
                        return
                    htf_df = None
                    if htf:
                        try:
                            htf_df = await self.client.fetch_klines(sym, htf, limit=300)
                        except Exception:
                            htf_df = None
                    # Daily trend filter: supply 1D klines to compute_signal.
                    # If HTF is already "1d" (4H scans), reuse htf_df — no extra call.
                    # Otherwise fetch "1d" separately (e.g. for 1H scans where HTF=4H).
                    daily_df = None
                    if htf == "1d":
                        daily_df = htf_df
                    elif htf is not None:
                        try:
                            daily_df = await self.client.fetch_klines(sym, "1d", limit=250)
                        except Exception:
                            daily_df = None
                    res = compute_signal(
                        df, symbol=sym, timeframe=tf,
                        htf_df=htf_df, daily_df=daily_df, weights=self.weights,
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd python
pytest tests/test_scheduler.py::TestDailyDfRouting -v
```

Expected: 2 PASSED

- [ ] **Step 5: Run the full suite**

```bash
cd python
pytest -v
```

Expected: 115 PASSED, 0 failed

- [ ] **Step 6: Commit**

```bash
cd python/..
git add python/scanner/scheduler.py python/tests/test_scheduler.py
git commit -m "feat: supply daily_df to compute_signal in scheduler"
```

---

## Task 3: Inject `daily_trend` in the dispatcher

**Files:**
- Modify: `python/scanner/dispatcher.py`
- Test: `python/tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Open `python/tests/test_dispatcher.py` and add at the end:

```python
class TestDailyTrendPropagation:
    @pytest.mark.asyncio
    async def test_daily_trend_included_in_notifier_signal(self):
        """dispatcher must pass daily_trend through to the TVSignal sent to notifiers."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import pandas as pd
        from scanner.signal_engine import ScanResult
        from scanner.dispatcher import SignalDispatcher
        from security import IdempotencyStore
        from models import Grade

        received: list = []

        class _CapturingNotifier:
            enabled = True
            async def send_signal(self, sig, broker_resp=None):
                received.append(sig)

        idem = IdempotencyStore()
        db = MagicMock()
        db.insert_signal = AsyncMock()

        dispatcher = SignalDispatcher(
            db=db,
            notifiers=[_CapturingNotifier()],
            idem=idem,
            min_alert_grade=Grade.A,
        )

        result = ScanResult(
            symbol="BTCUSDT",
            timeframe="1h",
            timestamp=pd.Timestamp("2026-01-01 12:00:00", tz="UTC"),
            side="BUY",
            grade="A",
            score=85.0,
            price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            atr_value=1.5,
            atr_pct=1.5,
            rsi_value=55.0,
            adx_value=30.0,
            htf_aligned=True,
            nearest_res=2.0,
            nearest_sup=1.5,
            daily_trend="bullish",
        )

        await dispatcher.dispatch(result)

        assert len(received) == 1
        sig = received[0]
        assert getattr(sig, "daily_trend", None) == "bullish"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd python
pytest tests/test_dispatcher.py::TestDailyTrendPropagation -v
```

Expected: FAIL — `daily_trend` not present on the TVSignal

- [ ] **Step 3: Add the injection in `dispatcher.py`**

In `python/scanner/dispatcher.py`, find the block that builds `sig_dict`:

```python
        chart_url = tv_chart_url(result.symbol, result.timeframe, self.tv_prefix)
        # Stash deep link inside metadata for notifiers that want it.
        # TVSignal has extra="allow" so we can attach freely.
        sig_dict = sig.model_dump()
        sig_dict["chart_url"] = chart_url
```

Add `daily_trend` injection on the line after `chart_url`:

```python
        chart_url = tv_chart_url(result.symbol, result.timeframe, self.tv_prefix)
        sig_dict = sig.model_dump()
        sig_dict["chart_url"] = chart_url
        sig_dict["daily_trend"] = result.daily_trend
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd python
pytest tests/test_dispatcher.py::TestDailyTrendPropagation -v
```

Expected: PASSED

- [ ] **Step 5: Run the full suite**

```bash
cd python
pytest -v
```

Expected: 116 PASSED, 0 failed

- [ ] **Step 6: Commit**

```bash
cd python/..
git add python/scanner/dispatcher.py python/tests/test_dispatcher.py
git commit -m "feat: propagate daily_trend through dispatcher to notifiers"
```

---

## Task 4: Display `daily_trend` in the Discord embed

**Files:**
- Modify: `python/notifiers/discord.py`

- [ ] **Step 1: Locate the HTF field block in `_build_embed`**

In `python/notifiers/discord.py`, inside `_build_embed`, find this block (around line 126):

```python
        # HTF
        if sig.htf:
            fields.append({"name": "HTF", "value": sig.htf.title(), "inline": True})
```

- [ ] **Step 2: Add the `Daily Trend` field immediately after the HTF block**

```python
        # HTF
        if sig.htf:
            fields.append({"name": "HTF", "value": sig.htf.title(), "inline": True})

        # Daily trend (EMA200 1D filter)
        daily_trend = getattr(sig, "daily_trend", None)
        if daily_trend:
            fields.append({
                "name": "Daily Trend",
                "value": daily_trend.title(),
                "inline": True,
            })
```

- [ ] **Step 3: Run the full test suite**

```bash
cd python
pytest -v
```

Expected: 116 PASSED (Discord notifier has no unit tests for embed fields, but no regressions)

- [ ] **Step 4: Commit**

```bash
cd python/..
git add python/notifiers/discord.py
git commit -m "feat: show Daily Trend field in Discord embed"
```

---

## Task 5: Display `daily_trend` in the Telegram message

**Files:**
- Modify: `python/notifiers/telegram.py`

- [ ] **Step 1: Locate the HTF line in `_format`**

In `python/notifiers/telegram.py`, inside `_format`, find this block (around line 92):

```python
        if sig.htf:
            lines.append(kv("HTF", sig.htf))
```

- [ ] **Step 2: Add the `Daily Trend` line immediately after**

```python
        if sig.htf:
            lines.append(kv("HTF", sig.htf))
        daily_trend = getattr(sig, "daily_trend", None)
        if daily_trend:
            lines.append(kv("Daily Trend", daily_trend.title()))
```

- [ ] **Step 3: Run the full test suite**

```bash
cd python
pytest -v
```

Expected: 116 PASSED

- [ ] **Step 4: Commit**

```bash
cd python/..
git add python/notifiers/telegram.py
git commit -m "feat: show Daily Trend in Telegram alert message"
```

---

## Task 6: Final verification

- [ ] **Step 1: Run the full test suite one last time**

```bash
cd python
pytest -v --tb=short
```

Expected output (abbreviated):
```
tests/test_config.py          10 passed
tests/test_dispatcher.py      13 passed   (+1 new)
tests/test_exchange_clients.py 13 passed
tests/test_indicators.py      24 passed
tests/test_scheduler.py       15 passed   (+2 new)
tests/test_security.py        12 passed
tests/test_signal_engine.py   25 passed   (+4 new)
============= 116 passed in ~2s =============
```

- [ ] **Step 2: Verify coverage on changed modules**

```bash
cd python
pytest --cov=scanner/signal_engine --cov=scanner/scheduler --cov=scanner/dispatcher --cov-report=term-missing
```

Expected: `signal_engine` stays ≥ 90%, `scheduler` stays ≥ 61%, `dispatcher` stays ≥ 94%

- [ ] **Step 3: Commit and tag**

```bash
cd python/..
git add .
git commit -m "feat: HTF daily trend filter complete — daily_trend label in all alerts"
```
