#!/usr/bin/env python3
"""Parse-shape probe for public DefiLlama hack records.

No market data or performance statistics.
"""
from __future__ import annotations
import collections, hashlib, html as htmlmod, json, re, urllib.request
from pathlib import Path

URL="https://defillama.com/hacks"

def main():
    req=urllib.request.Request(URL,headers={"User-Agent":"AI-Trading-public-source-parser/1.0"})
    with urllib.request.urlopen(req,timeout=30) as r:
        raw=r.read()
    text=htmlmod.unescape(raw.decode("utf-8",errors="replace"))

    frags=re.findall(r'\{[^{}]{0,400}?"name"\s*:\s*"[^"]+"[^{}]{0,1400}?\}',text)
    rows=[]
    failures=0
    for f in frags:
        if '"date"' not in f or '"classification"' not in f or '"technique"' not in f:
            continue
        try:
            x=json.loads(f)
            rows.append(x)
        except Exception:
            failures+=1

    key_counts=collections.Counter()
    for x in rows:
        key_counts.update(x.keys())

    # Deduplicate only for source-shape diagnostics; raw source remains untouched.
    unique={}
    for x in rows:
        k=(str(x.get("name")),str(x.get("date")),str(x.get("classification")),str(x.get("technique")))
        unique[k]=x

    samples=[]
    for x in list(unique.values())[:10]:
        samples.append({k:x.get(k) for k in sorted(x.keys())})

    report={
      "lead_id":"XL-20260926-001",
      "stage":"DEFILLAMA_PUBLIC_RECORD_PARSE_PROBE",
      "market_data_loaded":False,
      "market_performance_computed":False,
      "source_url":URL,
      "source_sha256":hashlib.sha256(raw).hexdigest(),
      "candidate_fragments":len(frags),
      "parsed_rows":len(rows),
      "parse_failures":failures,
      "unique_rows":len(unique),
      "key_frequency":dict(sorted(key_counts.items())),
      "samples":samples,
    }
    report["status"]="PASS" if len(unique)>=1000 and failures<=10 else "PARTIAL"
    Path("xl001-defillama-parse-probe.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
      "status":report["status"],
      "candidate_fragments":report["candidate_fragments"],
      "parsed_rows":report["parsed_rows"],
      "parse_failures":report["parse_failures"],
      "unique_rows":report["unique_rows"],
      "key_frequency":report["key_frequency"],
      "sample_names_dates":[{"name":x.get("name"),"date":x.get("date")} for x in samples],
      "market_data_loaded":False,
      "market_performance_computed":False,
    },sort_keys=True))

if __name__=="__main__":
    main()
