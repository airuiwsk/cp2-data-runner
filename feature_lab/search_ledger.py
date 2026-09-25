"""Append-only Feature Search Ledger helpers.

One row is preserved per raw candidate evaluation. Duplicate expression hashes are
allowed and intentionally retained so adaptive search effort cannot be hidden.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REQUIRED={
 "fdc_id","evaluation_index","expression_hash","normalized_ast","generator",
 "parent_hashes","random_seed","valid","invalid_reason","complexity",
 "discovery_fold_summary","turnover_summary","cost_summary",
 "redundancy_cluster","selected_as_champion","evaluated_at_utc"
}


def validate_row(row):
    missing=REQUIRED-set(row)
    if missing:
        raise ValueError("missing ledger fields: "+",".join(sorted(missing)))
    if not isinstance(row["evaluation_index"],int) or row["evaluation_index"]<0:
        raise ValueError("evaluation_index must be non-negative integer")
    h=str(row["expression_hash"])
    if len(h)!=64:
        raise ValueError("expression_hash must be sha256 hex")
    return True


def write_jsonl(rows,path):
    seen_indices=set()
    out=[]
    for row in rows:
        validate_row(row)
        key=(row["fdc_id"],row["evaluation_index"])
        if key in seen_indices:
            raise ValueError(f"duplicate evaluation index: {key}")
        seen_indices.add(key)
        out.append(json.dumps(row,sort_keys=True,separators=(",",":")))
    Path(path).write_text("\n".join(out)+("\n" if out else ""))


def summarize(rows):
    for r in rows:
        validate_row(r)
    hashes=[r["expression_hash"] for r in rows]
    gens=Counter(r["generator"] for r in rows)
    return {
      "raw_expression_evaluations":len(rows),
      "unique_expression_hashes":len(set(hashes)),
      "duplicate_evaluations":len(rows)-len(set(hashes)),
      "generator_raw_evaluations":dict(sorted(gens.items())),
      "champion_rows":sum(bool(r["selected_as_champion"]) for r in rows),
    }
