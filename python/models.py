"""
QMIE — Data Models
==================
Strict pydantic v2 models. Inbound TradingView signals, internal order
intents, broker responses, and position snapshots all flow through here.
Anything not in a model is rejected.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ═══════════════════════════════════════════════════════════════════════════
#                              Enums
# ═══════════════════════════════════════════════════════════════════════════
class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class EventType(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    CLOSE = "close"


class Grade(str, Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


class AssetClass(str, Enum):
    CRYPTO = "CRYPTO"
    METAL = "METAL"
    FUTURE = "FUTURE"
    FOREX = "FOREX"
    EQUITY = "EQUITY"
    OTHER = "OTHER"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(str, Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# ═══════════════════════════════════════════════════════════════════════════
#                       Inbound TradingView signal
# ═══════════════════════════════════════════════════════════════════════════
class TVSignal(BaseModel):
    """The exact JSON shape emitted by the Pine alert builders."""
    model_config = ConfigDict(extra="allow")

    strategy:      str
    event:         EventType = EventType.ENTRY
    symbol:        str
    asset_class:   AssetClass = AssetClass.OTHER
    timeframe:     Optional[str] = None
    side:          Optional[Side] = None
    price:         Optional[float] = None       # filled by TV at execution
    signal_price:  Optional[float] = None       # close price at signal time
    stop_loss:     Optional[float] = None
    take_profit:   Optional[float] = None
    score:         Optional[float] = None
    grade:         Optional[Grade] = None
    trend:         Optional[str] = None
    htf:           Optional[str] = None
    adx:           Optional[float] = None
    atr:           Optional[float] = None
    session:       Optional[str] = None
    timestamp:     Optional[str] = None
    bar_time:      Optional[int] = None
    contracts:     Optional[str] = None
    reason:        Optional[str] = None
    action:        Optional[str] = None         # buy/sell from {{strategy.order.action}}

    @field_validator("price", "signal_price", "stop_loss", "take_profit", mode="before")
    @classmethod
    def _coerce_float(cls, v):
        if v in (None, "", "{{strategy.order.price}}"):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @field_validator("symbol", mode="before")
    @classmethod
    def _upper_symbol(cls, v):
        return v.upper().strip() if isinstance(v, str) else v

    @property
    def idempotency_key(self) -> str:
        """Stable hash used for dedup. Multiple TV alerts on the same bar
        for the same symbol+side should NOT execute twice."""
        parts = [
            self.strategy,
            self.event.value,
            self.symbol,
            self.side.value if self.side else "-",
            str(self.bar_time or self.timestamp or ""),
        ]
        return "|".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
#                       Internal order intent (broker-agnostic)
# ═══════════════════════════════════════════════════════════════════════════
class OrderIntent(BaseModel):
    """Translated, broker-agnostic order. The router converts a TVSignal
    into one (or two: entry + protective bracket) of these."""
    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    broker:          str
    symbol:          str
    side:            Side
    order_type:      OrderType = OrderType.MARKET
    quantity:        float
    price:           Optional[float] = None
    stop_loss:       Optional[float] = None
    take_profit:     Optional[float] = None
    reduce_only:     bool = False
    time_in_force:   Literal["GTC", "IOC", "FOK", "DAY"] = "GTC"
    metadata:        dict = Field(default_factory=dict)


class BrokerResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    broker:           str
    client_order_id:  str
    broker_order_id:  Optional[str] = None
    status:           OrderStatus
    filled_qty:       float = 0.0
    avg_fill_price:   Optional[float] = None
    raw:              dict = Field(default_factory=dict)
    error:            Optional[str] = None
    submitted_at:     datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Position(BaseModel):
    broker:        str
    symbol:        str
    side:          Side
    quantity:      float
    avg_price:     float
    unrealized_pnl: Optional[float] = None
    raw:           dict = Field(default_factory=dict)


class HealthReport(BaseModel):
    status:        Literal["ok", "degraded", "down"]
    uptime_sec:    float
    queue_depth:   int
    db_ok:         bool
    brokers:       dict[str, str]   # name → "ok" / "disabled" / "error: ..."
    notifiers:     dict[str, str]
    risk:          dict
    version:       str = "1.0.0"
