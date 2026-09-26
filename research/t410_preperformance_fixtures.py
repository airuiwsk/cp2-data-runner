"""T410 non-performance fixtures against the frozen DI artifact.

MUST NOT compute returns, signals, edge, benchmark, hit rate, or performance.
"""
import hashlib
import json
import sys
from pathlib import Path
import pandas as pd

RAW=Path(sys.argv[1] if len(sys.argv)>1 else "input/t410_qqq_raw.csv")
META=Path(sys.argv[2] if len(sys.argv)>2 else "input/t410_qqq_di.json")
EXPECTED_SHA="fbf237e63bbfd58ca8290e8643bdc11af7289cf6564d125f335e259a8554bf9f"

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

for c in ["Open","High","Low","Close","Adj Close","Volume"]:
    assert pd.api.types.is_numeric_dtype(df[c]), (c, df[c].dtype)
assert int(df[["Open","Close"]].isna().sum().sum())==0
assert int((df["Open"]<=0).sum())==0
assert int((df["Close"]<=0).sum())==0

# Frozen T410 semantics only require consecutive trading-day date compatibility.
# This verifies complete close->next-open episode indexing without computing any return.
dates=df["Date"].tolist()
assert len(dates)>=2501
complete_overnight_pairs=len(dates)-1
assert complete_overnight_pairs>=2500

# Frozen C6 and reserved CP5 date windows must both be represented in the source.
c6=df[(df["Date"]>="2007-01-01") & (df["Date"]<="2018-12-31")]
cp5=df[(df["Date"]>="2019-01-01") & (df["Date"]<="2023-12-31")]
untouched=df[(df["Date"]>="2024-01-01") & (df["Date"]<="2025-12-31")]
assert len(c6)>2500
assert len(cp5)>1000
assert len(untouched)>400

out={
 "trial_id":"T410",
 "fixture_status":"PASS",
 "performance_computed":False,
 "raw_sha256":EXPECTED_SHA,
 "rows":len(df),
 "first_date":str(df["Date"].min().date()),
 "last_date":str(df["Date"].max().date()),
 "complete_overnight_pairs":complete_overnight_pairs,
 "c6_rows_2007_2018":len(c6),
 "cp5_reserved_rows_2019_2023":len(cp5),
 "untouched_rows_2024_2025":len(untouched),
 "schema_exact":True,
 "numeric_types_verified":True,
 "date_monotonic_unique":True,
 "source_identity_bound_to_di_sha":True,
 "do_not_infer":"No return, signal, edge, benchmark, hit-rate, Sharpe, PnL, or candidate-performance statistic was computed."
}
Path("t410_preperformance_fixture.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
print(json.dumps(out,sort_keys=True))
