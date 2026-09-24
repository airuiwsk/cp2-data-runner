#!/usr/bin/env python3
"""T405 raw-only acquisition. NO signal/return/PnL/Sharpe calculations."""
import hashlib, json, os, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

PRODUCT="FX_BTC_JPY"
START="2026-08-24T00:00:00Z"
END="2026-09-24T00:00:00Z"
BASE="https://api.bitflyer.com/v1/getexecutions"
OUT=Path(os.environ.get("T405_OUT","evidence/t405-bitflyer-raw"))
OUT.mkdir(parents=True,exist_ok=True)
rawdir=OUT/"raw"; rawdir.mkdir(exist_ok=True)
# Optional transport-only resume cursor. It must come from an immutable prior raw artifact;
# it changes neither the frozen sample nor any strategy/performance parameter.
before_env=os.environ.get("T405_BEFORE")
page_offset=int(os.environ.get("T405_PAGE_OFFSET","0"))

def parse_ts(s):
    t=datetime.fromisoformat(s.replace("Z","+00:00"))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)

def fetch_raw(url):
    for attempt in range(8):
        req=urllib.request.Request(url,headers={"User-Agent":"Method-X-T405-raw-acquisition/1.2"})
        try:
            with urllib.request.urlopen(req,timeout=30) as r:
                return r.read(), r.status
        except urllib.error.HTTPError as e:
            if e.code not in (429,500,502,503,504) or attempt==7: raise
            retry_after=e.headers.get("Retry-After")
            delay=float(retry_after) if retry_after and retry_after.replace('.','',1).isdigit() else min(60.0,2.0**attempt)
            print(f"transport retry http={e.code} attempt={attempt+1} sleep={delay}s",flush=True)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError):
            if attempt==7: raise
            delay=min(60.0,2.0**attempt)
            print(f"transport retry network attempt={attempt+1} sleep={delay}s",flush=True)
            time.sleep(delay)
    raise RuntimeError("unreachable")

start=parse_ts(START); end=parse_ts(END)
before=int(before_env) if before_env else None
page=page_offset; seen=set(); min_ts=None; max_ts=None; duplicate_ids=0; records_in_window=0
chunks=[]
while True:
    q={"product_code":PRODUCT,"count":"500"}
    if before is not None: q["before"]=str(before)
    url=BASE+"?"+urllib.parse.urlencode(q)
    body,status=fetch_raw(url)
    sha=hashlib.sha256(body).hexdigest()
    fn=rawdir/f"page-{page:05d}.json"; fn.write_bytes(body)
    data=json.loads(body)
    if not isinstance(data,list): raise RuntimeError("non-list response")
    page_min=None; page_max=None
    for x in data:
        if not all(k in x for k in ("id","side","price","size","exec_date")): raise RuntimeError("missing required field")
        i=int(x["id"]); t=parse_ts(x["exec_date"])
        if i in seen: duplicate_ids+=1
        seen.add(i)
        page_min=t if page_min is None or t<page_min else page_min
        page_max=t if page_max is None or t>page_max else page_max
        min_ts=t if min_ts is None or t<min_ts else min_ts
        max_ts=t if max_ts is None or t>max_ts else max_ts
        if start <= t < end: records_in_window+=1
    chunks.append({"page":page,"url":url,"http_status":status,"bytes":len(body),"sha256":sha,"count":len(data),"min_exec_date":page_min.isoformat() if page_min else None,"max_exec_date":page_max.isoformat() if page_max else None})
    if not data: break
    oldest_id=min(int(x["id"]) for x in data)
    if page_min is not None and page_min < start: break
    if before is not None and oldest_id>=before: raise RuntimeError("pagination did not move backward")
    before=oldest_id; page+=1
    if page>=10000: raise RuntimeError("page safety limit")
    time.sleep(0.12)

acquired_at=datetime.now(timezone.utc)
coverage_start_ok=min_ts is not None and min_ts < start
coverage_end_ok=(before_env is None and acquired_at >= end and max_ts is not None and max_ts >= end)
manifest={
 "trial_id":"T405","mode":"RAW_ONLY_NO_PERFORMANCE","product":PRODUCT,
 "frozen_start":START,"frozen_end_exclusive":END,"acquired_at_utc":acquired_at.isoformat(),
 "resume_before_id":int(before_env) if before_env else None,"page_offset":page_offset,
 "pages":len(chunks),"unique_execution_ids":len(seen),"duplicate_ids_across_pages":duplicate_ids,
 "records_in_frozen_window":records_in_window,
 "observed_min_exec_date":min_ts.isoformat() if min_ts else None,
 "observed_max_exec_date":max_ts.isoformat() if max_ts else None,
 "coverage_start_certified":coverage_start_ok,"coverage_end_certified":coverage_end_ok,
 "full_frozen_window_certified":coverage_start_ok and coverage_end_ok,
 "chunks":chunks
}
mb=json.dumps(manifest,indent=2,sort_keys=True).encode(); (OUT/"provenance.json").write_bytes(mb)
(OUT/"provenance.sha256").write_text(hashlib.sha256(mb).hexdigest()+"  provenance.json\n")
print(json.dumps({k:v for k,v in manifest.items() if k!="chunks"},indent=2))
if not coverage_start_ok:
    print("BLOCKED_DATA_RETENTION_OR_INCOMPLETE: acquisition segment did not reach frozen start",flush=True); raise SystemExit(42)
if acquired_at < end:
    print("PARTIAL_EXPECTED: frozen end is still in the future; preserve this snapshot and reacquire after END",flush=True)
