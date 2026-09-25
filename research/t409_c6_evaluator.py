"""T409 authoritative CP4 C6 evaluator.

Frozen semantics:
- exact DI raw SHA;
- C6 entry periods 2007-01 through 2023-12;
- entry = close of second-last trading day of month;
- exit = close of third trading day of next month;
- net episode = exit/entry - 1 - 0.001;
- complement = gross close-to-close return from previous TOM episode exit
  (third trading day of current month) to current TOM entry;
- yearly condition = fraction of entry calendar years whose arithmetic mean
  monthly net TOM episode return is > 0;
- negative control only if all primary conditions pass: shift both entry and
  exit five trading observations earlier; same 10bp round-trip cost.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
import pandas as pd

EXPECTED_SHA="ae45a7ba87ac10882cf6135afeb75aec58c0e391b51e14917501ecc028fc3c66"
RAW=Path(sys.argv[1] if len(sys.argv)>1 else "input/t409_spy_raw.csv")
raw=RAW.read_bytes()
if hashlib.sha256(raw).hexdigest()!=EXPECTED_SHA:
    raise SystemExit("raw SHA mismatch")

df=pd.read_csv(RAW)
df["Date"]=pd.to_datetime(df["Date"],errors="raise")
if not df["Date"].is_monotonic_increasing or not df["Date"].is_unique:
    raise SystemExit("date integrity failure")
if df["Close"].isna().any() or (df["Close"]<=0).any():
    raise SystemExit("close integrity failure")

df["Month"]=df["Date"].dt.to_period("M")
groups={p:g.copy() for p,g in df.groupby("Month",sort=True)}
price=dict(zip(df["Date"],df["Close"].astype(float)))
dates=df["Date"].tolist()
pos={d:i for i,d in enumerate(dates)}

def next_month(p):
    return p+1

def ep(p):
    g=groups.get(p)
    n=groups.get(next_month(p))
    if g is None or n is None or len(g)<2 or len(n)<3:
        return None
    entry=g["Date"].iloc[-2]
    exit_=n["Date"].iloc[2]
    return entry,exit_

periods=[]
p=pd.Period("2007-01","M")
end=pd.Period("2023-12","M")
while p<=end:
    periods.append(p)
    p+=1

episodes=[]
for p in periods:
    z=ep(p)
    if z is None:
        continue
    entry,exit_=z
    net=price[exit_]/price[entry]-1.0-0.001
    episodes.append({"period":p,"entry":entry,"exit":exit_,"net":float(net)})

n=len(episodes)
mean_net=sum(x["net"] for x in episodes)/n

# Complement interval for each month after the first available previous episode:
# previous episode exits on the third trading day of current month; current
# episode enters on the second-last trading day of current month.
complements=[]
for i in range(1,len(episodes)):
    current=episodes[i]
    previous=episodes[i-1]
    start=previous["exit"]
    end_=current["entry"]
    if start>=end_:
        raise SystemExit("invalid complement ordering")
    complements.append(float(price[end_]/price[start]-1.0))
mean_complement=sum(complements)/len(complements)

by_year={}
for x in episodes:
    by_year.setdefault(x["period"].year,[]).append(x["net"])
year_means={y:sum(v)/len(v) for y,v in by_year.items()}
positive_years=sum(v>0 for v in year_means.values())
positive_year_fraction=positive_years/len(year_means)

primary_conditions={
 "minimum_n":n>=190,
 "mean_net_positive":mean_net>0,
 "mean_net_gt_complement":mean_net>mean_complement,
 "positive_year_fraction_gt_half":positive_year_fraction>0.5,
}
primary_pass=all(primary_conditions.values())

control_mean=None
control_pass=None
if primary_pass:
    control=[]
    for x in episodes:
        ie=pos[x["entry"]]-5
        ix=pos[x["exit"]]-5
        if ie<0 or ix<0:
            raise SystemExit("negative-control date unavailable")
        ce=dates[ie]; cx=dates[ix]
        control.append(float(price[cx]/price[ce]-1.0-0.001))
    control_mean=sum(control)/len(control)
    control_pass=control_mean<mean_net

final_pass=bool(primary_pass and control_pass)
out={
 "trial_id":"T409",
 "stage":"CP4_C6",
 "performance_computed":True,
 "raw_sha256":EXPECTED_SHA,
 "c6_period_start":"2007-01",
 "c6_period_end":"2023-12",
 "n":n,
 "mean_net_episode_return":mean_net,
 "complement_n":len(complements),
 "mean_complement_return":mean_complement,
 "calendar_years":len(year_means),
 "positive_calendar_years":positive_years,
 "positive_year_fraction":positive_year_fraction,
 "primary_conditions":primary_conditions,
 "primary_pass":primary_pass,
 "negative_control_computed":primary_pass,
 "negative_control_mean_net_return":control_mean,
 "negative_control_pass":control_pass,
 "c6_pass":final_pass,
 "disposition":"PROMOTE_TO_EMPIRICAL" if final_pass else "CHEAP_REJECT(CR-TEMPORAL)",
 "no_rescue":True
}
Path("t409_c6_result.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
print(json.dumps(out,sort_keys=True))
