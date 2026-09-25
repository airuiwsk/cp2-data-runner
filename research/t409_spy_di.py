import hashlib, json, sys
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf

OUT="t409_spy_raw.csv"
META="t409_spy_di.json"

# Execution trigger only; frozen DI semantics unchanged.
df=yf.download("SPY",start="2007-01-01",end="2026-01-01",auto_adjust=False,actions=False,progress=False)
if isinstance(df.columns,pd.MultiIndex):
    df.columns=[c[0] for c in df.columns]
df=df.reset_index()
required=["Date","Open","High","Low","Close","Adj Close","Volume"]
missing=[c for c in required if c not in df.columns]
if missing: raise SystemExit("missing columns: "+repr(missing))
df["Date"]=pd.to_datetime(df["Date"],errors="raise")
checks={
 "rows":int(len(df)),
 "date_min":df["Date"].min().date().isoformat(),
 "date_max":df["Date"].max().date().isoformat(),
 "duplicates":int(df["Date"].duplicated().sum()),
 "monotonic":bool(df["Date"].is_monotonic_increasing),
 "close_nulls":int(df["Close"].isna().sum()),
 "close_nonpositive":int((df["Close"]<=0).sum()),
 "performance_computed":False
}
df.to_csv(OUT,index=False)
raw=open(OUT,"rb").read()
checks["sha256"]=hashlib.sha256(raw).hexdigest()
checks["retrieved_at_utc"]=datetime.now(timezone.utc).isoformat()
checks["pass"]=bool(checks["rows"]>4000 and checks["date_min"]<="2007-01-05" and checks["date_max"]>="2025-12-20" and checks["duplicates"]==0 and checks["monotonic"] and checks["close_nulls"]==0 and checks["close_nonpositive"]==0)
open(META,"w").write(json.dumps(checks,indent=2))
print(json.dumps(checks))
sys.exit(0 if checks["pass"] else 2)
# DI trigger 2026-09-26T04:53+09:00 — no performance semantics changed
