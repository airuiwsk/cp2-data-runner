#!/usr/bin/env python3
"""Frozen T411 D2 C6-FD evaluator.

Uses the exact frozen FDC001 champion and frozen DSL semantics.
Reads only D2 2017-2020. D3 2021-2025 is never loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import pandas as pd

RAW_SHA="706d4bae5a5d4ff31011f5422df2271824218139045a162bb59ff1e5a8900922"
CHAMPION_JSON_SHA="5891533099ba2fbcd9f65d18440f8db3331a04dc013f122c378ffdaf0cbff251"
CHAMPION_HASH="8dec4676de54bb28a964131b1344f85368f590db53fab9049614e351c8ab9f10"
ONE_WAY_COST=0.0002
NULL_SHIFT=503

def mean(xs):
    return sum(xs)/len(xs)

def run_path(selected, positions, ret, dates):
    strat=[]
    base=[]
    entry_dates=[]
    prev=0
    changes=0
    for t,p in zip(selected,positions):
        r=ret[t]
        if r is None or not math.isfinite(r):
            raise RuntimeError("selected future return missing/nonfinite")
        ch=abs(p-prev)
        changes+=ch
        s=p*r-ONE_WAY_COST*ch
        b=r
        strat.append(s)
        base.append(b)
        entry_dates.append(pd.Timestamp(dates[t+1]))
        prev=p
    if not strat:
        raise RuntimeError("no evaluated intervals")
    if positions[-1]==1:
        strat[-1]-=ONE_WAY_COST
        changes+=1
    base[0]-=ONE_WAY_COST
    base[-1]-=ONE_WAY_COST
    inc=[a-b for a,b in zip(strat,base)]
    return {
      "strategy":strat,
      "baseline":base,
      "incremental":inc,
      "entry_dates":entry_dates,
      "state_changes":changes,
    }

def year_means(values, dates):
    buckets={}
    for x,d in zip(values,dates):
        y=str(pd.Timestamp(d).year)
        buckets.setdefault(y,[]).append(float(x))
    return {y:mean(xs) for y,xs in sorted(buckets.items())}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--frozen-feature-lab",required=True)
    ap.add_argument("--raw",required=True)
    ap.add_argument("--champion",required=True)
    ap.add_argument("--out",default="t411_d2_c6_result.json")
    args=ap.parse_args()

    sys.path.insert(0,args.frozen_feature_lab)
    import dsl
    import fdc001_search_engine as eng

    rawp=Path(args.raw)
    chp=Path(args.champion)
    if hashlib.sha256(rawp.read_bytes()).hexdigest()!=RAW_SHA:
        raise SystemExit("D2 raw SHA mismatch")
    if hashlib.sha256(chp.read_bytes()).hexdigest()!=CHAMPION_JSON_SHA:
        raise SystemExit("champion JSON SHA mismatch")
    champion=json.loads(chp.read_text())
    if champion["expression_hash"]!=CHAMPION_HASH:
        raise SystemExit("champion expression hash mismatch")

    df=pd.read_csv(rawp)
    df["Date"]=pd.to_datetime(df["Date"],errors="raise")
    if not df["Date"].is_monotonic_increasing or not df["Date"].is_unique:
        raise SystemExit("date integrity failure")

    data=eng.build_terminals(df)
    score=dsl.evaluate(champion["normalized_ast"],data)
    real_ret=eng.future_open_returns(df)
    dates=df["Date"].tolist()

    selected=[]
    positions=[]
    finite_count=0
    for t in range(len(df)-2):
        entry=pd.Timestamp(dates[t+1])
        exit_=pd.Timestamp(dates[t+2])
        if entry>=pd.Timestamp("2017-01-01") and exit_<pd.Timestamp("2021-01-01"):
            selected.append(t)
            x=score[t]
            ok=x is not None and math.isfinite(x)
            finite_count+=int(ok)
            positions.append(1 if ok and x>0 else 0)

    n=len(selected)
    coverage=finite_count/n
    long_fraction=sum(positions)/n

    primary_path=run_path(selected,positions,real_ret,dates)
    changes=primary_path["state_changes"]
    changes_per_252=changes/n*252.0

    structural_gates={
      "n_ge_900":n>=900,
      "coverage_ge_0_90":coverage>=0.90,
      "long_fraction_ge_0_10":long_fraction>=0.10,
      "long_fraction_le_0_90":long_fraction<=0.90,
      "state_changes_per_252_le_80":changes_per_252<=80.0,
    }

    strategy_mean=mean(primary_path["strategy"])
    baseline_mean=mean(primary_path["baseline"])
    incremental_mean=mean(primary_path["incremental"])
    strategy_year=year_means(primary_path["strategy"],primary_path["entry_dates"])
    incremental_year=year_means(primary_path["incremental"],primary_path["entry_dates"])
    years=len(strategy_year)
    strategy_positive_years=sum(v>0 for v in strategy_year.values())
    incremental_positive_years=sum(v>0 for v in incremental_year.values())
    strategy_positive_year_fraction=strategy_positive_years/years
    incremental_positive_year_fraction=incremental_positive_years/years

    primary_gates={
      **structural_gates,
      "strategy_mean_net_gt_zero":strategy_mean>0.0,
      "incremental_mean_vs_always_long_gt_zero":incremental_mean>0.0,
      "strategy_positive_year_fraction_gt_0_50":strategy_positive_year_fraction>0.50,
      "incremental_positive_year_fraction_gt_0_50":incremental_positive_year_fraction>0.50,
    }
    primary_pass=all(primary_gates.values())

    null_control={
      "executed":False,
      "shift_observations":NULL_SHIFT,
      "reason":"Primary failed; null control prohibited by preregistration."
    }
    if primary_pass:
        null_ret=eng.circular_shift_returns(real_ret,NULL_SHIFT)
        null_path=run_path(selected,positions,null_ret,dates)
        null_incremental_mean=mean(null_path["incremental"])
        attenuation_pass=abs(null_incremental_mean)<=0.5*abs(incremental_mean)
        null_control={
          "executed":True,
          "shift_observations":NULL_SHIFT,
          "incremental_mean_vs_always_long":null_incremental_mean,
          "attenuation_ratio_abs":(
              abs(null_incremental_mean)/abs(incremental_mean)
              if abs(incremental_mean)>0 else None
          ),
          "pass":bool(attenuation_pass),
        }

    if not primary_pass:
        disposition="CHEAP_REJECT(CR-TEMPORAL)"
    elif not null_control["pass"]:
        disposition="CHEAP_REJECT(CR-NEGCONTROL)"
    else:
        disposition="PROMOTE_TO_EMPIRICAL"

    result={
      "trial_id":"T411",
      "edge_id":"EH-20260926-017",
      "fdc_id":"FDC001",
      "selection_family":"AEDE-ETF-GOLD-DATA-DISCOVERED-STATE-FILTER",
      "champion_expression_hash":CHAMPION_HASH,
      "d2_raw_sha256":RAW_SHA,
      "d2_window":{"start":"2017-01-01","end_exclusive":"2021-01-01"},
      "one_way_cost":ONE_WAY_COST,
      "n":n,
      "coverage":coverage,
      "long_fraction":long_fraction,
      "cash_fraction":1.0-long_fraction,
      "state_changes":changes,
      "state_changes_per_252":changes_per_252,
      "strategy_mean_net":strategy_mean,
      "always_long_mean_net":baseline_mean,
      "incremental_mean_vs_always_long":incremental_mean,
      "strategy_year_mean_net":strategy_year,
      "incremental_year_mean_vs_always_long":incremental_year,
      "strategy_positive_years":strategy_positive_years,
      "incremental_positive_years":incremental_positive_years,
      "calendar_years":years,
      "strategy_positive_year_fraction":strategy_positive_year_fraction,
      "incremental_positive_year_fraction":incremental_positive_year_fraction,
      "primary_gates":primary_gates,
      "primary_pass":primary_pass,
      "null_control":null_control,
      "disposition":disposition,
      "search_multiplicity":{
        "raw_evaluations":5000,
        "unique_expressions":2951,
        "valid_unique_expressions":2762,
        "discovery_eligible_unique":33,
        "null_eligible_unique":8,
        "promoted_champions":1,
      },
      "d3_loaded":False,
      "d3_performance_computed":False,
      "no_rescue":True,
    }
    Path(args.out).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
