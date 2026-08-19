---
name: qmie-analysis
description: >-
  QMIE Analysis Agent overlay. Status + Invalidation/Current/T1/T2 + tactical
  Take from stored scanner fields. Optional OpenAI. Never retunes W_*,
  never places orders, never invents gamma/dark-pool tape.
---

# QMIE analysis agent

Overlay only. Source of truth is `GET /agents/analysis/{id}`
(`improve.analysis.analyze_signal`).

- **Levels** are scanner ATR geometry: Invalidation = SL (1.5× ATR),
  Current = alert close, Target 1 = 1R (clamped if it overshoots TP),
  Target 2 = TP (2.5× ATR). Stamp prices after any LLM response.
- **Take** is template copy when `OPENAI_API_KEY` is empty or OpenAI
  errors. LLM never owns prices and is not a grade.
- Checklist SKIP → status MIXED, do not enter, do not call OpenAI.
- Do not invent equity options tape (gamma, dealer walls, 0DTE EM,
  dark pool). QMIE is crypto USDT perps.
- The 12s desk briefing only reports whether a key is set.
  Never call OpenAI on `/agents/briefing`.
- Confirm on `pine/quant_visualizer.pine`. Manual entry only.
