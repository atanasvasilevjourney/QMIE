"""
QMIE setup card — AI-ruled overlay, not a new score
===================================================
QMIE `compute_signal` stays the source of truth. This module applies a
fixed checklist to an optional TradingView-MCP snapshot (live quote,
third-party TA, HTF bias). Missing MCP → INCOMPLETE, never CONFIRM.

    cd python && python -m improve.setup_review --symbol BTCUSDT --side BUY \\
        --grade A --score 84 --rsi 52 --adx 28 --htf-aligned --daily-trend bullish \\
        --mcp-json mcp.json

Does not write `.env`, does not place orders, does not change weights.
MCP generic `backtest_strategy` is *not* QMIE OOS — use
`python -m backtest.run` for that.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_BUY = {"buy", "strong buy", "strong_buy", "bullish"}
_SELL = {"sell", "strong sell", "strong_sell", "bearish"}
_HOLD = {"hold", "neutral", "mixed"}


def yahoo_symbol(qmie_symbol: str) -> str:
    """BTCUSDT → BTC-USD. Best-effort; MCP also accepts BINANCE:TICKER."""
    s = qmie_symbol.upper().replace(".P", "").strip()
    if s.endswith("USDT"):
        s = s[:-4]
    if s.startswith("1000"):
        s = s[4:]
    return f"{s}-USD"


def _norm(raw: Optional[str]) -> str:
    return (raw or "").strip().lower().replace("-", " ")


def mcp_side(recommendation: Optional[str]) -> Optional[str]:
    n = _norm(recommendation)
    if n in _BUY:
        return "BUY"
    if n in _SELL:
        return "SELL"
    if n in _HOLD:
        return "HOLD"
    return None


@dataclass(frozen=True)
class QmieSetup:
    symbol: str
    timeframe: str
    side: str
    grade: str
    score: float
    rsi: Optional[float] = None
    adx: Optional[float] = None
    htf_aligned: Optional[bool] = None
    daily_trend: str = "unknown"
    atr_pct: Optional[float] = None


@dataclass(frozen=True)
class McpSnapshot:
    recommendation: Optional[str] = None
    rsi: Optional[float] = None
    htf_bias: Optional[str] = None
    yahoo_last: Optional[float] = None
    sentiment: Optional[str] = None
    source_notes: str = ""


@dataclass(frozen=True)
class RuleResult:
    id: str
    passed: bool
    required: bool
    detail: str


@dataclass
class SetupVerdict:
    verdict: str  # CONFIRM / CONFLICT / INCOMPLETE
    action: str
    rules: list[RuleResult] = field(default_factory=list)

    @property
    def failed_required(self) -> list[RuleResult]:
        return [r for r in self.rules if r.required and not r.passed]


def evaluate(qmie: QmieSetup, mcp: Optional[McpSnapshot]) -> SetupVerdict:
    rules: list[RuleResult] = []

    grade_ok = qmie.grade in ("A", "A+")
    side_ok = qmie.side in ("BUY", "SELL")
    rules.append(RuleResult(
        "qmie_alert",
        grade_ok and side_ok,
        True,
        f"QMIE {qmie.side} {qmie.grade} {qmie.score}/100 "
        f"(need A/A+ directional)",
    ))

    if mcp is None:
        rules.append(RuleResult(
            "mcp_present",
            False,
            True,
            "No MCP snapshot — enable tradingview in Cursor Settings → MCP",
        ))
        return SetupVerdict(
            verdict="INCOMPLETE",
            action="Open the visualizer from the Discord/Telegram chart link. "
                   "Do not treat this as MCP-confirmed.",
            rules=rules,
        )

    rec_side = mcp_side(mcp.recommendation)
    if rec_side is None:
        rules.append(RuleResult(
            "mcp_recommendation",
            False,
            True,
            "MCP recommendation missing or unreadable",
        ))
    elif rec_side == "HOLD":
        rules.append(RuleResult(
            "mcp_recommendation",
            False,
            True,
            f"MCP is HOLD vs QMIE {qmie.side}",
        ))
    else:
        rules.append(RuleResult(
            "mcp_recommendation",
            rec_side == qmie.side,
            True,
            f"MCP {mcp.recommendation!r} → {rec_side} vs QMIE {qmie.side}",
        ))

    htf = mcp_side(mcp.htf_bias)
    if htf is None:
        rules.append(RuleResult(
            "mcp_htf",
            False,
            True,
            "MCP HTF bias missing (call get_multi_timeframe_analysis)",
        ))
    elif htf == "HOLD":
        rules.append(RuleResult(
            "mcp_htf",
            False,
            True,
            "MCP HTF mixed/neutral — no confirmation",
        ))
    else:
        rules.append(RuleResult(
            "mcp_htf",
            htf == qmie.side,
            True,
            f"MCP HTF {mcp.htf_bias!r} vs QMIE {qmie.side}",
        ))

    # Extreme RSI *against* the QMIE side is a hard fail when MCP RSI exists.
    if mcp.rsi is None:
        rules.append(RuleResult(
            "mcp_rsi",
            False,
            True,
            "MCP RSI missing (call get_technical_analysis)",
        ))
    elif qmie.side == "BUY" and mcp.rsi >= 75:
        rules.append(RuleResult(
            "mcp_rsi",
            False,
            True,
            f"MCP RSI {mcp.rsi:.1f} overbought against BUY",
        ))
    elif qmie.side == "SELL" and mcp.rsi <= 25:
        rules.append(RuleResult(
            "mcp_rsi",
            False,
            True,
            f"MCP RSI {mcp.rsi:.1f} oversold against SELL",
        ))
    else:
        rules.append(RuleResult(
            "mcp_rsi",
            True,
            True,
            f"MCP RSI {mcp.rsi:.1f} not extreme against {qmie.side}",
        ))

    # Sentiment is informational only — never a scoring or confirm input.
    if mcp.sentiment:
        rules.append(RuleResult(
            "mcp_sentiment",
            True,
            False,
            f"Sentiment {mcp.sentiment!r} (info only, not a gate)",
        ))

    required_fail = [r for r in rules if r.required and not r.passed]
    missing = [
        r for r in required_fail
        if "missing" in r.detail.lower() or "unreadable" in r.detail.lower()
    ]
    disagreement = [r for r in required_fail if r not in missing]
    if disagreement:
        verdict, action = (
            "CONFLICT",
            "Skip this entry. QMIE and MCP TA disagree. Do not retune W_*.",
        )
    elif missing:
        verdict, action = (
            "INCOMPLETE",
            "Fill the missing MCP fields, then re-run. Visualizer still applies.",
        )
    else:
        verdict, action = (
            "CONFIRM",
            "Overlay agrees. Open quant_visualizer.pine on the chart link "
            "and decide manually. Not an order.",
        )
    return SetupVerdict(verdict=verdict, action=action, rules=rules)


def snapshot_from_dict(raw: dict[str, Any]) -> McpSnapshot:
    rsi = raw.get("rsi")
    last = raw.get("yahoo_last")
    return McpSnapshot(
        recommendation=raw.get("recommendation"),
        rsi=float(rsi) if rsi is not None and rsi != "" else None,
        htf_bias=raw.get("htf_bias"),
        yahoo_last=float(last) if last is not None and last != "" else None,
        sentiment=raw.get("sentiment"),
        source_notes=str(raw.get("source_notes") or ""),
    )


def render(qmie: QmieSetup, mcp: Optional[McpSnapshot], v: SetupVerdict) -> str:
    lines = [
        f"# Setup {qmie.symbol} {qmie.timeframe}",
        "",
        f"- QMIE: **{qmie.side} {qmie.grade}** score {qmie.score}",
        f"- RSI {qmie.rsi} · ADX {qmie.adx} · HTF aligned {qmie.htf_aligned} "
        f"· daily {qmie.daily_trend} · ATR% {qmie.atr_pct}",
        f"- Yahoo ticker for MCP: `{yahoo_symbol(qmie.symbol)}`",
        "",
        f"**Verdict: {v.verdict}**",
        v.action,
        "",
        "| Rule | Required | Result | Detail |",
        "|---|---|---|---|",
    ]
    for r in v.rules:
        mark = "PASS" if r.passed else "FAIL"
        lines.append(
            f"| `{r.id}` | {'yes' if r.required else 'no'} | {mark} | {r.detail} |"
        )
    lines += [
        "",
        "## Boundaries",
        "- This overlay does not change `compute_signal` or Pine.",
        "- `combined_analysis` / news / Reddit are info only.",
        "- MCP `backtest_strategy` is a generic strategy, not QMIE OOS. "
        "QMIE signals: `python -m backtest.run`.",
        "- No orders.",
    ]
    if mcp and mcp.yahoo_last is not None:
        lines.insert(5, f"- MCP last (Yahoo): {mcp.yahoo_last}")
    if mcp and mcp.source_notes:
        lines.append(f"- MCP notes: {mcp.source_notes}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="QMIE + MCP ruled setup overlay")
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", default="4h")
    p.add_argument("--side", required=True, choices=["BUY", "SELL", "NEUTRAL"])
    p.add_argument("--grade", required=True)
    p.add_argument("--score", type=float, required=True)
    p.add_argument("--rsi", type=float, default=None)
    p.add_argument("--adx", type=float, default=None)
    p.add_argument("--htf-aligned", action="store_true")
    p.add_argument("--daily-trend", default="unknown")
    p.add_argument("--atr-pct", type=float, default=None)
    p.add_argument(
        "--mcp-json",
        default=None,
        help="Path to MCP snapshot JSON, or - for stdin. Omit = INCOMPLETE.",
    )
    args = p.parse_args(argv)

    qmie = QmieSetup(
        symbol=args.symbol,
        timeframe=args.timeframe,
        side=args.side,
        grade=args.grade,
        score=args.score,
        rsi=args.rsi,
        adx=args.adx,
        htf_aligned=True if args.htf_aligned else None,
        daily_trend=args.daily_trend,
        atr_pct=args.atr_pct,
    )
    mcp = None
    if args.mcp_json:
        blob = sys.stdin.read() if args.mcp_json == "-" else Path(args.mcp_json).read_text(encoding="utf-8")
        mcp = snapshot_from_dict(json.loads(blob))
    v = evaluate(qmie, mcp)
    sys.stdout.write(render(qmie, mcp, v))
    return 0 if v.verdict != "CONFLICT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
