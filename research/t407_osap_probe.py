#!/usr/bin/env python3
"""T407/OpenAssetPricing non-performance deployability + source preflight.

Forbidden: any return mean, Sharpe, hit rate, t-stat, cumulative return, or
comparison of realized return values. Allowed: source/schema/date coverage,
missingness, portfolio labels, and constituent counts needed for execution-cost
feasibility.
"""
import json, hashlib
from pathlib import Path
import pandas as pd
import openassetpricing as oap

OUT=Path("out/t407-osap-probe")
OUT.mkdir(parents=True, exist_ok=True)

client=oap.OpenAP()
df=client.dl_port("op","pandas",["MomSeason","MomOffSeason"])
csv_bytes=df.to_csv(index=False).encode("utf-8")
(OUT/"momseason_controls_op.csv").write_bytes(csv_bytes)

df["date"]=pd.to_datetime(df["date"], errors="coerce")
sample=df[(df["date"]>=pd.Timestamp("2009-01-01")) & (df["date"]<=pd.Timestamp("2024-12-31"))]
ls=sample[sample["port"].astype(str)=="LS"]

def constituent_stats(g):
    out={}
    for col in ("Nlong","Nshort"):
        s=pd.to_numeric(g[col],errors="coerce").dropna()
        out[col]={
          "min": None if s.empty else float(s.min()),
          "median": None if s.empty else float(s.median()),
          "max": None if s.empty else float(s.max())
        }
    return out

per_signal={}
for sig,g in ls.groupby("signalname"):
    per_signal[str(sig)]={
      "ls_rows":int(len(g)),
      "date_min":None if g.empty else g["date"].min().strftime("%Y-%m-%d"),
      "date_max":None if g.empty else g["date"].max().strftime("%Y-%m-%d"),
      "missing_ret_rows":int(g["ret"].isna().sum()),
      "constituent_counts":constituent_stats(g)
    }

meta={
  "package":"openassetpricing",
  "requested_portfolio":"op",
  "requested_predictors":["MomSeason","MomOffSeason"],
  "all_rows":int(len(df)),
  "columns":[str(c) for c in df.columns],
  "all_date_min":df["date"].min().strftime("%Y-%m-%d"),
  "all_date_max":df["date"].max().strftime("%Y-%m-%d"),
  "portfolio_labels":sorted([str(x) for x in df["port"].dropna().unique()]),
  "prospective_c6_candidate_window_probe":"2009-01-01..2024-12-31",
  "ls_nonperformance_metadata":per_signal,
  "csv_sha256":hashlib.sha256(csv_bytes).hexdigest(),
  "csv_bytes":len(csv_bytes),
  "performance_statistics_computed":False,
  "forbidden_statistics":["mean_return","sharpe","hit_rate","cumulative_return","t_stat","return_quantiles"]
}
(OUT/"probe.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
print(json.dumps(meta,indent=2))
