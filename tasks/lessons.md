# QMIE — Lessons Learned

Patterns and rules captured from corrections. Reviewed at session start.

---

## Backtest / Runner

### L001 — Rolling window, not growing slice
**Mistake**: Passed `df[:i+1]` to `compute_signal` — O(n²) runtime, 2h+ for 2 symbols.
**Rule**: Always use a fixed-size rolling window (`df.iloc[i-WINDOW+1:i+1]`). WINDOW=400 covers all lookback needs.

### L002 — Binance CSV header row detection
**Mistake**: Newer Binance monthly ZIPs include a header row; older ones don't. Caused `ValueError: could not convert string to float`.
**Rule**: After reading CSV, check `if isinstance(df.iloc[0, 0], str): df = df.iloc[1:].reset_index(drop=True)`.

### L003 — pandas FutureWarning: pd.to_datetime with strings
**Mistake**: `pd.to_datetime(col, unit="ms")` with string values triggers FutureWarning and fails in future pandas.
**Rule**: Always cast first: `col.astype("int64")` before passing to `pd.to_datetime(..., unit="ms")`.

### L004 — Windows CP1251 Unicode encoding
**Mistake**: Used `→` arrow character in print statements; Windows terminal CP1251 can't encode it.
**Rule**: Avoid non-ASCII in print/log output. Use plain ASCII equivalents ("to", "->", etc.).

### L005 — Streamlit Styler cell limit
**Mistake**: Applying `.style.map()` to a 40k+ row DataFrame hits Streamlit's 262,144 cell limit.
**Rule**: Cap displayed rows with `.head(2000)` before applying Styler. Show a caption with total count.

---

## Git / Workflow

### L006 — Task output piped through `tail -30` loses full output
**Mistake**: Used `python -m backtest.run ... | tail -30` in background task — only saw last 30 lines, missed summary.
**Rule**: Don't pipe background tasks through `tail`. Let full output write to the task output file.

---

## Code Quality

### L007 — MAE/MFE forward scan is slow in pure Python
**Context**: Scanning 100 bars forward per signal in a Python loop, 83k signals = ~8M iterations.
**Rule**: If the forward scan becomes a bottleneck, vectorize with numpy (cummax/cummin on sliced arrays). Current runtime ~2h acceptable for offline use but flag if adding more symbols.
