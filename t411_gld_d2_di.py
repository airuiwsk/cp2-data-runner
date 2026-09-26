#!/usr/bin/env python3
"""T411 GLD D2-only non-performance data-integrity acquisition.

Acquires exactly the sealed D2 date range after T411 preregistration.
No strategy return, PnL, IC, Sharpe, hit rate, or D3 data is computed/loaded.
"""
from __future__ import annotations
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT=Path("evidence/t411-gld-d2-di")
OUT.mkdir(parents=True,exist_ok=True)

df=yf.download(
    "GLD",
    start="2017-01-01",
    end="2021-01-01",
    auto_adjust=False,
    actions=False,
    progress=False,
)
if isinstance(df.columns,pd.MultiIndex):
    df.columns=[c[0] for c in df.columns]
df=df.reset_index()

required=["Date","Open","High","Low","Close","Adj Close","Volume"]
missing=[c for c in required if c not in df.columns]
if missing:
    raise SystemExit("missing columns: "+repr(missing))
df=df[required].copy()
df["Date"]=pd.to_datetime(df["Date"],errors="raise")

checks={
  "trial_id":"T411",
  "fdc_id":"FDC001",
  "symbol":"GLD",
  "source":"Yahoo Finance via yfinance",
  "requested_start":"2017-01-01",
  "requested_end_exclusive":"2021-01-01",
  "rows":int(len(df)),
  "date_min":df["Date"].min().date().isoformat(),
  "date_max":df["Date"].max().date().isoformat(),
  "duplicates":int(df["Date"].duplicated().sum()),
  "monotonic":bool(df["Date"].is_monotonic_increasing),
  "performance_computed":False,
  "d3_loaded":False,
}
for c in ["Open","High","Low","Close","Adj Close","Volume"]:
    x=pd.to_numeric(df[c],errors="coerce")
    checks[f"{c}_nulls"]=int(x.isna().sum())
for c in ["Open","High","Low","Close"]:
    checks[f"{c}_nonpositive"]=int((pd.to_numeric(df[c],errors="coerce")<=0).sum())

raw=OUT/"t411_gld_d2_raw.csv"
df.to_csv(raw,index=False)
checks["sha256"]=hashlib.sha256(raw.read_bytes()).hexdigest()
checks["retrieved_at_utc"]=datetime.now(timezone.utc).isoformat()

checks["pass"]=bool(
    checks["rows"]>=950
    and checks["date_min"]<="2017-01-05"
    and checks["date_max"]>="2020-12-28"
    and checks["date_max"]<="2020-12-31"
    and checks["duplicates"]==0
    and checks["monotonic"]
    and all(checks[f"{c}_nulls"]==0 for c in ["Open","High","Low","Close","Adj Close","Volume"])
    and all(checks[f"{c}_nonpositive"]==0 for c in ["Open","High","Low","Close"])
)
(OUT/"t411_gld_d2_di.json").write_text(json.dumps(checks,indent=2,sort_keys=True)+"\n")
print(json.dumps(checks,sort_keys=True))
sys.exit(0 if checks["pass"] else 2)
