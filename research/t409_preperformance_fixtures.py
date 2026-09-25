"""T409 non-performance fixtures against the frozen DI artifact.

MUST NOT compute returns, signals, edge, benchmark, hit rate, or performance.
"""
import hashlib
import json
import sys
from pathlib import Path
import pandas as pd

RAW=Path(sys.argv[1] if len(sys.argv)>1 else "input/t409_spy_raw.csv")
META=Path(sys.argv[2] if len(sys.argv)>2 else "input/t409_spy_di.json")
EXPECTED_SHA="ae45a7ba87ac10882cf6135afeb75aec58c0e391b51e14917501ecc028fc3c66"

raw=RAW.read_bytes()
assert hashlib.sha256(raw).hexdigest()==EXPECTED_SHA
meta=json.loads(META.read_text())
assert meta["pass"] is True
assert meta["performance_computed"] is False
assert meta["sha256"]==EXPECTED_SHA

df=pd.read_csv(RAW)
required=["Date","Open","High","Low","Close","Adj Close","Volume"]
assert list(df.columns)==required, df.columns.tolist()
df["Date"]=pd.to_datetime(df["Date"],errors="raise")
assert len(df)==4780
assert str(df["Date"].min().date())=="2007-01-03"
assert str(df["Date"].max().date())=="2025-12-31"
assert df["Date"].is_monotonic_increasing
assert df["Date"].is_unique
assert pd.api.types.is_numeric_dtype(df["Close"])
assert int(df["Close"].isna().sum())==0
assert int((df["Close"]<=0).sum())==0

# Calendar/date-only compatibility for the frozen turn-of-month rule.
df["Month"]=df["Date"].dt.to_period("M")
groups={p:g["Date"].tolist() for p,g in df.groupby("Month",sort=True)}
assert len(groups)==228
assert min(len(v) for v in groups.values())>=15

def next_month(p):
    return p+1

def episode_dates(start_period,end_period):
    rows=[]
    p=start_period
    while p<=end_period:
        dates=groups.get(p,[])
        nxt=groups.get(next_month(p),[])
        if len(dates)>=2 and len(nxt)>=3:
            entry=dates[-2]
            final_day=dates[-1]
            exit_=nxt[2]
            # Negative control: both entry and exit shifted five trading observations earlier
            # in the combined chronological date index. Date existence only; no prices used.
            rows.append((p,entry,final_day,exit_))
        p+=1
    return rows

c6=episode_dates(pd.Period("2007-01","M"),pd.Period("2023-12","M"))
cp5=episode_dates(pd.Period("2024-01","M"),pd.Period("2025-11","M"))
# 2025-12 cannot have a 2026-01 exit inside the frozen acquisition range.
assert len(c6)>=190
assert len(cp5)>=20

all_dates=df["Date"].tolist()
pos={d:i for i,d in enumerate(all_dates)}
for _,entry,_,exit_ in c6+cp5:
    assert pos[entry]>=5 and pos[exit_]>=5
    _=all_dates[pos[entry]-5]
    _=all_dates[pos[exit_]-5]

out={
 "trial_id":"T409",
 "fixture_status":"PASS",
 "performance_computed":False,
 "raw_sha256":EXPECTED_SHA,
 "rows":len(df),
 "first_date":str(df["Date"].min().date()),
 "last_date":str(df["Date"].max().date()),
 "calendar_months":len(groups),
 "minimum_trading_days_in_month":min(len(v) for v in groups.values()),
 "c6_complete_date_episodes":len(c6),
 "cp5_complete_date_episodes_within_acquisition":len(cp5),
 "negative_control_date_shift_available":True,
 "do_not_infer":"No return, signal, edge, benchmark, hit-rate, or candidate-performance statistic was computed."
}
Path("t409_preperformance_fixture.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
print(json.dumps(out,sort_keys=True))
