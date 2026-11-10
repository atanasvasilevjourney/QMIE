# FTMO Swing prop sizing (research notes)

QMIE live scanner is unchanged. This page summarizes **public FTMO rules** and
**industry prop sizing practice** used to stress-test research books (S&P
momentum, trio Carver, crypto Donchian-VWAP).

## FTMO 2-Step Swing (official)

Sources: [Trading objectives](https://ftmo.com/en/trading-objectives/),
[Maximum daily loss (Academy)](https://academy.ftmo.com/lesson/maximum-daily-loss/),
[Swing FAQ](https://ftmo.com/en/faq/ftmo-swing-account-type/).

| Rule | Typical $100k eval |
|---|---|
| Profit target | +10% ($10k) |
| Maximum loss | 10% of **initial** simulated capital (equity floor ~$90k on static view; funded accounts may use a trailing high-water balance — confirm your product) |
| Maximum daily loss | 5% of **initial** capital ($5k), measured on **equity** (open P/L, swaps, commissions) |
| Daily limit reset | Midnight **CE(S)T** from **prior midnight balance** minus 5% of initial capital |
| Swing vs standard | Overnight / weekend / news holds allowed on Swing |

**Swing overnight implication:** A loss that was “safe” before midnight can breach
the **recalculated** daily floor after reset if floating loss is large. Research
books that hold multi-day equity sleeves should stress **worst daily equity change**,
not only closed-bar returns.

## What prop educators recommend (not FTMO-specific)

These are common heuristics from prop sizing guides; they are **buffers**, not
FTMO rules.

| Practice | Typical range | Rationale |
|---|---|---|
| Risk per trade | 0.25–1% of account on $100k+; size from **remaining drawdown buffer**, not full notional | [PropTradingVibes 2026](https://proptradingvibes.com/blog/position-sizing-prop-firms), [Damn Prop Firms ATR guide](https://damnpropfirms.com/trading-guides/calculate-position-size-using-atr/) |
| Stop distance | 1.5–2.5× **daily ATR** for swing stocks; 2.5–3× for slower trends | Same sources; [TradeAlgo swing RM](https://www.tradealgo.com/trading-guides/stocks/swing-trading-risk-management-position-sizing-stop-losses-and-portfolio-rules) |
| Portfolio heat | Sum of open risk capped ~**6%** (3–4% when VIX elevated) | TradeAlgo; [ClearEdge on concurrent trades](https://clearedge.trading/post/atr-average-true-range-position-sizing-automation-futures) |
| Personal circuit breaker | Stop trading near **2.5% daily / 8% total** to leave margin vs 5% / 10% firm limits | Common eval farm practice (research dial uses **8% IS max DD floor** in code) |

Formula (ATR stop sizing, one name):

```text
risk_dollars = account × risk_pct   # often 0.5–1% on large accounts
stop_points  = ATR × multiplier     # multiplier ~1.5–2.5 on daily chart
size         = floor(risk_dollars / (stop_points × point_value))
```

For a **systematic equal-weight top-N stock book**, per-name ATR stops are not
simulated in the research lab yet; we use **portfolio vol targeting** (Carver-style
lagged scale) plus optional **canary gross** and **IS-only vol dial** to align
realized book vol with a prop-safe drawdown envelope.

## How the research lab applies this

| Layer | Module | Purpose |
|---|---|---|
| Regime gate | `us100_canary.py` | Cut or scale gross when US100 (QQQ) is not in bull regime |
| Book vol target | `prop_sizing.py` | Lagged EWM vol scale on rotation returns (252d ann) |
| IS vol pick | `pick_rotation_vol_target_is` | Largest ann vol on IS with max DD ≥ floor (default −8%) |
| Legacy scalar | `mentor_prop.dial_return_scale_is` | Uniform return scale if vol layer still too hot |
| FTMO proxy stats | `mentor_prop.ftmo_daily_stats` | Worst **closed-bar** daily return %; static 10% max DD on equity curve |

**Not good (what we fixed conceptually):** Reporting raw OOS max DD (~−16%) on
canary-gated S&P momentum and calling it “prop ready.” Raw momentum concentration
violates heat/vol constraints; gating alone does not shrink tail risk enough.

**Better pipeline:** Canary (optional partial gross) → **vol-targeted weights** →
IS pick vol under DD floor → report OOS with `ftmo_10pct_ok` and
`worst_daily_loss_pct` vs 5%.

Monte Carlo eval rinse: `prop_eval_mc.py` (bootstrap daily returns × risk scale).

## Commands

```bash
cd /workspace/python
python -m research.trend_lab.run_us100_canary_validation
python -m research.trend_lab.run_mentor_prop_hypothesis
python -m research.trend_lab.run_prop_eval_monte_carlo --book trio_ranked_carver
```
