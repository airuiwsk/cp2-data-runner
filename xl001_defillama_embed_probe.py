#!/usr/bin/env python3
"""Probe public DefiLlama hacks page embedded data structure.

No market data. No return/PnL statistics.
"""
from __future__ import annotations
import hashlib, html as htmlmod, json, re, urllib.request
from pathlib import Path

URL="https://defillama.com/hacks"
SENTINELS=["Ronin","Nomad","WazirX","DMM","Bitget"]

def fetch():
    req=urllib.request.Request(URL,headers={"User-Agent":"AI-Trading-source-structure-probe/1.0"})
    with urllib.request.urlopen(req,timeout=30) as r:
        raw=r.read()
    return raw

def snippets(text,needle,radius=500):
    out=[]
    start=0
    low=text.lower(); nlow=needle.lower()
    while True:
        i=low.find(nlow,start)
        if i<0: break
        out.append(text[max(0,i-radius):min(len(text),i+len(needle)+radius)])
        start=i+len(needle)
        if len(out)>=3: break
    return out

def field_count(text,field):
    pats=[
      f'"{field}":',
      f'\\"{field}\\":',
      f'&quot;{field}&quot;:',
    ]
    return sum(text.count(p) for p in pats)

def main():
    raw=fetch()
    text=raw.decode("utf-8",errors="replace")
    unescaped=htmlmod.unescape(text)
    rep={
      "lead_id":"XL-20260926-001",
      "stage":"DEFILLAMA_PUBLIC_EMBED_STRUCTURE_PROBE",
      "market_data_loaded":False,
      "market_performance_computed":False,
      "source_url":URL,
      "source_sha256":hashlib.sha256(raw).hexdigest(),
      "source_bytes":len(raw),
      "contains_next_f":"self.__next_f.push" in text,
      "script_tag_count":len(re.findall(r"<script\b",text,re.I)),
      "field_counts":{f:field_count(unescaped,f) for f in ["name","date","amount","classification","technique","source","returnedFunds","defillamaId"]},
      "sentinels":{},
    }
    for s in SENTINELS:
        ss=snippets(unescaped,s)
        rep["sentinels"][s]={
          "occurrences":unescaped.lower().count(s.lower()),
          "snippet_count":len(ss),
          "snippets":[re.sub(r"\s+"," ",x)[:1200] for x in ss],
        }

    # Heuristic: identify JSON-like object fragments containing name/date/amount.
    # This is only source-shape discovery; no market outcomes are involved.
    candidates=re.findall(r'\{[^{}]{0,300}?"name"\s*:\s*"[^"]+"[^{}]{0,900}?\}',unescaped)
    shaped=[]
    for c in candidates:
        if '"date"' in c and ('"amount"' in c or '"classification"' in c):
            shaped.append(c)
    rep["heuristic_record_fragments"]=len(shaped)
    rep["heuristic_samples"]=shaped[:3]
    rep["status"]="PASS" if all(rep["sentinels"][s]["occurrences"]>0 for s in SENTINELS) else "PARTIAL"
    Path("xl001-defillama-embed-probe.json").write_text(json.dumps(rep,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
      "status":rep["status"],
      "source_sha256":rep["source_sha256"],
      "field_counts":rep["field_counts"],
      "sentinel_occurrences":{k:v["occurrences"] for k,v in rep["sentinels"].items()},
      "heuristic_record_fragments":rep["heuristic_record_fragments"],
      "market_data_loaded":False,
      "market_performance_computed":False,
    },sort_keys=True))

if __name__=="__main__":
    main()
