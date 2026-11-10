"""CLI: python -m long_vol.cli scan | eventstudy (stub)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _cmd_scan(args: argparse.Namespace) -> int:
    from backtest.data_loader import load_klines
    from long_vol.config import LongVolConfig, load_config
    from long_vol.live_scan import candidate_to_scan_fields, scan_closed_bar

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    cfg = load_config(cfg_path)
    if args.width_lookback:
        d = cfg.model_dump()
        d["features"]["width_pct_lookback_1h_bars"] = args.width_lookback
        cfg = LongVolConfig.model_validate(d)

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days)
    btc = load_klines(cfg.data.btc_symbol, "15m", start, end)
    symbols = args.symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    out = []
    for sym in symbols:
        df = load_klines(sym, "15m", start, end)
        if len(df) < cfg.features.vwap_bars + 5:
            continue
        cand, _ = scan_closed_bar(sym, df, cfg=cfg, btc15=btc)
        out.append(candidate_to_scan_fields(cand))
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        for row in out:
            flag = "ALERT" if row.get("alert") else "watch"
            print(f"{flag} {row['symbol']} gates={row.get('gates')} dist_atr={row.get('features', {}).get('dist_atr')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="longvol")
    sub = p.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan", help="Latest-bar candidates (Vision cache)")
    scan.add_argument("--config", default="configs/long_vol_v1.yaml")
    scan.add_argument("--symbols", nargs="+")
    scan.add_argument("--days", type=int, default=30)
    scan.add_argument("--width-lookback", type=int, default=0)
    scan.add_argument("--json", action="store_true")
    scan.set_defaults(func=_cmd_scan)
    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
