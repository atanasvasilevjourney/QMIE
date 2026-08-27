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

### Make `qmie.vercel.app` show the desk (fix the 404)

After this repo’s `vercel.json` is on the branch Vercel deploys:

1. Vercel project → **Deployments** → **Redeploy** the latest commit (or push).
2. Visit `https://qmie.vercel.app`. You should see **ORBIT**, not `NOT_FOUND`.
3. **Sync will fail** until the scanner is on a public HTTPS origin.

Without waiting for a git merge, you can also set this in the Vercel dashboard
and redeploy:

- **Settings → General → Root Directory** = `web`
- Framework = Vite
- Build = `npm run build`
- Output = `dist`

### Point the desk at a live scanner

1. Deploy Docker (§2) behind HTTPS (Caddy/Traefik/Nginx → `qmie:8080`).
2. Vercel → **Settings → Environment Variables** (Production):
   - `VITE_QMIE_API` = `https://your-scanner.example.com` (no trailing slash)
3. Redeploy the Vercel project so Vite inlines the env at **build** time.
   Changing the variable without a rebuild does nothing.

CORS on FastAPI is already `allow_origins=["*"]` for the public scanner
routes. Do not put `WEBHOOK_SECRET` or Discord URLs in Vercel — those belong
in `python/.env` on the scanner host.

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
