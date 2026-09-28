#!/usr/bin/env python3
"""Fetch frozen-scope Bybit public trade archives needed by T413 C6.

This script performs acquisition only. It does not compute returns, PnL,
Sharpe, IC, hit-rate, or any other performance statistic.
"""
from __future__ import annotations
import csv, io, os, sys, zipfile, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LEDGER=ROOT/"research/external-leads/XL-20260926-001-timestamp-provenance-ledger-v0.csv"
UNIVERSE=ROOT/"research/external-leads/XL-20260926-001-timestamp-universe-v0.csv"
OUT=ROOT/"data/t413"
BASE="https://public.bybit.com/trading"
SYMS=("XMRUSDT","BTCUSDT")

def D(s:str)->datetime:
    return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)

def ceil5(t:datetime)->datetime:
    b=t.replace(second=0,microsecond=0)
    if t.second or t.microsecond or b.minute%5:
        b+=timedelta(minutes=(5-b.minute%5)%5)
    return b

def real_events():
    xs=[]
    for r in csv.DictReader(LEDGER.open()):
        if r["timestamp_quality"]=="Q1" and r["tradability_status"]=="ELIGIBLE_T1" and r["t1_public_at_time"]=="TRUE":
            t=D(r["t1_alert_utc"])
            if D("2022-01-14T00:00:00Z")<=t<D("2025-01-01T00:00:00Z"):
                xs.append(t)
    assert len(xs)==21
    return xs

def all_event_dates():
    return [D(r["date_utc"]+"T00:00:00Z") for r in csv.DictReader(UNIVERSE.open())]

def placebo_pool(t,all_e):
    d=datetime(t.year,1,1,t.hour,t.minute,t.second,t.microsecond,tzinfo=timezone.utc)
    out=[]
    while d.year==t.year:
        if ((d.weekday()>=5)==(t.weekday()>=5)) and all(abs((d-e).total_seconds())>=604800 for e in all_e):
            out.append(d)
        d+=timedelta(days=1)
    return out

def needed_days():
    ev=real_events(); ae=all_event_dates()
    ts=set(ev)
    for t in ev:
        ts.update(placebo_pool(t,ae))
    days=set()
    for t in ts:
        e=ceil5(t); x=e+timedelta(hours=4)
        days.add(e.date().isoformat())
        days.add((e+timedelta(minutes=5)-timedelta(microseconds=1)).date().isoformat())
        days.add(x.date().isoformat())
        days.add((x+timedelta(minutes=5)-timedelta(microseconds=1)).date().isoformat())
    return sorted(days)

def archive_url(sym,day):
    return f"{BASE}/{sym}/{sym}{day}.csv.gz"

def fetch_one(sym,day):
    OUT.mkdir(parents=True,exist_ok=True)
    dst=OUT/f"{sym}-{day}.csv"
    if dst.exists() and dst.stat().st_size>0:
        return "exists"
    url=archive_url(sym,day)
    try:
        with urllib.request.urlopen(url,timeout=60) as r:
            raw=r.read()
    except Exception as e:
        print(f"FETCH_FAIL {sym} {day} {url}: {e}",file=sys.stderr)
        return "fail"
    import gzip
    try:
        data=gzip.decompress(raw)
    except Exception as e:
        print(f"GZIP_FAIL {sym} {day}: {e}",file=sys.stderr)
        return "fail"
    dst.write_bytes(data)
    return "fetched"

def main():
    days=needed_days()
    print(f"needed_days={len(days)} performance_computed=false")
    ok=fail=0
    for sym in SYMS:
        for day in days:
            s=fetch_one(sym,day)
            if s=="fail": fail+=1
            else: ok+=1
    print(f"files_ok={ok} files_fail={fail} performance_computed=false")
    if fail:
        raise SystemExit(2)

if __name__=="__main__":
    main()
