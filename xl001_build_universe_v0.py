#!/usr/bin/env python3
"""Build frozen XL001 timestamp-audit universe v0 from public DefiLlama embeds.

No market data and no performance calculations.
"""
from __future__ import annotations
import datetime as dt
import hashlib, html as htmlmod, json, re, urllib.request
from collections import Counter
from pathlib import Path

URL="https://defillama.com/hacks"
START=dt.datetime(2022,1,14,tzinfo=dt.timezone.utc).timestamp()
END=dt.datetime(2026,9,1,tzinfo=dt.timezone.utc).timestamp()
MIN_USD=10_000_000

def fetch():
    req=urllib.request.Request(URL,headers={"User-Agent":"AI-Trading-universe-builder/1.0"})
    with urllib.request.urlopen(req,timeout=30) as r:
        raw=r.read()
    return raw

def parse_records(raw):
    text=htmlmod.unescape(raw.decode("utf-8",errors="replace"))
    frags=re.findall(r'\{[^{}]{0,400}?"name"\s*:\s*"[^"]+"[^{}]{0,1400}?\}',text)
    out=[]
    seen=set()
    for f in frags:
        if '"date"' not in f or '"classification"' not in f or '"technique"' not in f:
            continue
        try:
            x=json.loads(f)
        except Exception:
            continue
        key=(str(x.get("name")),str(x.get("date")),str(x.get("classification")),str(x.get("technique")))
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out

def iso(ts):
    return dt.datetime.fromtimestamp(int(ts),tz=dt.timezone.utc).date().isoformat()

def main():
    raw=fetch()
    rows=parse_records(raw)
    selected=[]
    for x in rows:
        try:
            ts=int(x.get("date"))
            amt=float(x.get("amountUsd"))
        except Exception:
            continue
        if not (START <= ts < END):
            continue
        if amt < MIN_USD:
            continue
        selected.append({
          "name":x.get("name"),
          "date_utc":iso(ts),
          "date_unix":ts,
          "amountUsd":amt,
          "classification":x.get("classification"),
          "technique":x.get("technique"),
          "target":x.get("target"),
          "chains":x.get("chains"),
          "bridge":x.get("bridge"),
          "language":x.get("language"),
          "t0_flow":None,
          "t1_alert":None,
          "t2_official":None,
          "timestamp_quality":None,
          "timestamp_sources":[],
          "tradability_status":"UNASSESSED"
        })
    selected.sort(key=lambda x:(x["date_unix"],str(x["name"])))
    years=Counter(x["date_utc"][:4] for x in selected)
    classes=Counter(str(x["classification"]) for x in selected)
    targets=Counter(str(x["target"]) for x in selected)
    out={
      "lead_id":"XL-20260926-001",
      "universe_version":"v0",
      "frozen_rule":{
        "source_url":URL,
        "start_inclusive":"2022-01-14",
        "end_exclusive":"2026-09-01",
        "minimum_amount_usd":MIN_USD,
        "market_outcome_filter":False
      },
      "source_sha256":hashlib.sha256(raw).hexdigest(),
      "source_unique_records":len(rows),
      "selected_event_count":len(selected),
      "year_counts":dict(sorted(years.items())),
      "classification_counts":dict(sorted(classes.items())),
      "target_counts":dict(sorted(targets.items())),
      "market_data_loaded":False,
      "market_performance_computed":False,
      "events":selected
    }
    Path("xl001-timestamp-universe-v0.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
      "selected_event_count":len(selected),
      "year_counts":out["year_counts"],
      "classification_counts":out["classification_counts"],
      "target_counts":out["target_counts"],
      "first_events":[{"date":x["date_utc"],"name":x["name"],"amountUsd":x["amountUsd"]} for x in selected[:10]],
      "last_events":[{"date":x["date_utc"],"name":x["name"],"amountUsd":x["amountUsd"]} for x in selected[-10:]],
      "market_data_loaded":False,
      "market_performance_computed":False
    },sort_keys=True))

if __name__=="__main__":
    main()
