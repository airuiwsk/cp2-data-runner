#!/usr/bin/env python3
"""Acquire frozen T404 CP5 OOS inputs under CP2 raw-first integrity rules.

Data-only. This script MUST NOT compute T404 signals, returns, PnL, Sharpe,
controls, baseline metrics, or any CP5 gate outcome.

Frozen window from research/t404-cp5-validation-plan-v1.md:
2025-12-29T00:00:00Z through 2026-08-31T00:00:00Z required minute,
with 2026-08-31T00:01:00Z as the exclusive minute-grid end.
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

BASE_URL = "https://api.manepa.jp"
START_MS = 1766966400000  # 2025-12-29T00:00:00Z
END_MS = 1788134460000    # 2026-08-31T00:01:00Z exclusive
FIRST_ENTRY_MS = 1767571200000  # 2026-01-05T00:00:00Z
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SURFACES = {
    "tradeable": "/v5/market/kline",
    "mark": "/v5/market/mark-price-kline",
}
CHUNK_MS = 1000 * 60_000
FUNDING_ENDPOINT = "/v5/market/funding/history"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canon(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode()


def request(endpoint: str, params: dict, base: str, user_agent: str):
    q = urllib.parse.urlencode(sorted(params.items()))
    url = f"{base.rstrip('/')}{endpoint}?{q}"
    retryable_ret_codes = {10000, 10006, 10016}
    attempts = []
    for attempt in range(8):
        started = now()
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(req, timeout=30) as h:
                body = h.read()
                status = h.status
        except urllib.error.HTTPError as e:
            body = e.read()
            status = e.code
            attempts.append({"attempt": attempt + 1, "http_status": status})
            if status == 429 and attempt < 7:
                time.sleep(min(8.0, 0.5 * (2 ** attempt)))
                continue
            raise RuntimeError(
                f"fail-closed endpoint={endpoint} HTTP={status} params={params}"
            ) from e
        received = now()
        payload = json.loads(body)
        ret_code = payload.get("retCode")
        attempts.append(
            {"attempt": attempt + 1, "http_status": status, "retCode": ret_code}
        )
        if status == 200 and ret_code == 0:
            prov = {
                "source_venue": "Bybit",
                "source_base_url": base.rstrip("/"),
                "source_endpoint": endpoint,
                "request_parameters": dict(sorted(params.items())),
                "request_started_at_utc": started,
                "response_received_at_utc": received,
                "http_status": status,
                "raw_sha256": sha(body),
                "raw_bytes": len(body),
                "schema_contract_version": "CP2-v1/T404-CP5-OOS-input-v1",
                "performance_computed": False,
                "request_attempts": attempts,
            }
            return body, payload, prov
        if ret_code in retryable_ret_codes and attempt < 7:
            time.sleep(min(8.0, 0.5 * (2 ** attempt)))
            continue
        raise RuntimeError(
            f"fail-closed endpoint={endpoint} HTTP={status} retCode={ret_code} params={params}"
        )
    raise RuntimeError(f"fail-closed retry exhausted endpoint={endpoint} params={params}")


def acquire_bars(root: Path, base: str, manifest: list, quality: dict):
    expected_total = (END_MS - START_MS) // 60_000
    for symbol in SYMBOLS:
        for surface, endpoint in SURFACES.items():
            out = root / "normalized" / f"{symbol}.{surface}.csv"
            out.parent.mkdir(parents=True, exist_ok=True)
            seen = set()
            bad_chunks = []
            rows = 0
            with out.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(
                    ["symbol", "dataset", "start_ms", "open", "high", "low", "close",
                     "volume", "turnover", "raw_sha256"]
                )
                chunk = 0
                for start in range(START_MS, END_MS, CHUNK_MS):
                    end = min(start + CHUNK_MS, END_MS)
                    params = {
                        "category": "linear",
                        "symbol": symbol,
                        "interval": "1",
                        "start": start,
                        "end": end - 1,
                        "limit": 1000,
                    }
                    body, payload, prov = request(
                        endpoint, params, base, "AI-Trading-T404-CP5-OOS/1.0"
                    )
                    name = f"{symbol}.{surface}.{chunk:05d}"
                    rp = root / "raw" / f"{name}.json"
                    pp = root / "raw" / f"{name}.provenance.json"
                    rp.parent.mkdir(parents=True, exist_ok=True)
                    rp.write_bytes(body)
                    pp.write_bytes(canon(prov))
                    manifest.append(
                        {
                            "path": str(rp.relative_to(root)),
                            "sha256": sha(body),
                            "provenance_path": str(pp.relative_to(root)),
                            "provenance_sha256": sha(pp.read_bytes()),
                        }
                    )

                    xs = []
                    for x in payload.get("result", {}).get("list", []):
                        t = int(x[0])
                        if start <= t < end:
                            xs.append(x)
                    xs.sort(key=lambda x: int(x[0]))
                    expected = (end - start) // 60_000
                    grid_ok = len(xs) == expected and all(
                        int(x[0]) == start + i * 60_000 for i, x in enumerate(xs)
                    )
                    if not grid_ok:
                        bad_chunks.append(
                            {
                                "chunk": chunk,
                                "start_ms": start,
                                "end_ms": end,
                                "rows": len(xs),
                                "expected": expected,
                            }
                        )
                    for x in xs:
                        t = int(x[0])
                        if t in seen:
                            raise RuntimeError(f"BLOCK duplicate {symbol} {surface} {t}")
                        seen.add(t)
                        volume = x[5] if surface == "tradeable" and len(x) > 5 else ""
                        turnover = x[6] if surface == "tradeable" and len(x) > 6 else ""
                        w.writerow(
                            [symbol, surface, t, x[1], x[2], x[3], x[4],
                             volume, turnover, prov["raw_sha256"]]
                        )
                        rows += 1
                    chunk += 1
                    time.sleep(0.07)
            quality[f"{symbol}.{surface}"] = {
                "rows": rows,
                "expected_rows": expected_total,
                "first_ms": min(seen) if seen else None,
                "last_ms": max(seen) if seen else None,
                "duplicates": rows - len(seen),
                "bad_chunks": bad_chunks,
                "pass": (
                    rows == expected_total
                    and len(seen) == expected_total
                    and not bad_chunks
                    and (min(seen) if seen else None) == START_MS
                    and (max(seen) if seen else None) == END_MS - 60_000
                ),
            }


def acquire_funding(root: Path, base: str, manifest: list, quality: dict):
    for symbol in SYMBOLS:
        end = END_MS - 1
        page = 0
        events = {}
        while end >= START_MS:
            params = {
                "category": "linear",
                "symbol": symbol,
                "endTime": end,
                "limit": 200,
            }
            body, payload, prov = request(
                FUNDING_ENDPOINT, params, base, "AI-Trading-T404-CP5-Funding/1.0"
            )
            xs = payload.get("result", {}).get("list", [])
            name = f"{symbol}.funding.{page:05d}"
            rp = root / "raw" / f"{name}.json"
            pp = root / "raw" / f"{name}.provenance.json"
            rp.write_bytes(body)
            pp.write_bytes(canon(prov))
            manifest.append(
                {
                    "path": str(rp.relative_to(root)),
                    "sha256": sha(body),
                    "provenance_path": str(pp.relative_to(root)),
                    "provenance_sha256": sha(pp.read_bytes()),
                }
            )
            ts = []
            for x in xs:
                t = int(x["fundingRateTimestamp"])
                ts.append(t)
                if START_MS <= t < END_MS:
                    rate = x.get("fundingRate", "")
                    if t in events and events[t] != rate:
                        raise RuntimeError(
                            f"BLOCK conflicting funding event {symbol} {t}"
                        )
                    events[t] = rate
            if not ts or min(ts) < START_MS:
                break
            new_end = min(ts) - 1
            if new_end >= end:
                raise RuntimeError("BLOCK non-progressing funding pagination")
            end = new_end
            page += 1
            time.sleep(0.07)

        out = root / "normalized" / f"{symbol}.funding.csv"
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["symbol", "funding_time_ms", "funding_rate"])
            for t in sorted(events):
                w.writerow([symbol, t, events[t]])

        times = sorted(events)
        mark_times = set()
        mark_file = root / "normalized" / f"{symbol}.mark.csv"
        with mark_file.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                mark_times.add(int(row["start_ms"]))
        relevant = [t for t in times if FIRST_ENTRY_MS < t < END_MS]
        missing_mark = [t for t in relevant if t not in mark_times]
        quality[f"{symbol}.funding"] = {
            "events": len(times),
            "first_ms": times[0] if times else None,
            "last_ms": times[-1] if times else None,
            "strictly_increasing": all(b > a for a, b in zip(times, times[1:])),
            "in_window": all(START_MS <= t < END_MS for t in times),
            "relevant_events_after_first_entry": len(relevant),
            "funding_events_missing_mark_open": len(missing_mark),
            "pass": (
                bool(times)
                and all(b > a for a, b in zip(times, times[1:]))
                and all(START_MS <= t < END_MS for t in times)
                and not missing_mark
            ),
        }


def acquire(root: Path, base: str):
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    (root / "normalized").mkdir()
    manifest = []
    quality = {}

    acquire_bars(root, base, manifest, quality)
    acquire_funding(root, base, manifest, quality)

    normalized = []
    for path in sorted((root / "normalized").glob("*.csv")):
        normalized.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": sha(path.read_bytes()),
                "bytes": path.stat().st_size,
            }
        )
    q_payload = {
        "contract": "CP2-v1/T404-CP5-OOS-input-v1",
        "window_start_ms": START_MS,
        "window_end_ms_exclusive": END_MS,
        "checks": quality,
        "overall_pass": all(x["pass"] for x in quality.values()),
        "performance_computed": False,
    }
    (root / "quality-report.json").write_bytes(canon(q_payload))
    (root / "input-manifest.json").write_bytes(
        canon(
            {
                "contract": "CP2-v1/T404-CP5-OOS-input-v1",
                "window_start_ms": START_MS,
                "window_end_ms_exclusive": END_MS,
                "raw_files": manifest,
                "normalized_files": normalized,
                "quality_report_sha256": sha((root / "quality-report.json").read_bytes()),
                "performance_computed": False,
            }
        )
    )
    if not q_payload["overall_pass"]:
        raise RuntimeError("BLOCK T404 CP5 OOS integrity gate failed")


def verify(root: Path):
    m = json.loads((root / "input-manifest.json").read_text())
    if m.get("performance_computed") is not False:
        raise RuntimeError("BLOCK manifest performance flag")
    for x in m["raw_files"]:
        if sha((root / x["path"]).read_bytes()) != x["sha256"]:
            raise RuntimeError(f"BLOCK raw SHA mismatch {x['path']}")
        if sha((root / x["provenance_path"]).read_bytes()) != x["provenance_sha256"]:
            raise RuntimeError(f"BLOCK provenance SHA mismatch {x['provenance_path']}")
    for x in m["normalized_files"]:
        if sha((root / x["path"]).read_bytes()) != x["sha256"]:
            raise RuntimeError(f"BLOCK normalized SHA mismatch {x['path']}")
    if sha((root / "quality-report.json").read_bytes()) != m["quality_report_sha256"]:
        raise RuntimeError("BLOCK quality-report SHA mismatch")
    q = json.loads((root / "quality-report.json").read_text())
    if not q.get("overall_pass") or q.get("performance_computed") is not False:
        raise RuntimeError("BLOCK quality report")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["acquire", "verify"])
    p.add_argument("--out", required=True)
    p.add_argument("--base-url", default=BASE_URL)
    a = p.parse_args()
    root = Path(a.out)
    if a.cmd == "acquire":
        acquire(root, a.base_url)
    else:
        verify(root)
