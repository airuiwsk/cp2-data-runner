import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
import yfinance as yf

OUT=Path("evidence/t410-qqq-di")
OUT.mkdir(parents=True,exist_ok=True)
df=yf.download("QQQ",start="2007-01-01",end="2026-01-01",auto_adjust=False,actions=False,progress=False)
if isinstance(df.columns,pd.MultiIndex): df.columns=[c[0] for c in df.columns]
df=df.reset_index()
required=["Date","Open","High","Low","Close","Adj Close","Volume"]
missing=[c for c in required if c not in df.columns]
if missing: raise SystemExit("missing columns: "+repr(missing))
df["Date"]=pd.to_datetime(df["Date"],errors="raise")
checks={"rows":int(len(df)),"date_min":df["Date"].min().date().isoformat(),"date_max":df["Date"].max().date().isoformat(),"duplicates":int(df["Date"].duplicated().sum()),"monotonic":bool(df["Date"].is_monotonic_increasing),"open_nulls":int(df["Open"].isna().sum()),"close_nulls":int(df["Close"].isna().sum()),"open_nonpositive":int((df["Open"]<=0).sum()),"close_nonpositive":int((df["Close"]<=0).sum()),"performance_computed":False}
raw=OUT/"t410_qqq_raw.csv"; df.to_csv(raw,index=False)
checks["sha256"]=hashlib.sha256(raw.read_bytes()).hexdigest()
checks["retrieved_at_utc"]=datetime.now(timezone.utc).isoformat()
checks["pass"]=bool(checks["rows"]>4500 and checks["date_min"]<="2007-01-05" and checks["date_max"]>="2025-12-20" and checks["duplicates"]==0 and checks["monotonic"] and checks["open_nulls"]==0 and checks["close_nulls"]==0 and checks["open_nonpositive"]==0 and checks["close_nonpositive"]==0)
(OUT/"t410_qqq_di.json").write_text(json.dumps(checks,indent=2))
print(json.dumps(checks))
sys.exit(0 if checks["pass"] else 2)
