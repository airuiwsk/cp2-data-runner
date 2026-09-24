#!/usr/bin/env python3
"""T407/OpenAssetPricing non-performance source probe.

Downloads the current OSAP original-paper portfolio-return table and inspects
only schema, date coverage, predictor presence, and raw provenance. It MUST NOT
compute mean returns, Sharpe, hit rates, cumulative performance, or any other
candidate performance statistic.
"""
import json, hashlib, os, sys
from pathlib import Path

OUT=Path("out/t407-osap-probe")
OUT.mkdir(parents=True, exist_ok=True)

import openassetpricing as oap

client=oap.OpenAP()
df=client.dl_port("op","pandas",["MomSeason"])

# Persist exact returned table before interpretation.
csv_bytes=df.to_csv(index=False).encode("utf-8")
(OUT/"momseason_op.csv").write_bytes(csv_bytes)

cols=[str(c) for c in df.columns]
lower={c.lower():c for c in cols}
date_col=None
for cand in ("date","yyyymm","month"):
    if cand in lower:
        date_col=lower[cand]; break

coverage={"min":None,"max":None}
if date_col is not None and len(df):
    vals=df[date_col].astype(str)
    coverage={"min":str(vals.min()),"max":str(vals.max())}

# Strictly non-performance diagnostics.
meta={
  "package":"openassetpricing",
  "release_list":oap.list_release(),
  "requested_portfolio":"op",
  "requested_predictors":["MomSeason"],
  "rows":int(len(df)),
  "columns":cols,
  "date_column":date_col,
  "date_coverage_raw":coverage,
  "csv_sha256":hashlib.sha256(csv_bytes).hexdigest(),
  "csv_bytes":len(csv_bytes),
  "performance_statistics_computed":False,
  "forbidden_statistics":["mean_return","sharpe","hit_rate","cumulative_return","t_stat"],
}
(OUT/"probe.json").write_text(json.dumps(meta,indent=2,default=str),encoding="utf-8")
print(json.dumps(meta,indent=2,default=str))
