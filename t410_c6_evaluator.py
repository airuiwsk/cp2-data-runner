#!/usr/bin/env python3
"""Frozen T410 C6 evaluator.

Reads only the exact DI-PASS raw CSV. Computes performance only for the frozen
C6 entry window 2007-01-01 through 2018-12-31. It does not compute reserved
2019-2023 CP5 or 2024-2025 performance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pandas as pd

EXPECTED_SHA="fbf237e63bbfd58ca8290e8643bdc11af7289cf6564d125f335e259a8554bf9f"
RAW=Path("evidence/t410-qqq-di/t410_qqq_raw.csv")
OUT=Path("evidence/t410-c6")
OUT.mkdir(parents=True,exist_ok=True)

COST=0.0005
C6_START=pd.Timestamp("2007-01-01")
C6_END=pd.Timestamp("2018-12-31")
MIN_N=2500

raw=RAW.read_bytes()
sha=hashlib.sha256(raw).hexdigest()
if sha!=EXPECTED_SHA:
    raise SystemExit(f"raw SHA mismatch: {sha}")

df=pd.read_csv(RAW)
expected_cols=["Date","Adj Close","Close","High","Low","Open","Volume"]
if list(df.columns)!=expected_cols:
    raise SystemExit("unexpected columns")
df["Date"]=pd.to_datetime(df["Date"],errors="raise")
if not df["Date"].is_monotonic_increasing or not df["Date"].is_unique:
    raise SystemExit("date integrity failure")
if df[["Open","Close"]].isna().any().any():
    raise SystemExit("Open/Close nulls")
if (df[["Open","Close"]]<=0).any().any():
    raise SystemExit("nonpositive Open/Close")

episodes=[]
for i in range(len(df)-1):
    entry_date=df.at[i,"Date"]
    if entry_date<C6_START or entry_date>C6_END:
        continue
    close_t=float(df.at[i,"Close"])
    open_next=float(df.at[i+1,"Open"])
    close_next=float(df.at[i+1,"Close"])
    gross_overnight=open_next/close_t-1.0
    net_overnight=gross_overnight-COST
    intraday_complement=close_next/open_next-1.0
    episodes.append({
      "entry_date":entry_date,
      "gross_overnight":gross_overnight,
      "net_overnight":net_overnight,
      "intraday_complement":intraday_complement,
    })

if not episodes:
    raise SystemExit("no C6 episodes")

ep=pd.DataFrame(episodes)
n=int(len(ep))
mean_gross=float(ep["gross_overnight"].mean())
mean_net=float(ep["net_overnight"].mean())
mean_intraday=float(ep["intraday_complement"].mean())

ep["year"]=ep["entry_date"].dt.year
year_net=ep.groupby("year",sort=True)["net_overnight"].mean()
year_means={str(int(y)):float(v) for y,v in year_net.items()}
positive_years=int((year_net>0).sum())
years=int(len(year_net))
positive_year_fraction=float(positive_years/years)

primary_gates={
  "minimum_n":n>=MIN_N,
  "mean_net_gt_zero":mean_net>0.0,
  "mean_gross_gt_intraday_complement":mean_gross>mean_intraday,
  "positive_year_fraction_gt_0_50":positive_year_fraction>0.50,
}
primary_pass=all(primary_gates.values())

negative_control=None
if primary_pass:
    # Frozen preregistration's same-day Open-to-Close placebo sleeve is the
    # day t+1 intraday complement corresponding to each overnight episode.
    # The same 5bp completed-round-trip friction is applied.
    control_net=ep["intraday_complement"]-COST
    control_mean=float(control_net.mean())
    control_pass=control_mean<mean_net
    negative_control={
      "executed":True,
      "definition":"day t+1 Open-to-Close intraday complement less same 5bp round-trip friction",
      "mean_net":control_mean,
      "pass":bool(control_pass),
    }
else:
    negative_control={
      "executed":False,
      "reason":"Frozen primary gate failed; negative control prohibited by preregistration."
    }

if not primary_pass:
    disposition="CHEAP_REJECT(CR-TEMPORAL)"
elif not negative_control["pass"]:
    disposition="CHEAP_REJECT(CR-NEGCONTROL)"
else:
    disposition="PROMOTE_TO_EMPIRICAL"

result={
  "trial_id":"T410",
  "edge_id":"EH-20260926-016",
  "selection_family":"AEDE-US-ETF-OVERNIGHT-RISK-PREMIUM",
  "raw_sha256":sha,
  "c6_entry_window":{"start":"2007-01-01","end":"2018-12-31"},
  "frozen_cost_round_trip":COST,
  "n":n,
  "mean_gross_overnight":mean_gross,
  "mean_net_overnight":mean_net,
  "mean_intraday_complement":mean_intraday,
  "calendar_year_mean_net":year_means,
  "positive_years":positive_years,
  "calendar_years":years,
  "positive_year_fraction":positive_year_fraction,
  "primary_gates":primary_gates,
  "primary_pass":primary_pass,
  "negative_control":negative_control,
  "disposition":disposition,
  "cp5_reserved_performance_computed":False,
  "later_2024_2025_performance_computed":False,
  "no_rescue":True,
}
(OUT/"t410_c6_result.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
print(json.dumps(result,sort_keys=True))
