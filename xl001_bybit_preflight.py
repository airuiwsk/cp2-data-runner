#!/usr/bin/env python3
"""Non-performance market-data availability preflight for XL-20260926-001.

This script intentionally does NOT compute returns, event-window moves, PnL,
Sharpe, IC, hit rates, or any predictive statistic.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.bybit.com"
SYMBOLS = ["XMRUSDT", "BTCUSDT", "ZECUSDT"]
ANCHORS = [
    "2022-02-01T00:00:00Z",
    "2023-01-01T00:00:00Z",
    "2024-01-01T00:00:00Z",
    "2025-01-01T00:00:00Z",
    "2026-01-01T00:00:00Z",
]
INTERVAL = "5"


def get_json(path, params):
    q = urllib.parse.urlencode(params)
    url = f"{BASE}{path}?{q}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AI-Trading-nonperformance-preflight/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    obj = json.loads(raw)
    if obj.get("retCode") != 0:
        raise RuntimeError(f"Bybit error for {url}: {obj.get('retCode')} {obj.get('retMsg')}")
    return url, raw, obj


def ms(s):
    x = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int(x.timestamp() * 1000)


def iso(ts_ms):
    return dt.datetime.fromtimestamp(int(ts_ms) / 1000, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def main():
    report = {
        "lead_id": "XL-20260926-001",
        "stage": "NON_PERFORMANCE_MARKET_DATA_AVAILABILITY_PREFLIGHT",
        "provider": "Bybit V5 public API",
        "performance_computed": False,
        "symbols": {},
    }

    for symbol in SYMBOLS:
        sym = {"instrument": {}, "anchors": []}
        url, raw, obj = get_json("/v5/market/instruments-info", {"category": "linear", "symbol": symbol})
        rows = obj.get("result", {}).get("list", [])
        sym["instrument"] = {
            "request_url": url,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "row_count": len(rows),
            "symbol_found": bool(rows),
        }
        if rows:
            r = rows[0]
            sym["instrument"].update({
                "status": r.get("status"),
                "contractType": r.get("contractType"),
                "launchTime": iso(r["launchTime"]) if r.get("launchTime") else None,
                "settleCoin": r.get("settleCoin"),
                "baseCoin": r.get("baseCoin"),
                "quoteCoin": r.get("quoteCoin"),
            })

        for a in ANCHORS:
            start = ms(a)
            end = start + 60 * 60 * 1000
            try:
                kurl, kraw, kobj = get_json(
                    "/v5/market/kline",
                    {
                        "category": "linear",
                        "symbol": symbol,
                        "interval": INTERVAL,
                        "start": start,
                        "end": end,
                        "limit": 1000,
                    },
                )
                bars = kobj.get("result", {}).get("list", [])
                starts = sorted(int(x[0]) for x in bars) if bars else []
                sym["anchors"].append({
                    "anchor": a,
                    "request_url": kurl,
                    "raw_sha256": hashlib.sha256(kraw).hexdigest(),
                    "bar_count": len(bars),
                    "first_bar_start": iso(starts[0]) if starts else None,
                    "last_bar_start": iso(starts[-1]) if starts else None,
                    "schema_widths": sorted({len(x) for x in bars}),
                })
            except Exception as exc:
                sym["anchors"].append({"anchor": a, "error": str(exc)})

        report["symbols"][symbol] = sym

    report["pass_requirements"] = {
        "xmr_instrument_found": report["symbols"]["XMRUSDT"]["instrument"].get("symbol_found", False),
        "btc_instrument_found": report["symbols"]["BTCUSDT"]["instrument"].get("symbol_found", False),
        "xmr_has_at_least_3_anchor_windows": sum(
            1 for x in report["symbols"]["XMRUSDT"]["anchors"] if x.get("bar_count", 0) > 0
        ) >= 3,
        "btc_has_at_least_3_anchor_windows": sum(
            1 for x in report["symbols"]["BTCUSDT"]["anchors"] if x.get("bar_count", 0) > 0
        ) >= 3,
    }
    report["status"] = "PASS" if all(report["pass_requirements"].values()) else "FAIL"
    Path("xl001-bybit-preflight.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": report["status"],
        "performance_computed": False,
        "pass_requirements": report["pass_requirements"],
        "instrument_summary": {
            s: report["symbols"][s]["instrument"] for s in SYMBOLS
        },
        "anchor_counts": {
            s: [x.get("bar_count", 0) for x in report["symbols"][s]["anchors"]]
            for s in SYMBOLS
        },
    }, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
