#!/usr/bin/env python3
"""CP2 forward-append integrity path.

This module collects only public market observability data. It does not compute
returns, PnL, Sharpe, IC, signals, or optimization results.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from cp2_bybit_integrity import (
    BASE_URL,
    CONTRACT,
    SYMBOLS,
    canonical_json,
    request,
    save_raw,
    sha256,
    utc_now,
)

TICKER_ENDPOINT = "/v5/market/tickers"
TRADES_ENDPOINT = "/v5/market/recent-trade"


def batch_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def write_jsonl(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = b"".join(canonical_json(row) for row in rows)
    path.write_bytes(data)
    return sha256(data)


def normalize_ticker(payload: dict, symbol: str, prov: dict) -> dict:
    items = [x for x in payload.get("result", {}).get("list", []) if x.get("symbol") == symbol]
    if len(items) != 1:
        raise RuntimeError(f"BLOCK: expected one ticker row for {symbol}, got {len(items)}")
    x = items[0]
    return {
        "kind": "ticker",
        "symbol": symbol,
        "source_server_time_ms": int(payload["time"]),
        "collector_receive_time_utc": prov["response_received_at_utc"],
        "lastPrice": x.get("lastPrice", ""),
        "markPrice": x.get("markPrice", ""),
        "indexPrice": x.get("indexPrice", ""),
        "fundingRate": x.get("fundingRate", ""),
        "nextFundingTime": x.get("nextFundingTime", ""),
        "bid1Price": x.get("bid1Price", ""),
        "bid1Size": x.get("bid1Size", ""),
        "ask1Price": x.get("ask1Price", ""),
        "ask1Size": x.get("ask1Size", ""),
        "openInterest": x.get("openInterest", ""),
        "openInterestValue": x.get("openInterestValue", ""),
        "raw_sha256": prov["raw_sha256"],
    }


def normalize_trades(payload: dict, symbol: str, prov: dict) -> list[dict]:
    rows = []
    server_ms = int(payload["time"])
    for x in payload.get("result", {}).get("list", []):
        if x.get("symbol") != symbol:
            continue
        rows.append({
            "kind": "trade",
            "symbol": symbol,
            "source_event_time_ms": int(x["time"]),
            "source_server_time_ms": server_ms,
            "collector_receive_time_utc": prov["response_received_at_utc"],
            "execId": x.get("execId", ""),
            "side": x.get("side", ""),
            "price": x.get("price", ""),
            "size": x.get("size", ""),
            "seq": x.get("seq", ""),
            "isBlockTrade": x.get("isBlockTrade"),
            "isRPITrade": x.get("isRPITrade"),
            "raw_sha256": prov["raw_sha256"],
        })
    rows.sort(key=lambda r: (r["source_event_time_ms"], str(r["seq"]), r["execId"]))
    return rows


def append_once(root: Path, base_url: str = BASE_URL) -> str:
    root.mkdir(parents=True, exist_ok=True)
    forward = root / "forward"
    batch_id = batch_id_now()
    batch = forward / "batches" / batch_id
    batch.mkdir(parents=True, exist_ok=False)

    raw_manifest: list[dict] = []
    ticker_rows: list[dict] = []
    trade_rows: list[dict] = []
    checks: dict[str, dict] = {}

    for symbol in SYMBOLS:
        body, prov = request(
            TICKER_ENDPOINT,
            {"category": "linear", "symbol": symbol},
            base_url=base_url,
        )
        payload = save_raw(batch, f"{symbol}.ticker", body, prov, raw_manifest)
        ticker = normalize_ticker(payload, symbol, prov)
        ticker_rows.append(ticker)

        body, prov = request(
            TRADES_ENDPOINT,
            {"category": "linear", "symbol": symbol, "limit": 50},
            base_url=base_url,
        )
        payload = save_raw(batch, f"{symbol}.trades", body, prov, raw_manifest)
        trades = normalize_trades(payload, symbol, prov)
        trade_rows.extend(trades)

        required_ticker = [
            "markPrice", "indexPrice", "fundingRate", "nextFundingTime",
            "bid1Price", "ask1Price", "openInterest",
        ]
        exec_ids = [r["execId"] for r in trades]
        seqs = [r["seq"] for r in trades]
        event_times = [r["source_event_time_ms"] for r in trades]
        checks[symbol] = {
            "ticker_required_fields_present": all(ticker.get(k) not in ("", None) for k in required_ticker),
            "trade_rows": len(trades),
            "trade_exec_ids_unique": len(exec_ids) == len(set(exec_ids)),
            "trade_sequence_present": bool(seqs) and all(x not in ("", None) for x in seqs),
            "trade_event_time_monotonic": all(a <= b for a, b in zip(event_times, event_times[1:])),
            "seq_min": min((int(x) for x in seqs if str(x).isdigit()), default=None),
            "seq_max": max((int(x) for x in seqs if str(x).isdigit()), default=None),
            "unique_seq_count": len(set(seqs)),
        }
        checks[symbol]["pass"] = (
            checks[symbol]["ticker_required_fields_present"]
            and checks[symbol]["trade_rows"] > 0
            and checks[symbol]["trade_exec_ids_unique"]
            and checks[symbol]["trade_sequence_present"]
            and checks[symbol]["trade_event_time_monotonic"]
        )

    ticker_rows.sort(key=lambda r: r["symbol"])
    trade_rows.sort(key=lambda r: (r["symbol"], r["source_event_time_ms"], str(r["seq"]), r["execId"]))

    ticker_path = batch / "normalized" / "tickers.jsonl"
    trades_path = batch / "normalized" / "trades.jsonl"
    ticker_sha = write_jsonl(ticker_path, ticker_rows)
    trades_sha = write_jsonl(trades_path, trade_rows)

    normalized_manifest = [
        {
            "path": str(ticker_path.relative_to(batch)),
            "sha256": ticker_sha,
            "bytes": ticker_path.stat().st_size,
        },
        {
            "path": str(trades_path.relative_to(batch)),
            "sha256": trades_sha,
            "bytes": trades_path.stat().st_size,
        },
    ]
    manifest_doc = {
        "contract": CONTRACT,
        "batch_id": batch_id,
        "source_base_url": base_url.rstrip("/"),
        "raw_files": sorted(raw_manifest, key=lambda x: x["path"]),
        "normalized_files": normalized_manifest,
    }
    manifest_path = batch / "forward-manifest.json"
    manifest_path.write_bytes(canonical_json(manifest_doc))

    quality_doc = {
        "contract": CONTRACT,
        "batch_id": batch_id,
        "purpose": "forward-integrity-only; strategy performance prohibited",
        "checks": checks,
        "overall_pass": all(v["pass"] for v in checks.values()),
        "created_at_utc": utc_now(),
    }
    quality_path = batch / "forward-quality-report.json"
    quality_path.write_bytes(canonical_json(quality_doc))

    verify_batch(batch)
    if not quality_doc["overall_pass"]:
        raise RuntimeError("BLOCK: forward append quality gate failed")

    log = forward / "append-log.jsonl"
    with log.open("ab") as f:
        f.write(canonical_json({
            "batch_id": batch_id,
            "batch_path": str(batch.relative_to(root)),
            "source_base_url": base_url.rstrip("/"),
            "manifest_sha256": sha256(manifest_path.read_bytes()),
            "quality_sha256": sha256(quality_path.read_bytes()),
            "committed_at_utc": utc_now(),
        }))
    return batch_id


def verify_batch(batch: Path) -> None:
    manifest_path = batch / "forward-manifest.json"
    quality_path = batch / "forward-quality-report.json"
    manifest = json.loads(manifest_path.read_text())
    quality = json.loads(quality_path.read_text())

    for f in manifest["raw_files"]:
        for path_key, hash_key in (("path", "sha256"), ("provenance_path", "provenance_sha256")):
            data = (batch / f[path_key]).read_bytes()
            if sha256(data) != f[hash_key]:
                raise RuntimeError(f"BLOCK: forward SHA mismatch: {f[path_key]}")
    for f in manifest["normalized_files"]:
        data = (batch / f["path"]).read_bytes()
        if sha256(data) != f["sha256"]:
            raise RuntimeError(f"BLOCK: forward normalized SHA mismatch: {f['path']}")

    for p in (batch / "raw").glob("*.provenance.json"):
        prov = json.loads(p.read_text())
        if not prov.get("source_base_url") or not prov.get("response_received_at_utc"):
            raise RuntimeError(f"BLOCK: incomplete forward provenance: {p.name}")

    if not quality.get("overall_pass"):
        raise RuntimeError("BLOCK: forward quality report failed")


def verify_forward(root: Path, min_batches: int = 1) -> None:
    forward = root / "forward"
    log_path = forward / "append-log.jsonl"
    if not log_path.exists():
        raise RuntimeError("BLOCK: missing forward append log")
    lines = [json.loads(x) for x in log_path.read_text().splitlines() if x.strip()]
    if len(lines) < min_batches:
        raise RuntimeError(f"BLOCK: expected at least {min_batches} forward batches, got {len(lines)}")
    ids = [x["batch_id"] for x in lines]
    if len(ids) != len(set(ids)):
        raise RuntimeError("BLOCK: duplicate forward batch id")

    batch_root = forward / "batches"
    dirs = {p.name for p in batch_root.iterdir() if p.is_dir()}
    if dirs != set(ids):
        raise RuntimeError("BLOCK: unlogged or missing forward batch directory")

    for rec in lines:
        batch = batch_root / rec["batch_id"]
        verify_batch(batch)
        manifest_path = batch / "forward-manifest.json"
        quality_path = batch / "forward-quality-report.json"
        if sha256(manifest_path.read_bytes()) != rec["manifest_sha256"]:
            raise RuntimeError(f"BLOCK: append-log manifest mismatch: {rec['batch_id']}")
        if sha256(quality_path.read_bytes()) != rec["quality_sha256"]:
            raise RuntimeError(f"BLOCK: append-log quality mismatch: {rec['batch_id']}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append")
    a.add_argument("--out", required=True)
    a.add_argument("--base-url", default=BASE_URL)
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    v.add_argument("--min-batches", type=int, default=1)
    args = p.parse_args()
    if args.cmd == "append":
        print(append_once(Path(args.out), args.base_url))
    else:
        verify_forward(Path(args.out), args.min_batches)


if __name__ == "__main__":
    main()
