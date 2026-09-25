"""FDC001 GLD D0 source/data-integrity preflight only.

Authorized range: [2005-01-01, 2017-01-01).
Forbidden here: D2/D3 acquisition and any performance statistic.
"""
import hashlib, json, sys
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf

START="2005-01-01"
END="2017-01-01"
OUT="fdc001_gld_d0_raw.csv"
META="fdc001_gld_d0_preflight.json"

df=yf.download("GLD",start=START,end=END,auto_adjust=False,actions=False,progress=False)
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
 "fdc_id":"FDC001",
 "instrument":"GLD",
 "authorized_data_state":"D0_ONLY",
 "requested_start":START,
 "requested_end_exclusive":END,
 "rows":int(len(df)),
 "date_min":df["Date"].min().date().isoformat(),
 "date_max":df["Date"].max().date().isoformat(),
 "duplicates":int(df["Date"].duplicated().sum()),
 "monotonic":bool(df["Date"].is_monotonic_increasing),
 "null_counts":{c:int(df[c].isna().sum()) for c in ["Open","High","Low","Close","Volume"]},
 "nonpositive_counts":{c:int((df[c]<=0).sum()) for c in ["Open","High","Low","Close"]},
 "d2_loaded":False,
 "d3_loaded":False,
 "performance_computed":False
}
df.to_csv(OUT,index=False)
raw=open(OUT,"rb").read()
checks["sha256"]=hashlib.sha256(raw).hexdigest()
checks["retrieved_at_utc"]=datetime.now(timezone.utc).isoformat()
checks["pass"]=bool(
  checks["rows"]>=2900
  and checks["date_min"]<="2005-01-05"
  and checks["date_max"]>="2016-12-20"
  and checks["duplicates"]==0
  and checks["monotonic"]
  and all(v==0 for v in checks["null_counts"].values())
  and all(v==0 for v in checks["nonpositive_counts"].values())
)
open(META,"w").write(json.dumps(checks,indent=2,sort_keys=True)+"\n")
print(json.dumps(checks,sort_keys=True))
sys.exit(0 if checks["pass"] else 2)
