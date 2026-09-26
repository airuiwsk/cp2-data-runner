#!/usr/bin/env python3
"""T411 D2 structural/feature fixtures only.

No future open-to-open return, PnL, IC, Sharpe, hit rate, or strategy mean is
computed. Uses exact frozen FDC001 champion and frozen engine DSL semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import pandas as pd

EXPECTED_RAW_SHA="706d4bae5a5d4ff31011f5422df2271824218139045a162bb59ff1e5a8900922"
EXPECTED_CHAMPION_SHA="5891533099ba2fbcd9f65d18440f8db3331a04dc013f122c378ffdaf0cbff251"
EXPECTED_CHAMPION_HASH="8dec4676de54bb28a964131b1344f85368f590db53fab9049614e351c8ab9f10"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--frozen-feature-lab",required=True)
    ap.add_argument("--raw",required=True)
    ap.add_argument("--champion",required=True)
    ap.add_argument("--out",default="t411_d2_fixtures.json")
    args=ap.parse_args()

    sys.path.insert(0,args.frozen_feature_lab)
    import dsl
    import fdc001_search_engine as eng

    raw_path=Path(args.raw)
    champ_path=Path(args.champion)

    if hashlib.sha256(raw_path.read_bytes()).hexdigest()!=EXPECTED_RAW_SHA:
        raise SystemExit("D2 raw SHA mismatch")
    if hashlib.sha256(champ_path.read_bytes()).hexdigest()!=EXPECTED_CHAMPION_SHA:
        raise SystemExit("champion JSON SHA mismatch")

    champ=json.loads(champ_path.read_text())
    if champ["expression_hash"]!=EXPECTED_CHAMPION_HASH:
        raise SystemExit("champion expression hash mismatch")

    df=pd.read_csv(raw_path)
    df["Date"]=pd.to_datetime(df["Date"],errors="raise")
    data=eng.build_terminals(df)
    score=dsl.evaluate(champ["normalized_ast"],data)

    dates=df["Date"].tolist()
    selected=[]
    for t in range(len(df)-2):
        entry=pd.Timestamp(dates[t+1])
        exit_=pd.Timestamp(dates[t+2])
        if entry>=pd.Timestamp("2017-01-01") and exit_<pd.Timestamp("2021-01-01"):
            selected.append(t)

    finite=[]
    positions=[]
    for t in selected:
        x=score[t]
        ok=x is not None and math.isfinite(x)
        finite.append(ok)
        positions.append(1 if ok and x>0 else 0)

    n=len(selected)
    finite_count=sum(finite)
    coverage=finite_count/n if n else 0.0
    long_fraction=sum(positions)/n if n else 0.0

    prev=0
    changes=0
    for p in positions:
        changes+=abs(p-prev)
        prev=p
    if positions and positions[-1]==1:
        changes+=1
    changes_per_252=changes/n*252.0 if n else float("inf")

    # Diagnostics only; not gates and not market-outcome statistics.
    range1=data["range1"]
    range_sign_counts={"positive":0,"zero":0,"negative":0,"missing":0}
    for t in selected:
        j=t-10
        if j<0 or range1[j] is None or not math.isfinite(range1[j]):
            range_sign_counts["missing"]+=1
        elif range1[j]>0:
            range_sign_counts["positive"]+=1
        elif range1[j]<0:
            range_sign_counts["negative"]+=1
        else:
            range_sign_counts["zero"]+=1

    vchg=data["volume_chg1"]
    denominator_diagnostics={
      "abs_lt_1e_12":0,
      "abs_lt_1e_6":0,
      "abs_lt_1e_4":0,
      "missing":0,
    }
    for t in selected:
        v=vchg[t]
        if v is None or not math.isfinite(v):
            denominator_diagnostics["missing"]+=1
            continue
        a=abs(v)
        denominator_diagnostics["abs_lt_1e_12"]+=int(a<1e-12)
        denominator_diagnostics["abs_lt_1e_6"]+=int(a<1e-6)
        denominator_diagnostics["abs_lt_1e_4"]+=int(a<1e-4)

    gates={
      "n_ge_900":n>=900,
      "coverage_ge_0_90":coverage>=0.90,
      "long_fraction_ge_0_10":long_fraction>=0.10,
      "long_fraction_le_0_90":long_fraction<=0.90,
      "state_changes_per_252_le_80":changes_per_252<=80.0,
    }
    out={
      "trial_id":"T411",
      "fdc_id":"FDC001",
      "stage":"D2_NON_PERFORMANCE_FEATURE_FIXTURES",
      "raw_sha256":EXPECTED_RAW_SHA,
      "champion_sha256":EXPECTED_CHAMPION_SHA,
      "champion_expression_hash":EXPECTED_CHAMPION_HASH,
      "evaluated_interval_count":n,
      "finite_score_count":finite_count,
      "coverage":coverage,
      "long_fraction":long_fraction,
      "cash_fraction":1.0-long_fraction,
      "state_changes_including_final_exit":changes,
      "state_changes_per_252":changes_per_252,
      "range_sign_diagnostic":range_sign_counts,
      "volume_change_denominator_diagnostic":denominator_diagnostics,
      "structural_gates":gates,
      "pass":all(gates.values()),
      "future_returns_computed":False,
      "performance_computed":False,
      "d3_loaded":False,
    }
    Path(args.out).write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps(out,sort_keys=True))
    raise SystemExit(0 if out["pass"] else 2)

if __name__=="__main__":
    main()
