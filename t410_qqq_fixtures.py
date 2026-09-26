#!/usr/bin/env python3
"""T410 pre-performance structural fixtures.

Consumes the exact DI-PASS raw CSV and checks only schema/date/type/source
identity and frozen-window structural eligibility. No return, PnL, hit-rate,
Sharpe, IC, or mean performance is computed.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import pandas as pd

EXPECTED_SHA="fbf237e63bbfd58ca8290e8643bdc11af7289cf6564d125f335e259a8554bf9f"
RAW=Path("evidence/t410-qqq-di/t410_qqq_raw.csv")
OUT=Path("evidence/t410-qqq-fixtures")
OUT.mkdir(parents=True,exist_ok=True)

raw_bytes=RAW.read_bytes()
sha=hashlib.sha256(raw_bytes).hexdigest()
if sha!=EXPECTED_SHA:
    raise SystemExit(f"raw SHA mismatch: {sha} != {EXPECTED_SHA}")

df=pd.read_csv(RAW)
expected_cols=["Date","Adj Close","Close","High","Low","Open","Volume"]
checks={}
checks["exact_columns"]=list(df.columns)==expected_cols
checks["rows"]=int(len(df))
checks["raw_sha256"]=sha

df["Date"]=pd.to_datetime(df["Date"],errors="raise")
checks["date_min"]=df["Date"].min().date().isoformat()
checks["date_max"]=df["Date"].max().date().isoformat()
checks["duplicates"]=int(df["Date"].duplicated().sum())
checks["strictly_increasing"]=bool(df["Date"].is_monotonic_increasing and checks["duplicates"]==0)

for c in ["Open","Close","Adj Close","High","Low","Volume"]:
    s=pd.to_numeric(df[c],errors="coerce")
    checks[f"{c}_numeric_nulls"]=int(s.isna().sum())

checks["open_positive"]=bool((df["Open"]>0).all())
checks["close_positive"]=bool((df["Close"]>0).all())
checks["adj_close_differs_from_close_rows"]=int(((df["Adj Close"]-df["Close"]).abs()>1e-12).sum())
checks["raw_price_semantics_sentinel"]=checks["adj_close_differs_from_close_rows"]>0

# Structural episode counts only. No price arithmetic.
dates=df["Date"]
c6_entry=(dates>=pd.Timestamp("2007-01-01")) & (dates<=pd.Timestamp("2018-12-31"))
cp5_entry=(dates>=pd.Timestamp("2019-01-01")) & (dates<=pd.Timestamp("2023-12-31"))
later=(dates>=pd.Timestamp("2024-01-01")) & (dates<=pd.Timestamp("2025-12-31"))
# Every entry except the dataset's final row has a next-session row.
next_exists=pd.Series([True]*(len(df)-1)+[False],index=df.index)
checks["c6_complete_episode_count"]=int((c6_entry & next_exists).sum())
checks["cp5_reserved_complete_episode_count"]=int((cp5_entry & next_exists).sum())
checks["later_untouched_row_count"]=int(later.sum())
checks["c6_min_n_structural_pass"]=checks["c6_complete_episode_count"]>=2500
checks["cp5_min_n_structural_pass"]=checks["cp5_reserved_complete_episode_count"]>=1000

checks["performance_computed"]=False
checks["pass"]=bool(
    checks["exact_columns"]
    and checks["rows"]==4780
    and checks["date_min"]=="2007-01-03"
    and checks["date_max"]=="2025-12-31"
    and checks["strictly_increasing"]
    and all(checks[f"{c}_numeric_nulls"]==0 for c in ["Open","Close","Adj Close","High","Low","Volume"])
    and checks["open_positive"]
    and checks["close_positive"]
    and checks["raw_price_semantics_sentinel"]
    and checks["c6_min_n_structural_pass"]
    and checks["cp5_min_n_structural_pass"]
)
(OUT/"t410_qqq_fixtures.json").write_text(json.dumps(checks,indent=2,sort_keys=True)+"\n")
print(json.dumps(checks,sort_keys=True))
raise SystemExit(0 if checks["pass"] else 2)
