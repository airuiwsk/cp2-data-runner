#!/usr/bin/env python3
"""Acquire only preregistered T402 5-minute open-interest inputs.

No signal, return, PnL, percentile, threshold, or strategy metric is computed.
Window and interval are frozen by EH-20260923-003 / T402.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path

BASE_URL="https://api.manepa.jp"
START_MS=1704067200000
END_MS=1767225600000
INTERVAL_MS=5*60*1000
LIMIT=200
STEP_MS=INTERVAL_MS*LIMIT
SYMBOLS=("BTCUSDT","ETHUSDT")
ENDPOINT="/v5/market/open-interest"

def now(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def sha(b): return hashlib.sha256(b).hexdigest()
def canon(x): return (json.dumps(x,sort_keys=True,separators=(",",":"))+"\n").encode()

def req(params,base):
    q=urllib.parse.urlencode(sorted(params.items())); url=f"{base.rstrip('/')}{ENDPOINT}?{q}"
    started=now(); r=urllib.request.Request(url,headers={"User-Agent":"AI-Trading-CP2-T402/1.0"})
    with urllib.request.urlopen(r,timeout=30) as h: body=h.read(); status=h.status
    received=now(); p=json.loads(body)
    if status!=200 or p.get("retCode")!=0:
        raise RuntimeError(f"fail-closed HTTP={status} retCode={p.get('retCode')}")
    prov={"source_venue":"Bybit","source_base_url":base.rstrip("/"),"source_endpoint":ENDPOINT,
          "request_parameters":dict(sorted(params.items())),"request_started_at_utc":started,
          "response_received_at_utc":received,"http_status":status,"raw_sha256":sha(body),
          "raw_bytes":len(body),"schema_contract_version":"CP2-v1/T402-oi-v1"}
    return body,prov

def acquire(root:Path,base:str):
    root.mkdir(parents=True,exist_ok=False); manifest=[]; quality={}
    for symbol in SYMBOLS:
        out=root/"normalized"/f"{symbol}.open_interest_5m.csv"; out.parent.mkdir(parents=True,exist_ok=True)
        rows=0; seen=set(); bad=[]
        with out.open("w",newline="",encoding="utf-8") as f:
            w=csv.writer(f,lineterminator="\n"); w.writerow(["symbol","timestamp_ms","open_interest","raw_sha256"])
            chunk=0
            for s in range(START_MS,END_MS,STEP_MS):
                e=min(s+STEP_MS,END_MS)
                params={"category":"linear","symbol":symbol,"intervalTime":"5min",
                        "startTime":s,"endTime":e-1,"limit":LIMIT}
                body,prov=req(params,base)
                name=f"{symbol}.oi5m.{chunk:05d}"
                rp=root/"raw"/f"{name}.json"; pp=root/"raw"/f"{name}.provenance.json"; rp.parent.mkdir(parents=True,exist_ok=True)
                rp.write_bytes(body); pp.write_bytes(canon(prov))
                manifest.append({"path":str(rp.relative_to(root)),"sha256":sha(body),
                    "provenance_path":str(pp.relative_to(root)),"provenance_sha256":sha(pp.read_bytes())})
                p=json.loads(body); xs=[]
                for x in p.get("result",{}).get("list",[]):
                    t=int(x["timestamp"])
                    if s<=t<e: xs.append((t,x["openInterest"]))
                xs.sort()
                expected=(e-s)//INTERVAL_MS
                contiguous=(len(xs)==expected and all(t==s+i*INTERVAL_MS for i,(t,_) in enumerate(xs)))
                if not contiguous:
                    bad.append({"chunk":chunk,"start_ms":s,"end_ms":e,"rows":len(xs),"expected":expected,
                                "first_ms":xs[0][0] if xs else None,"last_ms":xs[-1][0] if xs else None})
                for t,oi in xs:
                    if t in seen: raise RuntimeError(f"BLOCK duplicate {symbol} {t}")
                    seen.add(t); w.writerow([symbol,t,oi,prov["raw_sha256"]]); rows+=1
                chunk+=1; time.sleep(0.04)
        expected_total=(END_MS-START_MS)//INTERVAL_MS
        quality[symbol]={"rows":rows,"expected_rows":expected_total,"bad_chunks":bad,
                         "strict_grid_pass":not bad and rows==expected_total,
                         "duplicates":rows-len(seen),"pass":not bad and rows==expected_total and rows==len(seen)}
    (root/"manifest.json").write_bytes(canon({"contract":"CP2-v1/T402-oi-v1","files":manifest}))
    (root/"quality-report.json").write_bytes(canon({"checks":quality,"overall_pass":all(v["pass"] for v in quality.values())}))
    if not all(v["pass"] for v in quality.values()): raise RuntimeError("BLOCK OI continuity gate failed")

def verify(root:Path):
    m=json.loads((root/"manifest.json").read_text())
    for x in m["files"]:
        if sha((root/x["path"]).read_bytes())!=x["sha256"]: raise RuntimeError(f"BLOCK raw SHA {x['path']}")
        if sha((root/x["provenance_path"]).read_bytes())!=x["provenance_sha256"]: raise RuntimeError(f"BLOCK provenance SHA {x['provenance_path']}")
    q=json.loads((root/"quality-report.json").read_text())
    if not q["overall_pass"]: raise RuntimeError("BLOCK OI quality report")
    for symbol in SYMBOLS:
        path=root/"normalized"/f"{symbol}.open_interest_5m.csv"
        with path.open(newline="",encoding="utf-8") as f:
            rows=list(csv.DictReader(f))
        ts=[int(r["timestamp_ms"]) for r in rows]
        exp=list(range(START_MS,END_MS,INTERVAL_MS))
        if ts!=exp: raise RuntimeError(f"BLOCK normalized OI grid {symbol}")
        if any(float(r["open_interest"])<=0 for r in rows): raise RuntimeError(f"BLOCK nonpositive OI {symbol}")

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("cmd",choices=["acquire","verify"])
    p.add_argument("--out",required=True); p.add_argument("--base-url",default=BASE_URL); a=p.parse_args()
    root=Path(a.out)
    acquire(root,a.base_url) if a.cmd=="acquire" else verify(root)
