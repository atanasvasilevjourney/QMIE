# AGENTS.md

QMIE is a server-side, crypto-only market scanner (FastAPI). It scans USDT-perp
symbols on closed 1H/4H bars, scores them with a 7-component weighted engine, and
dispatches A/A+ alerts to Discord/Telegram. It does not execute trades. See
`README.md` and `CLAUDE.md` for product detail, math invariants, and conventions.

## Cursor Cloud specific instructions

Python 3.12 project. Dependencies are installed into a virtualenv at `/workspace/.venv`
by the environment update script (runtime deps from `python/requirements.txt` plus the
test-only `requests`, `pyarrow`, `pytest`, `pytest-asyncio`, `pytest-cov`). Always use
the venv interpreter (`/workspace/.venv/bin/python`, `/workspace/.venv/bin/pytest`).

- Local dev env file: `python/.env` (gitignored) is created during setup from
  `python/.env.example` with notifiers disabled and a known `WEBHOOK_SECRET` so the
  HMAC `/webhook` path can be exercised locally. If it is missing on a fresh VM,
  recreate it from `python/.env.example`.

- Run tests (from `python/`, matching CI in `.github/workflows/tests.yml`):
  `WEBHOOK_SECRET=ci-test-secret DISCORD_ENABLED=false TELEGRAM_ENABLED=false /workspace/.venv/bin/python -m pytest`
  Tests are fully offline (mocked HTTP, synthetic fixtures) — 214 tests.

- Do NOT install `python/backtest/requirements.txt` alongside runtime deps: it pins
  `streamlit`/`numpy<2` which conflicts with runtime `numpy==2.1.2`. The backtest unit
  tests only need `requests` + `pyarrow` (already installed). Run the Streamlit backtest
  dashboard in a separate venv if you need it.

- No linter/formatter is configured (no ruff/flake8/black/pre-commit). "Lint" is a
  byte-compile check: `/workspace/.venv/bin/python -m compileall python`.

- Run the app in dev mode (from `python/`):
  `/workspace/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8080`
  (`python main.py` also works; it reads HOST/PORT/WORKERS from `.env`). Then
  `curl localhost:8080/health`. Swagger UI is at `/docs`. The Docker path in the README
  (`docker compose ... up`) is the production stack — for local dev prefer uvicorn.

- IMPORTANT NETWORK CAVEAT: the live scanner's market data comes from
  `fapi.binance.com` (Binance USDT-M Futures) and `api.bybit.com` (Bybit). Both are
  GEO-BLOCKED from the Cloud VM's region (Binance returns HTTP 451, Bybit returns
  CloudFront 403). Egress is otherwise unrestricted — this is a regional block, not a
  firewall/allowlist issue, and switching `SCAN_DATA_SOURCE` between binance/bybit does
  not help. The scanner boots fine (static `/universe` needs no network), a scan pass
  completes and logs per-symbol 451/403 warnings without crashing, but it produces zero
  live signals in this environment. To exercise the full signal path without live
  klines, POST a signal to the HMAC-protected `/webhook` (sign the raw body with
  `WEBHOOK_SECRET` using HMAC-SHA256, header `X-QMIE-Signature`); it persists to SQLite
  and is then readable via `/signals` and journalable via `/journal`.

- Journal `realized_r`/`outcome` (WIN/LOSS) only compute when the underlying signal has
  a `stop_loss`; without one the fill stays `OPEN` with `realized_r=null`. This is
  expected behavior, not a bug.

- SQLite lives at `python/data/qmie.db` (relative to the run cwd). It is gitignored;
  delete it to reset journal/signal state.
