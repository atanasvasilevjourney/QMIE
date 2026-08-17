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

### Cloud gotchas

- **Exchange REST geo-blocks:** Binance Futures (`fapi`) and Bybit public endpoints often return 451/403 from this VM. Scanner/radar live rows may be empty. Historical Vision (`data.binance.vision`) and offline/unit tests still work. Do not treat empty `/radar` as a UI bug when health is `ok`.
- **Secrets:** Discord/Telegram webhooks and `WEBHOOK_SECRET` are optional for desk UI + journal. HMAC webhook posts need a matching secret from `python/.env`.
- **Signal-only:** Never add broker/execution paths. Desk JOURNAL is manual fill logging only.
- **Shadow MCP:** `.cursor/mcp.json` TradingView MCP is not the scanner; do not retune `W_*` from it (`docs/tradingview-mcp.md`).
- **Frozen OOS:** `docs/backtest-baseline.md` is the TMA 9/90/199 walk-forward. Re-run with `python -m backtest.run --start 2024-01-01 --split 2025-01-01 --min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0` (Vision cache, not `fapi`). Do not retune `W_*` on that sample. One-knob proposal: `strategy/reviews/2026-08-17.md` (`SCAN_TIMEFRAMES=4h`, not applied).
