"""Pure helpers for derivatives flow snapshots (ported from crypto-flow prototype)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

FLOW_ASSETS = frozenset({"BTC", "ETH", "SOL"})

BV = "https://data-api.binance.vision"
OKX = "https://www.okx.com"
BG = "https://api.bitget.com"
GATE = "https://api.gateio.ws/api/v4"
HTX = "https://api.hbdm.com"
HL = "https://api.hyperliquid.xyz/info"
ASTER = "https://fapi.asterdex.com"
DERIBIT = "https://www.deribit.com/api/v2/public"


def utc_now(ts: float | None = None) -> str:
    t = ts if ts is not None else time.time()
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def asset_symbols(asset: str) -> dict[str, Any]:
    a = asset.upper()
    return dict(
        binance=f"{a}USDT",
        okx_swap=f"{a}-USDT-SWAP",
        okx_spot=f"{a}-USDT",
        bitget=f"{a}USDT",
        gate=f"{a}_USDT",
        htx=f"{a}-USDT",
        hl=a,
        aster=f"{a}USDT",
        bybit=f"{a}USDT",
        deribit={"BTC": "BTC-PERPETUAL", "ETH": "ETH-PERPETUAL"}.get(a),
    )


def fmt_money(x: float | None) -> str:
    if x is None:
        return "n/a"
    a = abs(x)
    s = "-" if x < 0 else ""
    if a >= 1e9:
        return f"{s}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{s}${a / 1e6:.1f}M"
    return f"{s}${a / 1e3:.0f}K"


def fmt_price_k(p: float) -> str:
    return f"{p / 1000:.1f}K" if p >= 10000 else f"{p:,.2f}"


def parse_binance_klines(raw: list) -> list[dict[str, float | int]]:
    return [
        dict(
            t=int(x[0]),
            o=float(x[1]),
            h=float(x[2]),
            l=float(x[3]),
            c=float(x[4]),
            v=float(x[5]),
            qv=float(x[7]),
            tbq=float(x[10]),
        )
        for x in raw
    ]


def pivots(k: list[dict], n: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    hi, lo = [], []
    for i in range(n, len(k) - n):
        if k[i]["h"] == max(x["h"] for x in k[i - n : i + n + 1]):
            hi.append((k[i]["t"], k[i]["h"]))
        if k[i]["l"] == min(x["l"] for x in k[i - n : i + n + 1]):
            lo.append((k[i]["t"], k[i]["l"]))
    return hi, lo


def volume_nodes(
    k: list[dict], price: float, bin_pct: float = 0.75, top: int = 6
) -> tuple[list[dict[str, float]], tuple[float, float, list[float]] | None]:
    lo = min(x["l"] for x in k)
    hi = max(x["h"] for x in k)
    w = price * bin_pct / 100
    nb = int((hi - lo) / w) + 1
    vol = [0.0] * nb
    for x in k:
        a = int((x["l"] - lo) / w)
        b = int((x["h"] - lo) / w)
        share = x["qv"] / (b - a + 1)
        for i in range(a, b + 1):
            vol[i] += share
    peaks = [i for i in range(1, nb - 1) if vol[i] >= vol[i - 1] and vol[i] >= vol[i + 1]]
    peaks = sorted(peaks, key=lambda i: -vol[i])[:top]
    hvn = sorted(
        [{"price": round(lo + (i + 0.5) * w, 1), "quote_vol_usd": vol[i]} for i in peaks],
        key=lambda d: d["price"],
    )
    prof = (lo, w, vol)
    return hvn, prof


def key_levels(k1d: list[dict], k4h: list[dict], price: float) -> dict[str, Any]:
    lv = []
    for tf, bars, n in (("1d", k1d, 5), ("4h", k4h, 6)):
        hi, lo = pivots(bars, n)
        lv += [dict(price=p, kind="swing high", tf=tf, t=utc_now(t / 1000)) for t, p in hi]
        lv += [dict(price=p, kind="swing low", tf=tf, t=utc_now(t / 1000)) for t, p in lo]
    lv.sort(key=lambda d: d["price"])
    merged: list[dict[str, Any]] = []
    for d in lv:
        if merged and abs(d["price"] / merged[-1]["price"] - 1) < 0.01:
            merged[-1]["touches"] += 1
            merged[-1]["tfs"] = sorted(set(merged[-1]["tfs"] + [d["tf"]]))
            merged[-1]["last_utc"] = max(merged[-1]["last_utc"], d["t"])
            merged[-1]["kinds"] = sorted(set(merged[-1]["kinds"] + [d["kind"]]))
        else:
            merged.append(
                dict(price=d["price"], touches=1, tfs=[d["tf"]], kinds=[d["kind"]], last_utc=d["t"])
            )
    for m in merged:
        m["role_now"] = "resistance" if m["price"] > price else "support"
        m["flipped"] = m["role_now"] == "resistance" and "swing low" in m["kinds"]

    def pick(cands: list[dict], gap: float, n: int) -> list[dict]:
        out: list[dict] = []
        for m in cands:
            if abs(m["price"] / price - 1) < 0.004:
                continue
            if out and abs(m["price"] / out[-1]["price"] - 1) < gap:
                continue
            out.append(m)
            if len(out) == n:
                break
        return out

    sig = [m for m in merged if "1d" in m["tfs"] or m["touches"] >= 2]
    above = pick([m for m in sig if m["price"] > price], 0.015, 4)
    below = pick([m for m in sig if m["price"] < price][::-1], 0.015, 4)
    hi10, lo10 = pivots(k1d, 10)
    maj = sorted(
        [dict(price=p, kind="swing high", t=utc_now(t / 1000)) for t, p in hi10]
        + [dict(price=p, kind="swing low", t=utc_now(t / 1000)) for t, p in lo10],
        key=lambda d: d["price"],
    )
    for m in maj:
        m["flipped"] = m["price"] > price and m["kind"] == "swing low"
    maj_above = pick([m for m in maj if m["price"] > price], 0.04, 4)
    maj_below = pick([m for m in maj if m["price"] < price][::-1], 0.04, 3)
    hvn, prof = volume_nodes(k4h, price)
    cycle_high = max((x["h"], x["t"]) for x in k1d)
    cycle_low = min((x["l"], x["t"]) for x in k1d)
    return {
        "resistance": above,
        "support": below,
        "major_above": maj_above,
        "major_below": maj_below,
        "hvn_4h": hvn,
        "range_4h_window": {
            "from_utc": utc_now(k4h[0]["t"] / 1000),
            "to_utc": utc_now(k4h[-1]["t"] / 1000),
        },
        "cycle_high_1d": {"price": cycle_high[0], "t_utc": utc_now(cycle_high[1] / 1000)},
        "cycle_low_1d": {"price": cycle_low[0], "t_utc": utc_now(cycle_low[1] / 1000)},
        "source": "Binance spot klines (data-api.binance.vision) 1d/4h pivots + 4h volume profile",
        "_volume_profile": prof,
    }


def modelled_liq_clusters(
    oi_hist_4h: list[tuple[int, float, float | None, float, float]],
    price: float,
    levs: tuple[int, ...] = (25, 50, 100),
) -> list[dict[str, Any]]:
    bins: dict[tuple[str, float], float] = {}
    for i in range(1, len(oi_hist_4h)):
        t, oi, px, lo_after, hi_after = oi_hist_4h[i]
        prev = oi_hist_4h[i - 1][1]
        d = oi - prev
        if d <= 0 or not px:
            continue
        for lev in levs:
            for side, lp in (("long", px * (1 - 1 / lev)), ("short", px * (1 + 1 / lev))):
                if side == "long" and lp >= lo_after:
                    continue
                if side == "short" and lp <= hi_after:
                    continue
                b = round(lp / (price * 0.005)) * price * 0.005
                key = (side, round(b, 0))
                bins[key] = bins.get(key, 0) + d / 2 / len(levs)
    top = sorted(bins.items(), key=lambda kv: -kv[1])[:8]
    return [
        {"side": k[0], "price": k[1], "est_notional_usd": v}
        for k, v in sorted(top, key=lambda kv: kv[0][1])
    ]


def hourly_bucket(rows: list[tuple[int, float]]) -> dict[int, float]:
    d: dict[int, float] = {}
    for t, v in rows:
        h = t - t % 3_600_000
        d[h] = d.get(h, 0) + v
    return d


def cvd_window(series_by_ex: dict[str, dict[int, float]], start_ms: int) -> dict[str, Any]:
    per = {ex: sum(v for t, v in d.items() if t >= start_ms) for ex, d in series_by_ex.items()}
    return {"total_usd": sum(per.values()), "by_exchange_usd": per}


def oi_changes(hist: dict[str, list[tuple[int, float]]]) -> dict[str, Any]:
    res: dict[str, Any] = {}
    agg_now = 0.0
    agg: dict[int, float] = {1: 0, 4: 0, 24: 0}
    ok = {1: True, 4: True, 24: True}
    for ex, ser in hist.items():
        d = dict(ser)
        last_t = max(d)
        cur = d[last_t]
        r: dict[str, Any] = {"latest_bar_utc": utc_now(last_t / 1000), "oi_usd": cur}
        for hrs in (1, 4, 24):
            p = d.get(last_t - hrs * 3_600_000)
            r[f"chg_{hrs}h_pct"] = None if p is None else (cur / p - 1) * 100
            if p is None:
                ok[hrs] = False
            else:
                agg[hrs] += p
        agg_now += cur
        res[ex] = r
    res["aggregate_OKX_Gate_HTX"] = {
        "oi_usd": agg_now,
        **{
            f"chg_{h}h_pct": ((agg_now / agg[h] - 1) * 100 if ok[h] and agg[h] else None)
            for h in (1, 4, 24)
        },
    }
    return res


def liq_aggregate_rows(rows: list[dict]) -> tuple[float, float, float]:
    long_u = sum(r["usd"] for r in rows if r["side"] == "long")
    short_u = sum(r["usd"] for r in rows if r["side"] == "short")
    return long_u + short_u, long_u, short_u


def observed_liq_clusters(rows: list[dict], price: float, top: int = 6) -> list[dict[str, Any]]:
    obs: dict[tuple[str, float], float] = {}
    for r in rows:
        b = round(r["price"] / (price * 0.0025)) * price * 0.0025
        key = (r["side"], round(b))
        obs[key] = obs.get(key, 0) + r["usd"]
    return [
        {"side": k[0], "price": k[1], "usd": v}
        for k, v in sorted(obs.items(), key=lambda kv: -kv[1])[:top]
    ]


def build_narrative(r: dict[str, Any]) -> str:
    a = r["asset"]
    p = r["price"]
    lv = r.get("levels") or {}
    c = r["cvd"]
    oi = r["open_interest"]
    lq = r["liquidations_24h"]
    fu = r["funding"]
    parts: list[str] = []
    parts.append(
        f"{a} is at {fmt_price_k(p['spot_last'])} ({p['change_pct']:+.2f}% 24h), "
        f"range {fmt_price_k(p['low'])}-{fmt_price_k(p['high'])} on "
        f"{fmt_money(p['quote_volume_usd'])} Binance spot volume."
    )
    if "resistance" in lv:
        res = ", ".join(
            fmt_price_k(m["price"]) + (" (flipped support)" if m.get("flipped") else "")
            for m in lv["resistance"][:3]
        )
        sup = ", ".join(fmt_price_k(m["price"]) for m in lv["support"][:3])
        hv = lv.get("hvn_4h") or []
        hv_s = ", ".join(
            fmt_price_k(h["price"])
            for h in sorted(hv, key=lambda h: abs(h["price"] - p["spot_last"]))[:3]
        )
        parts.append(f"Near-term resistance {res}; support {sup}. Nearest 4h HVNs: {hv_s}.")
        if lv.get("major_above"):
            tail = (
                f", with major swing low below at {fmt_price_k(lv['major_below'][0]['price'])}"
                if lv.get("major_below")
                else ""
            )
            parts.append(
                "Bigger picture overhead: "
                + ", ".join(
                    fmt_price_k(m["price"]) + (" (lost support)" if m.get("flipped") else "")
                    for m in lv["major_above"][:3]
                )
                + tail
                + "."
            )
    sp, pp = c["spot_24h"]["total_usd"], c["perp_24h"]["total_usd"]
    if sp > 0 and pp > 0:
        lead = "both spot and perps net buying" + (", perps louder" if pp > sp else ", spot louder")
    elif pp < sp < 0 or (pp < 0 and abs(pp) > abs(sp)):
        lead = "perps doing heavier selling"
    elif abs(sp) > abs(pp):
        lead = "spot leading"
    else:
        lead = "perps leading"
    parts.append(
        f"24h CVD: spot {fmt_money(sp)} vs perps {fmt_money(pp)} "
        f"(since 00:00 UTC: spot {fmt_money(c['spot_since_0000utc']['total_usd'])}, "
        f"perps {fmt_money(c['perp_since_0000utc']['total_usd'])}) — {lead}."
    )
    ag = oi["change_from_history"].get("aggregate_OKX_Gate_HTX", {})

    def pc(x: float | None) -> str:
        return "n/a" if x is None else f"{x:+.2f}%"

    f8 = fu["oi_weighted_8h_equiv"]
    n_venues = len(oi.get("by_exchange") or {})
    parts.append(
        f"Open interest across {n_venues} venues is {fmt_money(oi['total_usd_now'])}; "
        f"OKX+Gate+HTX changed {pc(ag.get('chg_1h_pct'))} 1h, "
        f"{pc(ag.get('chg_4h_pct'))} 4h, {pc(ag.get('chg_24h_pct'))} 24h; "
        f"OI-weighted funding {f8 * 100:.4f}% per 8h."
    )
    chg24 = ag.get("chg_24h_pct") or 0
    if chg24 > 1 and p["change_pct"] < 0:
        lr = "OI rising into falling price — new leverage on both sides."
    elif chg24 < -1 and p["change_pct"] < 0:
        lr = "OI falling with price — longs closing rather than fresh shorts."
    elif chg24 > 1 and p["change_pct"] > 0:
        lr = "OI rising with price — leveraged longs chasing."
    elif chg24 < -1:
        lr = "OI falling into a bounce — short covering bias."
    else:
        lr = "OI roughly flat — leverage not the main driver."
    ls = r.get("long_short") or {}
    acc = [v["ratio"] for k, v in ls.items() if "accounts" in k and isinstance(v.get("ratio"), (int, float))]
    if acc:
        crowd = "heavily long" if min(acc) > 1.5 else "leaning long" if min(acc) > 1 else "leaning short"
        lr += f" Retail L/S: {', '.join(f'{x:.2f}' for x in acc)} — {crowd}."
    parts.append(lr)
    t = lq["aggregate_of_complete_venues"]
    if t.get("total_usd"):
        parts.append(
            f"24h liquidations ({', '.join(t.get('venues_included') or [])}): "
            f"{fmt_money(t['total_usd'])}, longs {t['long_usd'] / t['total_usd'] * 100:.0f}%."
        )
    mc = (r.get("modelled_liq_clusters") or {}).get("clusters") or []
    if mc:
        above = [m for m in mc if m["price"] > p["spot_last"]]
        below = [m for m in mc if m["price"] < p["spot_last"]]
        bits = []
        if below:
            bits.append(
                "modelled long-liq near "
                + ", ".join(fmt_price_k(m["price"]) for m in sorted(below, key=lambda m: -m["price"])[:2])
            )
        if above:
            bits.append(
                "short-liq near "
                + ", ".join(fmt_price_k(m["price"]) for m in sorted(above, key=lambda m: m["price"])[:2])
            )
        if bits:
            parts.append("Watch: spot vs perp CVD divergence, funding flip, and " + " / ".join(bits) + " (estimate).")
    parts.append("Data, not financial advice.")
    return " ".join(parts)


def chart_payload(
    k4h: list[dict],
    spot_h: dict[str, dict[int, float]],
    perp_h: dict[str, dict[int, float]],
    oi_hist: dict[str, list[tuple[int, float]]],
    levels: dict[str, Any],
    model_clusters: list[dict],
    prof: tuple[float, float, list[float]] | None,
    price: float,
) -> dict[str, Any]:
    bars = k4h[-180:]
    lo = min(x["l"] for x in bars)
    hi = max(x["h"] for x in bars)

    def cum_series(series: dict[str, dict[int, float]], n: int = 48) -> list[dict[str, float]]:
        ts = sorted({t for d in series.values() for t in d})[-n:]
        tot = 0.0
        out: list[dict[str, float]] = []
        for t in ts:
            tot += sum(d.get(t, 0) for d in series.values())
            out.append({"t": t, "cvd_usd": tot})
        return out

    oi_ts: list[dict[str, float]] = []
    if oi_hist:
        ts = sorted(set.intersection(*[set(t for t, _ in s) for s in oi_hist.values()]))[-72:]
        dmap = {ex: dict(s) for ex, s in oi_hist.items()}
        for t in ts:
            oi_ts.append({"t": t, "oi_usd": sum(dmap[e][t] for e in dmap)})

    vp_bins: list[dict[str, float]] = []
    if prof:
        plo, bw, vol = prof
        vmax = max(vol) if vol else 1
        for i, v in enumerate(vol):
            y = plo + i * bw
            if lo * 0.9 <= y <= hi * 1.1:
                vp_bins.append({"price": y, "norm": v / vmax})

    return {
        "bars_4h": [{"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]} for b in bars],
        "price_lo": lo,
        "price_hi": hi,
        "spot_cvd_cum": cum_series(spot_h),
        "perp_cvd_cum": cum_series(perp_h),
        "oi_aggregate_hourly": oi_ts,
        "volume_profile": vp_bins,
        "level_lines": {
            "resistance": levels.get("resistance") or [],
            "support": levels.get("support") or [],
            "major_above": levels.get("major_above") or [],
            "major_below": levels.get("major_below") or [],
        },
        "modelled_liq_bands": model_clusters,
        "last_price": price,
    }