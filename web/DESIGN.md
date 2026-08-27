# QMIE Desk — visual system

Read this before changing `web/` UI. Derived from Cursor/Claude **frontend-design** skill
(distinctive identity, not Inter/purple-gradient slop) plus operator readability.

## Subject

Signal-only crypto desk. One operator. Job: read radar + TEMA / daily-breakout tables
and journal fills. Never orders. Orbis 3D is the signature; chrome is the instrument.

## Tokens

| Role | Dark | Light |
|---|---|---|
| void (page) | `#0c1017` | `#f3f5f8` |
| panel | `#141a24` | `#ffffff` |
| surface | `#1a2230` | `#ffffff` |
| ink (text) | `#f2f5f8` | `#15202b` |
| muted (secondary) | `#9aa8b8` | `#4b5c6e` |
| line | `#2a3545` | `#d5dce6` |
| cyan (selection) | `#3ec8d8` | `#0b7c8c` |
| lime (up / green) | `#5dcc8a` | `#1a8a52` |
| magenta (down / red) | `#e85a8c` | `#c43d6e` |
| amber (breakout) | `#e0a54b` | `#9a6408` |

## Type

- Display **Syne** — wordmark + page titles only. Sentence case. Tracking tight, not 0.22em caps.
- Body **IBM Plex Sans** — nav, buttons, hints, guide copy. ≥14px in modules.
- Data **IBM Plex Mono** — symbols, prices, tables. Tabular nums. ≥13px.

Do not set Orbitron on table rows, chips, or 10px labels.

## Layout

Compact top bar (text tabs, not giant hint-cards). Modules share `PanelShell`:
16px radius, 20px pad, title 18px, subtitle muted 13px / 1.45 leading.

## Signature

Orbis WebGL stays dark in both themes. Panels follow `data-theme`.

## Don't

Neon-on-neon, ALL CAPS tracked labels, `text-chrome/45` at 10px, purple gradients,
cream+serif terracotta, black+single acid green, broadsheet hairlines.
