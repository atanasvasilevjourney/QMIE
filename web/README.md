# QMIE Desk (web)

Cyberpunk operator UI for the QMIE signal scanner. Vite + React + TypeScript + Tailwind v4 + React Three Fiber.

## Run (dev)

Backend must be listening on `:8080` (see root README / `python/`).

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:5173`. API calls go to `/qmie/*` and are proxied to `http://127.0.0.1:8080`.

Theme: top-bar **LIGHT / DARK** toggle (persisted as `qmie-desk-theme`). Light mode is a white desk chrome; the Orbis WebGL canvas stays dark.

## Scripts

- `npm run dev` — desk UI with HMR
- `npm run build` — typecheck + production bundle
- `npm run lint` — oxlint
- `npm run preview` — serve the production build

## Tabs

| Tab | Purpose |
|---|---|
| ORBIT | Landing page: Orbis Universe 3D (RGG nebula + orbit tokens) |
| OPS | Trend Radar + TEMA / Daily breakout / Exit tables |
| GUIDE | Trading guide (paper fills, SL/TP exits, PnL) |
| AGENTS | Briefing + desk DAG (quantity always 0) |
| BOOK | Ranked allocation weights (suggested only) |
| JOURNAL | Manual fill / exit logging |
| FLOWS | Operator path (orbit → ops tables → chart → fill) |

Signal-only: this UI never places orders.
