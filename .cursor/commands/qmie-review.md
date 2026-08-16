---
name: qmie-review
description: Run the weekly one-variable QMIE strategy review (journal vs goals).
---

# /qmie-review

Run the QMIE self-improve cycle. Follow `.cursor/skills/qmie-improve/SKILL.md`.

```bash
cd python && python -m improve.review
```

Then open the newest `strategy/reviews/*.md` and report:

- verdict (`insufficient_sample` / `success` / `short_of_goal` / `failure`)
- closed A/A+ fills, win%, avg R
- the single `proposed_knob` or why none
- reminder: do not write `.env`; do not place orders

TradingView in this repo is Pine + chart links, not MCP.
