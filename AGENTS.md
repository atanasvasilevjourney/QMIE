# AGENTS.md

Project conventions for humans and cloud agents. Core product notes live in `CLAUDE.md` and `docs/`.

## Cursor Cloud specific instructions

### Services

| Service | How to run | Notes |
|---|---|---|
| QMIE API | `cd python && /workspace/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080` | Health: `GET /health`. SQLite under `python/data/` (gitignored). |
| QMIE Desk UI | `cd web && npm run dev` | Vite on `:5173`. Proxies `/qmie` → `http://127.0.0.1:8080`. |

Do not put service startup in the environment update script — start them in the session (tmux is fine).

### Lint / test / build

- Python: `cd python && /workspace/.venv/bin/pytest -v` (see `CLAUDE.md`). Coverage optional.
- Desk UI: `cd web && npm run lint` and `npm run build`.
- Standard Docker path remains `docker/` + root README.
- Multi-agent briefing: `GET /agents/briefing` or `cd python && python -m improve.agents` (read-only; GO/WATCH/SKIP is not an order).
- Analysis overlay: `GET /agents/analysis/{id}` (on-demand Take + ATR levels). Empty `OPENAI_API_KEY` uses the template. Briefing must not call OpenAI.
- Hedge-fund DAG analog: `GET /agents/desk` (start→data→strategy→risk→portfolio). `quantity` is always 0. Not LangGraph. Not a broker.

### Cloud gotchas

- **Exchange REST geo-blocks:** Binance Futures (`fapi`) and Bybit public endpoints often return 451/403 from this VM. `SCAN_DATA_SOURCE=okx` (OKX USDT-margined swaps) is reachable here — session env only unless the operator confirms `.env`. Historical Vision (`data.binance.vision`) still works for backtests. Yahoo/Kraken/CoinGecko last prices are **not** the scanner. Do not treat empty `/radar` as a UI bug when health is `ok`.
- **Desk `Sync: Failed to fetch` / `desk API unreachable`:** the browser never reached FastAPI. Open `http://127.0.0.1:5173` (Vite `/qmie` → `:8080`). The UI now also retries `http://127.0.0.1:8080` (CORS). Empty radar / Binance 451 is a **different** problem — see `docs/streaming-data-sources.md`. Do **not** add Hyperliquid trading APIs.
- **Secrets:** Discord/Telegram webhooks and `WEBHOOK_SECRET` are optional for desk UI + journal. HMAC webhook posts need a matching secret from `python/.env`.
- **Signal-only:** Never add broker/execution paths. Desk JOURNAL is manual fill logging only.
- **Shadow MCP:** `.cursor/mcp.json` TradingView MCP is not the scanner; do not retune `W_*` from it (`docs/tradingview-mcp.md`).
- **Frozen OOS:** `docs/backtest-baseline.md` is the TMA 9/90/199 walk-forward. Re-run with `python -m backtest.run --start 2024-01-01 --split 2025-01-01 --min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0` (Vision cache, not `fapi`). Do not retune `W_*` on that sample. One-knob proposal: `strategy/reviews/2026-08-17.md` (`SCAN_TIMEFRAMES=4h`, not applied).
