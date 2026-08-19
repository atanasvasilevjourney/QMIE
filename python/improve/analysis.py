"""
QMIE Analysis Agent — OpenAI overlay, not a new score
=====================================================
Builds a levels table from scanner SL/TP (ATR geometry) and optionally
asks OpenAI for a short tactical "Take". Does not retune W_*, does not
place orders, does not invent equity options tape (gamma / dark pool).

    GET /agents/analysis/{signal_id}
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Optional

import aiohttp
from aiohttp import ClientTimeout

from improve.checklist import atr_pct_of, evaluate_native, flatten_signal, radar_color_for

logger = logging.getLogger(__name__)

OPENAI_CHAT_PATH = "/chat/completions"

SYSTEM_PROMPT = """You are the QMIE Analysis Agent for crypto USDT-perp alerts.

Hard rules:
- Overlay only. Never place orders. Never retune W_* or EMA lengths.
- Use ONLY the facts JSON. Do not invent prices, gamma, dark pool, dealer
  walls, expected-move options tape, or news.
- Levels in facts.levels are already the scanner's ATR stop / 1R / TP.
  Quote those prices; do not invent new ones.
- If facts.checklist.verdict is SKIP, status must be MIXED and take must
  say skip.
- 4h A/A+ is the measured book; 1h is a drag. Mention TF if it is 1h.
- Output a single JSON object with keys:
  status (BULLISH|BEARISH|MIXED), zone, take, counter.
- take: 2-4 sentences, tactical (where to wait, where the setup dies).
- counter: one sentence of the conflicting evidence, or "none".
"""


@dataclass
class Level:
    type: str
    price: float
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _s(v: Any) -> str:
    return str(v or "").strip()


def openai_configured(api_key: Optional[str] = None) -> bool:
    """True only when a non-empty key is present. Never logs the secret."""
    if api_key is None:
        try:
            from config import get_settings
            api_key = get_settings().openai_api_key
        except Exception:
            return False
    return bool(str(api_key or "").strip())


def scanner_levels(flat: dict[str, Any]) -> list[Level]:
    """Invalidation = SL, T1 = 1R, T2 = TP. Prices from QMIE, not the LLM."""
    side = _s(flat.get("side")).upper()
    px = _f(flat.get("signal_price") or flat.get("price"))
    sl = _f(flat.get("stop_loss"))
    tp = _f(flat.get("take_profit"))
    if px is None:
        return []
    levels: list[Level] = []
    if sl is not None:
        levels.append(Level(
            "Invalidation", round(sl, 6),
            "Scanner stop (1.5× ATR). If price reclaims this, the setup is dead.",
        ))
    levels.append(Level(
        "Current", round(px, 6),
        f"Alert {side or '—'} close. Do not chase; wait for a small bounce/retest.",
    ))
    t1: Optional[float] = None
    t2 = tp
    if sl is not None:
        risk = abs(px - sl)
        if side == "SELL":
            t1 = px - risk
            if t2 is not None and t1 <= t2:
                t1 = px - abs(px - t2) * 0.5
        else:
            t1 = px + risk
            if t2 is not None and t1 >= t2:
                t1 = px + abs(t2 - px) * 0.5
    if t1 is not None:
        levels.append(Level(
            "Target 1", round(t1, 6),
            "1R (same distance as stop). Take a partial here.",
        ))
    if t2 is not None:
        levels.append(Level(
            "Target 2", round(t2, 6),
            "Scanner take-profit (2.5× ATR). Final target on the alert.",
        ))
    return levels


def template_take(flat: dict[str, Any], checklist_verdict: str, levels: list[Level]) -> tuple[str, str, str, str]:
    """Deterministic copy when OpenAI is off. Still not an order."""
    side = _s(flat.get("side")).upper()
    symbol = _s(flat.get("symbol")).upper()
    tf = _s(flat.get("timeframe")).lower() or "?"
    grade = _s(flat.get("grade")) or "?"
    inv = next((lv.price for lv in levels if lv.type == "Invalidation"), None)
    cur = next((lv.price for lv in levels if lv.type == "Current"), None)
    t1 = next((lv.price for lv in levels if lv.type == "Target 1"), None)
    t2_present = any(lv.type == "Target 2" for lv in levels)
    t2_bit = " Final at Target 2." if t2_present else ""
    status = "MIXED"
    if checklist_verdict == "SKIP":
        status = "MIXED"
        zone = "checklist skip"
        take = (
            f"{symbol} {tf} {grade} {side}: native checklist is SKIP. "
            "Do not enter. Confirm on quant_visualizer.pine if you still look."
        )
        counter = "Required overlay failed — see Smart Checklist."
        return status, zone, take, counter
    if inv is None:
        status = "BEARISH" if side == "SELL" else "BULLISH"
        zone = "incomplete levels"
        take = (
            f"{symbol} {tf} {grade} {side}: scanner stored no stop_loss, so "
            "invalidation and 1R cannot be drawn. Do not size from this Take. "
            "Confirm on quant_visualizer.pine. Manual only."
        )
        counter = "Missing SL on the stored row — not a full plan."
        return status, zone, take, counter
    if side == "SELL":
        status = "BEARISH"
        zone = f"below invalidation {inv}"
        take = (
            f"{side} is the scanner side on {symbol} {tf} {grade} as long as price "
            f"holds beyond invalidation {inv}. Do not chase the low — look for "
            f"a small bounce from {cur} toward {inv} to enter, tight stop past {inv}. "
            f"Partial at {t1}.{t2_bit} Manual only."
        )
    else:
        status = "BULLISH"
        zone = f"above invalidation {inv}"
        take = (
            f"{side} is the scanner side on {symbol} {tf} {grade} as long as price "
            f"holds beyond invalidation {inv}. Do not chase — look for a small dip "
            f"from {cur} toward {inv} to enter, tight stop past {inv}. "
            f"Partial at {t1}.{t2_bit} Manual only."
        )
    if tf in ("1h", "60"):
        counter = "1h A/A+ diluted frozen OOS (PF 1.14 vs 4h 1.61). Prefer 4h."
    else:
        counter = "If HTF, daily trend, or radar color disagree, treat as WATCH not GO."
    return status, zone, take, counter


def facts_payload(
    row: dict[str, Any],
    *,
    radar: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    flat = flatten_signal(row)
    chk = evaluate_native(row, radar=radar)
    levels = scanner_levels(flat)
    color = radar_color_for(_s(flat.get("symbol")), radar)
    return {
        "symbol": _s(flat.get("symbol")).upper(),
        "side": _s(flat.get("side")).upper(),
        "grade": _s(flat.get("grade")),
        "score": _f(flat.get("score")),
        "timeframe": _s(flat.get("timeframe")).lower(),
        "signal_id": flat.get("id"),
        "price": _f(flat.get("signal_price") or flat.get("price")),
        "stop_loss": _f(flat.get("stop_loss")),
        "take_profit": _f(flat.get("take_profit")),
        "adx": _f(flat.get("adx")),
        "rsi": _f(flat.get("rsi")),
        "atr_pct": atr_pct_of(flat),
        "htf": _s(flat.get("htf")),
        "daily_trend": _s(flat.get("daily_trend")),
        "funding_rate": _f(flat.get("funding_rate")),
        "radar_color": color,
        "checklist": {"verdict": chk.verdict, "action": chk.action},
        "levels": [lv.as_dict() for lv in levels],
        "places_orders": False,
        "note": "Levels are scanner ATR geometry. Not gamma/dark-pool.",
    }


def _extract_json(text: str) -> dict[str, Any]:
    blob = (text or "").strip()
    if blob.startswith("```"):
        blob = blob.strip("`")
        if blob.lower().startswith("json"):
            blob = blob[4:]
        blob = blob.strip()
    return json.loads(blob)


async def _openai_narrative(
    facts: dict[str, Any],
    *,
    api_key: str,
    model: str,
    timeout_sec: float,
    base_url: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> dict[str, str]:
    url = base_url.rstrip("/") + OPENAI_CHAT_PATH
    body = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(facts, default=str)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    close = False
    sess = session
    if sess is None:
        sess = aiohttp.ClientSession()
        close = True
    try:
        timeout = ClientTimeout(total=timeout_sec)
        async with sess.post(url, json=body, headers=headers, timeout=timeout) as resp:
            raw = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(
                    f"openai_http_{resp.status}: {raw if isinstance(raw, dict) else resp.status}"
                )
    finally:
        if close:
            await sess.close()
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"openai_bad_payload: {e}") from e
    parsed = _extract_json(content)
    return {
        "status": _s(parsed.get("status")).upper() or "MIXED",
        "zone": _s(parsed.get("zone")) or "setup",
        "take": _s(parsed.get("take")),
        "counter": _s(parsed.get("counter")) or "none",
    }


def _stamp_levels(card: dict[str, Any], levels: list[Level]) -> dict[str, Any]:
    """LLM never owns prices."""
    card["levels"] = [lv.as_dict() for lv in levels]
    card["places_orders"] = False
    return card


async def analyze_signal(
    row: dict[str, Any],
    *,
    api_key: Optional[str] = None,
    model: str = "gpt-4.1-mini",
    timeout_sec: float = 20.0,
    base_url: str = "https://api.openai.com/v1",
    radar: Optional[dict[str, Any]] = None,
    session: Optional[aiohttp.ClientSession] = None,
) -> dict[str, Any]:
    facts = facts_payload(row, radar=radar)
    levels = [Level(**lv) for lv in facts["levels"]]
    chk_v = facts["checklist"]["verdict"]
    status, zone, take, counter = template_take(flatten_signal(row), chk_v, levels)
    source = "template"
    key = str(api_key or "").strip() or None
    # SKIP never calls OpenAI — checklist already said do not enter.
    if key and chk_v != "SKIP":
        try:
            nar = await _openai_narrative(
                facts,
                api_key=key,
                model=model,
                timeout_sec=timeout_sec,
                base_url=base_url,
                session=session,
            )
            if nar.get("take"):
                status = nar["status"] if nar["status"] in ("BULLISH", "BEARISH", "MIXED") else status
                zone = nar["zone"] or zone
                take = nar["take"]
                counter = nar["counter"]
                source = "openai"
        except Exception as e:
            logger.warning("OpenAI analysis failed, using template: %s", e)
            source = f"template_fallback:{type(e).__name__}"
    if chk_v == "SKIP":
        status = "MIXED"
    card = {
        "ok": True,
        "agent": "analysis",
        "source": source,
        "model": model if source == "openai" else None,
        "openai_configured": bool(key),
        "symbol": facts["symbol"],
        "side": facts["side"],
        "grade": facts["grade"],
        "timeframe": facts["timeframe"],
        "signal_id": facts["signal_id"],
        "status": status,
        "zone": zone,
        "take": take,
        "counter": counter,
        "checklist_verdict": chk_v,
        "note": "Overlay. Confirm on quant_visualizer.pine. Not an order. Not a grade.",
    }
    return _stamp_levels(card, levels)
