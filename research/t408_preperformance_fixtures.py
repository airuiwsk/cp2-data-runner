"""T408 non-performance fixtures only. MUST NOT compute returns/signals/performance."""
import hashlib, json
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf

START, END = "2007-01-01", "2024-01-01"
df = yf.download("SPY", start=START, end=END, auto_adjust=False, actions=False, progress=False)
assert len(df) >= 4000, f"row_count={len(df)}"
# Normalize yfinance MultiIndex without inspecting price relationships.
if isinstance(df.columns, pd.MultiIndex):
    df.columns = [c[0] for c in df.columns]
required = {"Open","High","Low","Close","Adj Close","Volume"}
assert required.issubset(df.columns), f"missing={required-set(df.columns)}"
idx = pd.DatetimeIndex(df.index)
assert idx.is_monotonic_increasing and idx.is_unique
assert idx.tz is None, "unexpected timezone-aware daily index"
assert str(idx.min().date()) == "2007-01-03"
assert str(idx.max().date()) == "2023-12-29"
assert pd.api.types.is_numeric_dtype(df["Close"])
assert int(df["Close"].isna().sum()) == 0
# Source sentinel/category compatibility: daily SPY rows, calendar-month grouping possible.
periods = idx.to_period("M")
assert periods.nunique() >= 200
assert all(int((periods == p).sum()) >= 1 for p in periods.unique())
raw = df.to_csv().encode()
out = {
  "trial_id":"T408", "fixture_status":"PASS", "performance_computed":False,
  "rows":len(df), "first_date":str(idx.min().date()), "last_date":str(idx.max().date()),
  "columns":list(df.columns), "index_timezone":"naive", "unique_dates":True,
  "ascending_dates":True, "null_close":0, "monthly_buckets":int(periods.nunique()),
  "retrieved_at_utc":datetime.now(timezone.utc).isoformat(),
  "raw_csv_sha256":hashlib.sha256(raw).hexdigest(),
  "do_not_infer":"No return, signal, edge, benchmark, hit-rate, or candidate-performance statistic was computed."
}
print(json.dumps(out, indent=2))
