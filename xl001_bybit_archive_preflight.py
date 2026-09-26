#!/usr/bin/env python3
"""Non-performance Bybit public historical archive availability preflight.

No return/PnL/edge statistic is computed.
"""
from __future__ import annotations
import gzip
import hashlib
import io
import json
import urllib.request
from pathlib import Path

SYMBOLS=["XMRUSDT","BTCUSDT","ZECUSDT"]
DATES=["2022-02-01","2023-01-01","2024-01-01","2025-01-01","2026-01-01","2026-09-24"]
BASE="https://public.bybit.com/trading"

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"AI-Trading-availability-preflight/1.0"})
    with urllib.request.urlopen(req,timeout=60) as r:
        raw=r.read()
        code=getattr(r,"status",200)
        headers=dict(r.headers.items())
    return code,headers,raw

def inspect_gz_csv(raw):
    dec=gzip.decompress(raw)
    # Schema/row-count only. Do not parse price changes or construct returns.
    text=dec.decode("utf-8",errors="replace")
    lines=text.splitlines()
    header=lines[0].split(",") if lines else []
    return {
        "compressed_bytes":len(raw),
        "decompressed_bytes":len(dec),
        "line_count":len(lines),
        "data_row_count":max(0,len(lines)-1),
        "header":header,
        "compressed_sha256":hashlib.sha256(raw).hexdigest(),
        "decompressed_sha256":hashlib.sha256(dec).hexdigest(),
    }

def main():
    report={
      "lead_id":"XL-20260926-001",
      "stage":"NON_PERFORMANCE_BYBIT_PUBLIC_ARCHIVE_PREFLIGHT",
      "performance_computed":False,
      "source":"public.bybit.com/trading",
      "symbols":{}
    }
    for sym in SYMBOLS:
        rows=[]
        for d in DATES:
            url=f"{BASE}/{sym}/{sym}{d}.csv.gz"
            try:
                code,headers,raw=fetch(url)
                meta=inspect_gz_csv(raw)
                rows.append({"date":d,"url":url,"http_status":code,**meta})
            except Exception as exc:
                rows.append({"date":d,"url":url,"error":str(exc)})
        report["symbols"][sym]=rows

    report["pass_requirements"]={
      "xmr_anchor_files_ge_5":sum("data_row_count" in x for x in report["symbols"]["XMRUSDT"])>=5,
      "btc_anchor_files_ge_5":sum("data_row_count" in x for x in report["symbols"]["BTCUSDT"])>=5,
      "xmr_2022_available":any(x.get("date")=="2022-02-01" and x.get("data_row_count",0)>0 for x in report["symbols"]["XMRUSDT"]),
      "xmr_2026_available":any(x.get("date")=="2026-09-24" and x.get("data_row_count",0)>0 for x in report["symbols"]["XMRUSDT"]),
    }
    report["status"]="PASS" if all(report["pass_requirements"].values()) else "FAIL"
    Path("xl001-bybit-archive-preflight.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
      "status":report["status"],
      "performance_computed":False,
      "pass_requirements":report["pass_requirements"],
      "availability":{s:[{"date":x["date"],"rows":x.get("data_row_count"),"error":x.get("error")} for x in xs] for s,xs in report["symbols"].items()}
    },sort_keys=True))
    if report["status"]!="PASS":
        raise SystemExit(2)

if __name__=="__main__":
    main()
