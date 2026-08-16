"""
QMIE — Ranked Asset Allocation
==============================
After a scan pass, pick *which* swing setups to take and *how much*
of a 100-point risk budget each gets. Does not place orders.

Rules:
  * Eligible = directional (BUY/SELL) and grade >= min_grade
  * Rank each side by score (desc), then symbol (stable)
  * Take top_long / top_short, honoring cluster_max (correlated names)
  * Split the book 50/50 long vs short when both sides have slots;
    otherwise 100% to the populated side
  * Within a side: rank weights (n, n-1, …, 1) or equal
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .signal_engine import ScanResult


_GRADE_RANK = {"A+": 4, "A": 3, "B": 2, "C": 1, "REJECT": 0}

CLUSTERS: dict[str, set[str]] = {
    "BTC": {"BTCUSDT"},
    "ETH": {"ETHUSDT", "ARBUSDT", "OPUSDT", "LDOUSDT", "ATOMUSDT"},
    "SOL": {"SOLUSDT"},
}


def cluster_of(symbol: str) -> str:
    s = symbol.upper().replace(".P", "")
    for name, members in CLUSTERS.items():
        if s in members:
            return name
    return "OTHER"


@dataclass
class AllocConfig:
    mode: str = "ranked"          # ranked | all
    top_long: int = 3
    top_short: int = 3
    min_grade: str = "A"
    weighting: str = "rank"       # rank | equal
    cluster_max: int = 1          # 0 = unlimited


@dataclass
class AllocSlot:
    result: ScanResult
    rank: int                     # 1 = best on that side
    side: str
    cluster: str
    weight_pct: float             # share of the 100-point book


@dataclass
class AllocationPlan:
    timeframe: str
    slots: list[AllocSlot] = field(default_factory=list)
    considered: int = 0
    skipped_grade: int = 0

    def as_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "considered": self.considered,
            "skipped_grade": self.skipped_grade,
            "slots": [
                {
                    "rank": s.rank,
                    "side": s.side,
                    "symbol": s.result.symbol,
                    "cluster": s.cluster,
                    "grade": s.result.grade,
                    "score": s.result.score,
                    "weight_pct": s.weight_pct,
                    "price": s.result.price,
                    "stop_loss": s.result.stop_loss,
                    "take_profit": s.result.take_profit,
                    "daily_trend": s.result.daily_trend,
                }
                for s in self.slots
            ],
        }


def _grade_ok(grade: str, min_grade: str) -> bool:
    return _GRADE_RANK.get(grade, 0) >= _GRADE_RANK.get(min_grade, 3)


def _side_weights(n: int, weighting: str, book_pct: float) -> list[float]:
    if n <= 0:
        return []
    if weighting == "equal":
        w = [book_pct / n] * n
    else:
        raw = [float(n - i) for i in range(n)]
        total = sum(raw)
        w = [book_pct * x / total for x in raw]
    # round to 2dp and fix remainder on rank 1
    rounded = [round(x, 2) for x in w]
    rounded[0] = round(book_pct - sum(rounded[1:]), 2)
    return rounded


def _pick(cands: list[ScanResult], n: int, cluster_max: int) -> list[ScanResult]:
    picked: list[ScanResult] = []
    counts: dict[str, int] = defaultdict(int)
    for r in cands:
        if len(picked) >= n:
            break
        c = cluster_of(r.symbol)
        if cluster_max > 0 and counts[c] >= cluster_max:
            continue
        picked.append(r)
        counts[c] += 1
    return picked


def allocate(
    results: list[ScanResult],
    cfg: AllocConfig,
    *,
    timeframe: str = "",
) -> AllocationPlan:
    considered = [r for r in results if r.side in ("BUY", "SELL")]
    skipped = sum(1 for r in considered if not _grade_ok(r.grade, cfg.min_grade))
    eligible = [r for r in considered if _grade_ok(r.grade, cfg.min_grade)]

    longs = sorted(
        [r for r in eligible if r.side == "BUY"],
        key=lambda r: (-r.score, r.symbol),
    )
    shorts = sorted(
        [r for r in eligible if r.side == "SELL"],
        key=lambda r: (-r.score, r.symbol),
    )
    longs_p = _pick(longs, cfg.top_long, cfg.cluster_max)
    shorts_p = _pick(shorts, cfg.top_short, cfg.cluster_max)

    long_book = 50.0 if longs_p and shorts_p else (100.0 if longs_p else 0.0)
    short_book = 50.0 if longs_p and shorts_p else (100.0 if shorts_p else 0.0)
    lw = _side_weights(len(longs_p), cfg.weighting, long_book)
    sw = _side_weights(len(shorts_p), cfg.weighting, short_book)

    slots: list[AllocSlot] = []
    for i, r in enumerate(longs_p):
        slots.append(AllocSlot(
            result=r, rank=i + 1, side="BUY",
            cluster=cluster_of(r.symbol), weight_pct=lw[i],
        ))
    for i, r in enumerate(shorts_p):
        slots.append(AllocSlot(
            result=r, rank=i + 1, side="SELL",
            cluster=cluster_of(r.symbol), weight_pct=sw[i],
        ))

    for slot in slots:
        slot.result.alloc_rank = slot.rank
        slot.result.alloc_weight_pct = slot.weight_pct
        slot.result.alloc_cluster = slot.cluster

    return AllocationPlan(
        timeframe=timeframe,
        slots=slots,
        considered=len(considered),
        skipped_grade=skipped,
    )
