#!/usr/bin/env python3
"""CP2 integrity-only collector/verifier for Method X v1.0.

No strategy returns, PnL, Sharpe, IC, signals, or optimization are computed.
The default sample window is fixed solely to test the frozen CP2 data contract.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://api.bybit.com"
CONTRACT = "CP2-v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
# Integrity-only fixed sample. This is not an empirical Edge data window.
DEFAULT_START = "2026-09-21T00:00:00Z"
DEFAULT_END = "2026-09-21T00:10:00Z"  # end-exclusive for normalized 1m bars
KLINES = {
    "premium": "/v5/market/premium-index-price-kline",
    "mark": "/v5/market/mark-price-kline",
    "index": "/v5/market/index-price-kline",
    "tradeable": "/v5/market/kline",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ms(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


def canonical_json(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request(endpoint: str, params: dict, timeout: int = 20) -> tuple[bytes, dict]:
    query = urllib.parse.urlencode(sorted(params.items()))
    url = f"{BASE_URL}{endpoint}?{query}"
    started = utc_now()
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Trading-CP2/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        status = resp.status
    received = utc_now()
    parsed = json.loads(body)
    if status != 200 or parsed.get("retCode") != 0:
        raise RuntimeError(f"fail-closed source response: HTTP={status}, retCode={parsed.get('retCode')}")
    provenance = {
        "source_venue": "Bybit",
        "source_endpoint": endpoint,
        "request_parameters": dict(sorted(params.items())),
        "request_started_at_utc": started,
        "response_received_at_utc": received,
        "http_status": status,
        "collector_version_or_commit": "research/cp2_bybit_integrity.py",
        "raw_sha256": sha256(body),
        "raw_bytes": len(body),
        "schema_contract_version": CONTRACT,
    }
    return body, provenance


def save_raw(root: Path, name: str, body: bytes, provenance: dict, manifest: list) -> dict:
    raw = root / "raw" / f"{name}.json"
    meta = root / "raw" / f"{name}.provenance.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(body)
    meta.write_bytes(canonical_json(provenance))
    manifest.append({
        "path": str(raw.relative_to(root)), "sha256": sha256(body), "bytes": len(body),
        "provenance_path": str(meta.relative_to(root)), "provenance_sha256": sha256(meta.read_bytes()),
    })
    return json.loads(body)


def normalize_kline(payload: dict, symbol: str, dataset: str, start_ms: int, end_ms: int, raw_sha: str) -> list[dict]:
    rows = []
    for x in payload["result"]["list"]:
        t = int(x[0])
        if not (start_ms <= t < end_ms):
            continue
        row = {"symbol": symbol, "dataset": dataset, "start_ms": t,
               "open": x[1], "high": x[2], "low": x[3], "close": x[4], "raw_sha256": raw_sha}
        if dataset == "tradeable":
            row.update({"volume": x[5], "turnover": x[6]})
        rows.append(row)
    rows.sort(key=lambda r: r["start_ms"])
    return rows


def quality(rows: list[dict], start_ms: int, end_ms: int) -> dict:
    ts = [r["start_ms"] for r in rows]
    duplicates = sorted({x for x in ts if ts.count(x) > 1})
    expected = list(range(start_ms, end_ms, 60_000))
    missing = sorted(set(expected) - set(ts))
    unexpected = sorted(set(ts) - set(expected))
    monotonic = all(a < b for a, b in zip(ts, ts[1:]))
    return {"rows": len(rows), "duplicates_ms": duplicates, "missing_ms": missing,
            "unexpected_ms": unexpected, "strictly_monotonic": monotonic,
            "pass": not duplicates and not missing and not unexpected and monotonic}


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["symbol", "dataset", "start_ms", "open", "high", "low", "close", "volume", "turnover", "raw_sha256"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def collect(root: Path, start: str, end: str) -> None:
    s, e = ms(start), ms(end)
    if e <= s or e - s > 60 * 60 * 1000:
        raise ValueError("integrity window must be >0 and <=1 hour")
    manifest, reports = [], {}
    root.mkdir(parents=True, exist_ok=False)
    run = {"contract": CONTRACT, "purpose": "integrity-only; strategy performance prohibited",
           "window_start_utc": start, "window_end_exclusive_utc": end, "symbols": list(SYMBOLS),
           "created_at_utc": utc_now()}
    (root / "run.json").write_bytes(canonical_json(run))

    for symbol in SYMBOLS:
        body, prov = request("/v5/market/instruments-info", {"category": "linear", "symbol": symbol})
        save_raw(root, f"{symbol}.instrument", body, prov, manifest)
        time.sleep(0.08)

        # Funding uses a wider source query because the integrity window may contain no settlement.
        body, prov = request("/v5/market/funding/history", {"category": "linear", "symbol": symbol,
                                                            "endTime": e - 1, "limit": 2})
        save_raw(root, f"{symbol}.funding", body, prov, manifest)
        time.sleep(0.08)

        for dataset, endpoint in KLINES.items():
            params = {"category": "linear", "symbol": symbol, "interval": "1",
                      "start": s, "end": e - 1, "limit": 1000}
            body, prov = request(endpoint, params)
            payload = save_raw(root, f"{symbol}.{dataset}", body, prov, manifest)
            rows = normalize_kline(payload, symbol, dataset, s, e, prov["raw_sha256"])
            out = root / "normalized" / f"{symbol}.{dataset}.csv"
            write_csv(out, rows)
            reports[f"{symbol}.{dataset}"] = quality(rows, s, e)
            time.sleep(0.08)

    manifest_doc = {"contract": CONTRACT, "files": sorted(manifest, key=lambda x: x["path"])}
    (root / "manifest.json").write_bytes(canonical_json(manifest_doc))
    report_doc = {"contract": CONTRACT, "checks": reports,
                  "overall_pass": all(x["pass"] for x in reports.values())}
    (root / "quality-report.json").write_bytes(canonical_json(report_doc))
    verify(root)
    if not report_doc["overall_pass"]:
        raise RuntimeError("BLOCK: gap/duplicate/monotonic quality gate failed")


def verify(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text())
    for f in manifest["files"]:
        for path_key, hash_key in (("path", "sha256"), ("provenance_path", "provenance_sha256")):
            data = (root / f[path_key]).read_bytes()
            if sha256(data) != f[hash_key]:
                raise RuntimeError(f"BLOCK: SHA mismatch: {f[path_key]}")
    run = json.loads((root / "run.json").read_text())
    s, e = ms(run["window_start_utc"]), ms(run["window_end_exclusive_utc"])
    # Deterministic rebuild: regenerate normalized CSV bytes only from frozen raw payloads.
    for symbol in run["symbols"]:
        for dataset in KLINES:
            raw_path = root / "raw" / f"{symbol}.{dataset}.json"
            raw = raw_path.read_bytes()
            rows = normalize_kline(json.loads(raw), symbol, dataset, s, e, sha256(raw))
            rebuilt = root / "rebuild" / f"{symbol}.{dataset}.csv"
            write_csv(rebuilt, rows)
            canonical = root / "normalized" / f"{symbol}.{dataset}.csv"
            if rebuilt.read_bytes() != canonical.read_bytes():
                raise RuntimeError(f"BLOCK: nondeterministic rebuild: {symbol}.{dataset}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--out", required=True)
    c.add_argument("--start", default=DEFAULT_START)
    c.add_argument("--end", default=DEFAULT_END)
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    a = p.parse_args()
    if a.cmd == "collect":
        collect(Path(a.out), a.start, a.end)
    else:
        verify(Path(a.out))

if __name__ == "__main__":
    main()
