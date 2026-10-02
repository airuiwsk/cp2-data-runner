#!/usr/bin/env python3
"""T414 source acquisition only. Missing public archives are recorded and left for DI eligibility."""
from __future__ import annotations
import csv,gzip,json,urllib.request
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
LEDGER=ROOT/"t414/stage/research/external-leads/XL-20260926-001-timestamp-provenance-ledger-v0.csv"
UNIVERSE=ROOT/"t414/stage/research/external-leads/XL-20260926-001-timestamp-universe-v0.csv"
OUT=ROOT/"data/t414"; BASE="https://public.bybit.com/trading"; SYMS=("XMRUSDT","BTCUSDT")
def D(s):return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)
def ceil5(t):
 b=t.replace(second=0,microsecond=0)
 if t.second or t.microsecond or b.minute%5:b+=timedelta(minutes=(5-b.minute%5)%5)
 return b
def events():
 out=[]
 for r in csv.DictReader(LEDGER.open()):
  if r["timestamp_quality"]=="Q1" and r["tradability_status"]=="ELIGIBLE_T1" and r["t1_public_at_time"]=="TRUE":
   t=D(r["t1_alert_utc"])
   if D("2022-01-14T00:00:00Z")<=t<D("2025-01-01T00:00:00Z"):out.append(t)
 assert len(out)==21;return out
def all_dates():return [D(r["date_utc"]+"T00:00:00Z") for r in csv.DictReader(UNIVERSE.open())]
def candidates(t,ae):
 d=datetime(t.year,1,1,t.hour,t.minute,t.second,t.microsecond,tzinfo=timezone.utc)
 while d.year==t.year:
  if ((d.weekday()>=5)==(t.weekday()>=5)) and all(abs((d-e).total_seconds())>=604800 for e in ae):yield d
  d+=timedelta(days=1)
def needed_days():
 ev=events();ae=all_dates();ts=set(ev)
 for t in ev:ts.update(candidates(t,ae))
 out=set()
 for t in ts:
  e=ceil5(t);out.add(e.date().isoformat());out.add((e+timedelta(hours=4)).date().isoformat())
 return sorted(out)
def main():
 OUT.mkdir(parents=True,exist_ok=True);missing=[];ok=0;ds=needed_days()
 for sym in SYMS:
  for day in ds:
   dst=OUT/f"{sym}-{day}.csv"
   if dst.exists() and dst.stat().st_size:ok+=1;continue
   url=f"{BASE}/{sym}/{sym}{day}.csv.gz"
   try:
    with urllib.request.urlopen(url,timeout=90) as r:raw=r.read()
    dst.write_bytes(gzip.decompress(raw));ok+=1
   except Exception as e:missing.append({"symbol":sym,"day":day,"error":str(e)})
 report={"trial":"T414","needed_days":len(ds),"files_ok":ok,"missing_count":len(missing),"missing":missing,"performance_computed":False}
 (OUT/"acquisition-report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
 print(json.dumps({"trial":"T414","needed_days":len(ds),"files_ok":ok,"missing_count":len(missing),"performance_computed":False},sort_keys=True))
if __name__=="__main__":main()
