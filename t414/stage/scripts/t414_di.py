#!/usr/bin/env python3
"""T414 source-integrity DI only; computes no returns or economic outcomes."""
from __future__ import annotations
import csv,json
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]; DATA=ROOT/"data/t414"
LEDGER=ROOT/"t414/stage/research/external-leads/XL-20260926-001-timestamp-provenance-ledger-v0.csv"
UNIVERSE=ROOT/"t414/stage/research/external-leads/XL-20260926-001-timestamp-universe-v0.csv"
def D(s):return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)
def U(s):return datetime.fromtimestamp(float(s),tz=timezone.utc)
def ceil5(t):
 b=t.replace(second=0,microsecond=0)
 if t.second or t.microsecond:
  b+=timedelta(minutes=1)
 if b.minute%5:
  b+=timedelta(minutes=5-b.minute%5)
 return b
def present(sym,s):
 p=DATA/f"{sym}-{s.date().isoformat()}.csv"
 if not p.exists():return False
 e=s+timedelta(minutes=5)
 try:return any(s<=U(r["timestamp"])<e for r in csv.DictReader(p.open()))
 except Exception:return False
def complete(t):
 e=ceil5(t);x=e+timedelta(hours=4)
 return all(present(sym,s) for sym in ("XMRUSDT","BTCUSDT") for s in (e,x))
def events():
 out=[]
 for r in csv.DictReader(LEDGER.open()):
  if r["timestamp_quality"]=="Q1" and r["tradability_status"]=="ELIGIBLE_T1" and r["t1_public_at_time"]=="TRUE":
   t=D(r["t1_alert_utc"])
   if D("2022-01-14T00:00:00Z")<=t<D("2025-01-01T00:00:00Z"):out.append(t)
 return out
def main():
 ev=events();ae=[D(r["date_utc"]+"T00:00:00Z") for r in csv.DictReader(UNIVERSE.open())]
 real_ok=sum(complete(t) for t in ev); pool_sizes=[]
 for t in ev:
  d=datetime(t.year,1,1,t.hour,t.minute,t.second,t.microsecond,tzinfo=timezone.utc);n=0
  while d.year==t.year:
   if ((d.weekday()>=5)==(t.weekday()>=5)) and all(abs((d-e).total_seconds())>=604800 for e in ae) and complete(d):n+=1
   d+=timedelta(days=1)
  pool_sizes.append(n)
 report={"trial":"T414","real_events":len(ev),"real_source_complete":real_ok,"placebo_pool_sizes":pool_sizes,"all_placebo_pools_nonempty":all(n>0 for n in pool_sizes),"pass":len(ev)==21 and real_ok==21 and all(n>0 for n in pool_sizes),"performance_computed":False}
 (DATA/"di-report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n");print(json.dumps(report,sort_keys=True))
 raise SystemExit(0 if report["pass"] else 2)
if __name__=="__main__":main()
