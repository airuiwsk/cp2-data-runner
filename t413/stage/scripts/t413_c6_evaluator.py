#!/usr/bin/env python3
"""T413 corrected C6 evaluator. Only change from T412 is Unix-second parsing for Bybit archive timestamps. CP5 unsupported."""
from __future__ import annotations
import csv, json, random
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LEDGER=ROOT/"research/external-leads/XL-20260926-001-timestamp-provenance-ledger-v0.csv"
UNIVERSE=ROOT/"research/external-leads/XL-20260926-001-timestamp-universe-v0.csv"
DATA=ROOT/"data/t413"
SEED=20260926
COST=.002
SETS=1000

def D(s): return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)
def U(s): return datetime.fromtimestamp(float(s),tz=timezone.utc)
def ceil5(t):
    b=t.replace(second=0,microsecond=0)
    if t.second or t.microsecond or b.minute%5: b+=timedelta(minutes=(5-b.minute%5)%5)
    return b
def events():
    a=[]
    for r in csv.DictReader(LEDGER.open()):
        if r["timestamp_quality"]=="Q1" and r["tradability_status"]=="ELIGIBLE_T1" and r["t1_public_at_time"]=="TRUE":
            t=D(r["t1_alert_utc"])
            if D("2022-01-14T00:00:00Z")<=t<D("2025-01-01T00:00:00Z"): a.append(t)
    assert len(a)==21
    return a
def all_dates():
    return [D(r["date_utc"]+"T00:00:00Z") for r in csv.DictReader(UNIVERSE.open())]
def pool(t,all_e):
    d=datetime(t.year,1,1,t.hour,t.minute,t.second,t.microsecond,tzinfo=timezone.utc); a=[]
    while d.year==t.year:
        if ((d.weekday()>=5)==(t.weekday()>=5)) and all(abs((d-e).total_seconds())>=604800 for e in all_e): a.append(d)
        d+=timedelta(days=1)
    return a
_cache={}
def trades(sym,day):
    k=(sym,day)
    if k in _cache:return _cache[k]
    p=DATA/f"{sym}-{day}.csv"
    z=[]
    for r in csv.DictReader(p.open()):
        z.append((U(r["timestamp"]),float(r["price"]),float(r["size"])))
    _cache[k]=z; return z
def vwap(sym,s):
    e=s+timedelta(minutes=5); z=[]
    for day in {s.date().isoformat(),(e-timedelta(microseconds=1)).date().isoformat()}:
        z += [(p,q) for t,p,q in trades(sym,day) if s<=t<e]
    assert z
    return sum(p*q for p,q in z)/sum(q for _,q in z)
def ep(t):
    e=ceil5(t); x=e+timedelta(hours=4)
    a=vwap("XMRUSDT",e); b=vwap("XMRUSDT",x); c=vwap("BTCUSDT",e); d=vwap("BTCUSDT",x)
    xr=b/a-1; br=d/c-1
    return xr-COST,xr-br
def avg(x):return sum(x)/len(x)
def main():
    real=events(); ae=all_dates(); rng=random.Random(SEED)
    pools=[pool(t,ae) for t in real]; assert all(pools)
    obs=[ep(t) for t in real]
    net=avg([x[0] for x in obs]); res=avg([x[1] for x in obs]); hit=sum(x[0]>0 for x in obs)/len(obs)
    pm=[]
    for _ in range(SETS): pm.append(avg([ep(rng.choice(p))[1] for p in pools]))
    p95=sorted(pm)[949]
    g=[len(obs)>=20,net>0,res>0,hit>.55,res>p95]
    print(json.dumps({"trial":"T413","scope":"C6_ONLY","N":len(obs),"mean_xmr_net":net,"mean_residual":res,"positive_net_fraction":hit,"placebo_p95":p95,"seed":SEED,"sets":SETS,"cost":COST,"pass":all(g),"cp5_opened":False},indent=2,sort_keys=True))
if __name__=="__main__":main()
