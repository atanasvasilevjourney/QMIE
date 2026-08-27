# QMIE — Deployment runbook

Scanner edition. Alert-only. No broker keys.

## Vercel (desk UI only — not the scanner)

Connecting this GitHub repo to Vercel and deploying **master** as-is produces
`404: NOT_FOUND` with status **Ready**. Vercel built nothing useful: the repo
root is Python + Docker, not a Next.js app, and there was no `index.html` to
serve.

Vercel **cannot** run QMIE. The product is a long-lived FastAPI process
(bar-close scheduler, SQLite, optional Redis, exchange REST). Serverless
functions time out and have no persistent loop. Discord/Telegram alerts do
**not** need Vercel.

Two pieces, two hosts:

| Piece | Where |
|---|---|
| Scanner API (`uvicorn` on `:8080`) | Docker Compose on a VPS, or a **container** host (Fly / Railway / Render). See §2. |
| Desk UI (`web/`) | Optional: Vercel static hosting of the Vite build |

### Why `qmie.vercel.app` is still `404: NOT_FOUND`

Vercel **Production** tracks GitHub **`master`**. That commit has no `web/`
app and no `vercel.json`, so the deploy is Ready with an empty output.
Preview deploys of this branch are SSO-gated; they are not the apex URL.

The live desk is **`https://qmie.onrender.com/`** (browser `Accept: text/html`).
`GET /health` stays JSON.

To make `qmie.vercel.app` itself serve ORBIT:

1. Vercel → Settings → Git → **Production Branch** =
   `cursor/render-backend-a231` (or merge this stack into `master`)
2. Optional: **Root Directory** = `web` (then `web/vercel.json` SPA rewrites
   apply; do not keep `outputDirectory: web/dist` in that mode)
3. Redeploy. Desk on `*.vercel.app` calls `https://qmie.onrender.com`
   unless you set `VITE_QMIE_API`.

`vercel.json` at the repo root uses `framework: null` and builds `web/dist`.
Do not use the Vite preset at the monorepo root — it looks for
`vite.config` next to `vercel.json`, finds none, and ships a 404.

CORS on FastAPI is already `allow_origins=["*"]` for the public scanner
routes. Do not put `WEBHOOK_SECRET` or Discord URLs in Vercel — those belong
in `python/.env` on the scanner host.

## Render (scanner API)

Yes: a **Web Service** with Docker. No: static site, cron, or the free
spin-down plan.

`https://mcp.render.com/mcp` can list deploys and logs after OAuth or
`RENDER_API_KEY`. That URL is a **shadow MCP** (not Runlayer). Prefer a
Runlayer-managed Render server if your org has one.

The image used to bind **8080** only. Render health-checks **`$PORT`**
(often `10000`), so the old `CMD` never passed the probe. `docker/start.sh`
now honors `PORT` (Compose still defaults to 8080).

### Dashboard (existing service)

1. Runtime **Docker**, Dockerfile `docker/Dockerfile`, context **repo root**
   (not `docker/` — `COPY python/` would fail).
2. Start command empty (image `CMD`) **or**
   `uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers`
3. Health check `/health`
4. **1** instance + a disk at `/app/data`
5. Env: `SCAN_DATA_SOURCE=okx`, `WORKERS=1`, `DISCORD_WEBHOOK_URL`,
   `WEBHOOK_SECRET`, optional `REDIS_URL`
6. Redeploy. Then `curl -sS https://<service>.onrender.com/health`
7. Browser: `https://<service>.onrender.com/` (desk). JSON: `curl` `/` still.

### Blueprint

`render.yaml` at the repo root. Connect the repo in Render → Blueprint.
Fill `sync: false` secrets in the dashboard. Plan is `starter` (always-on).

---

## 1. Configure

```bash
cp python/.env.example python/.env
```

Minimum for Discord alerts:

| Variable | Notes |
|---|---|
| `DISCORD_WEBHOOK_URL` | Channel webhook |
| `WEBHOOK_SECRET` | 64 hex chars if you use `POST /webhook` |
| `SCAN_DATA_SOURCE` | `binance` (default) or `bybit` |
| `REDIS_URL` | `redis://redis:6379/0` in Compose — **set this in production** or a restart can re-fire the last bar |

Optional: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, `SCAN_MIN_ALERT_GRADE`, `W_*` (sum ~100), `SIG_MIN_ADX`, `SIG_FUNDING_RATE_THRESHOLD`, `SIG_MAX_SIGNALS_PER_SYMBOL_PER_DAY`.

## 2. Run

```bash
cd docker
docker compose --env-file ../python/.env up -d --build
docker logs -f qmie
```

Health:

```bash
curl -s localhost:8080/health | jq
curl -s localhost:8080/universe | jq
```

The first 1H or 4H close after startup (plus 5s grace) triggers a scan.
`POST /scan/once?timeframe=1h` forces a pass without waiting.

Journal a fill (no broker):

```bash
curl -s -X POST localhost:8080/journal \
  -H 'content-type: application/json' \
  -d '{"signal_id":1,"fill_price":65000,"size":0.01}'
curl -s localhost:8080/journal/stats
```

## 3. Binance geo / egress

- HTTP 451 from fapi → region blocked. Set `SCAN_DATA_SOURCE=bybit`.
- HTTP 403 / DNS failure inside the container → egress. From the container: `curl -fsS https://fapi.binance.com/fapi/v1/ping`.

## 4. Persistence

- SQLite volume: `docker/data` → `/app/data`.
- Redis: used only if `REDIS_URL` is set. Compose starts Redis; the app ignores it until the env var is present.

## 5. Backtest (not in the scanner container)

The Compose memory cap is 512MB. Run the harness on a workstation:

```bash
cd python
pip install -r requirements.txt -r backtest/requirements.txt
python -m backtest.run --symbols BTCUSDT ETHUSDT --tf 1h 4h \
  --start 2024-01-01 --split 2025-01-01 \
  --min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0
streamlit run backtest/app.py
```

Do not run this inside the `qmie` service.

## 6. What success looks like

- `/health` → `status: ok`, `db_ok: true`
- Logs: `Scan pass tf=1h completed` after a bar close
- Discord/Telegram: A/A+ embeds with a TradingView deep-link
- After a container restart, the same bar does **not** re-alert (Redis)

Canonical edge measurement: `docs/backtest-baseline.md` (Sprint 1).
