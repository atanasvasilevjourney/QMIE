# QMIE Desk — visual system

Read this before changing `web/` UI. Derived from Anthropic **frontend-design**
(distinctive identity, not Inter/purple-gradient slop) plus Vercel
**web-design-guidelines** (contrast, type size, empty states, focus, theming).

## Subject

Signal-only crypto desk. One operator. Job: read radar + TEMA / daily-breakout
tables and journal fills. Never orders. Orbis 3D is the signature; chrome is the
instrument.

## Tokens

| Role | Dark | Light |
|---|---|---|
| void (page) | `#0c1017` | `#eef1f5` |
| panel | `#141a24` | `#ffffff` |
| surface | `#1a2230` | `#f7f9fb` |
| ink (text) | `#f2f5f8` | `#12202c` |
| muted (secondary) | `#a7b6c6` | `#3d5163` |
| line | `#334155` | `#c5d0dc` |
| cyan (selection) | `#3ec8d8` | `#0a6e7c` |
| lime (up / green) | `#5dcc8a` | `#157a48` |
| magenta (down / red) | `#e85a8c` | `#b52f60` |
| amber (breakout) | `#e0a54b` | `#8a5806` |

## Type

- Display **Syne** — wordmark + page titles only. Sentence case. Tracking tight, not 0.22em caps.
- Body **IBM Plex Sans** — nav, buttons, hints, guide copy. ≥14px in modules (`0.875rem`).
- Data **IBM Plex Mono** — symbols, prices, tables. Tabular nums. ≥13px (`0.8125rem`), prefer 15px on rows.

Do not set Orbitron, Syne, or 10–12px labels on table rows, chips, or HUD.

## Layout

Compact top bar (text tabs, 36px hit target). Modules share `PanelShell`:
16px radius, 20px pad, title 18px, subtitle muted 14px / 1.5 leading.

Empty buckets are one dashed line (“None yet”), not a vacant card stack.

## Signature

Orbis WebGL stays dark in both themes. Signature is a refractive glass core
with elliptical satellite rails (not neon tubes). HUD overlays use `.hud`
(always-dark tokens) so Light mode does not invert the 3D chrome. Panels
follow `data-theme`.

## Don't

Neon-on-neon, ALL CAPS tracked labels, `text-chrome/45` at 10px, purple gradients,
cream+serif terracotta, black+single acid green, broadsheet hairlines,
`font-display` on chips or data rows.
