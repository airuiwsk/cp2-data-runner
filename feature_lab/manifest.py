"""Feature Discovery Campaign manifest freezer/validator."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

REQUIRED = [
    "fdc_id","status","objective","market_surface","instruments","data_source",
    "d0_search_window","d1_walk_forward_folds","d2_sealed_confirmation","d3_reserved_cp5",
    "label_definition","primary_discovery_objective","action_mapping","decision_timing","execution_price_semantics",
    "baseline","turnover_definition","cost_model","capital_jpy","dsl_version",
    "generators","evaluation_budget_by_generator","random_seeds","max_ast_depth",
    "max_complexity","ranking_rule","turnover_cap","minimum_n","champion_count",
    "null_control","positive_control","forbidden_data","lineage"
]


def canonical_payload(m):
    x = {k: v for k, v in m.items() if k != "manifest_sha256"}
    return json.dumps(x, sort_keys=True, separators=(",", ":")).encode()


def manifest_hash(m):
    return hashlib.sha256(canonical_payload(m)).hexdigest()


def parse_window(w, name):
    if not isinstance(w, dict) or set(("start", "end")) - set(w):
        raise ValueError(f"{name} must contain start/end")
    s = date.fromisoformat(w["start"])
    e = date.fromisoformat(w["end"])
    if not s < e:
        raise ValueError(f"{name}: start must be < end")
    return s, e


def overlaps(a, b):
    return max(a[0], b[0]) < min(a[1], b[1])


def validate_manifest(m, require_frozen_hash=True):
    missing = [k for k in REQUIRED if k not in m]
    if missing:
        raise ValueError("missing required fields: " + ",".join(missing))
    if not re.fullmatch(r"FDC\d{3,}", str(m["fdc_id"])):
        raise ValueError("invalid fdc_id")
    if m["champion_count"] < 1:
        raise ValueError("champion_count must be >=1")
    if m["capital_jpy"] <= 0:
        raise ValueError("capital_jpy must be >0")
    if m["max_ast_depth"] < 1 or m["max_complexity"] < 1:
        raise ValueError("invalid AST limits")
    if not m["generators"]:
        raise ValueError("at least one generator required")
    for g in m["generators"]:
        if int(m["evaluation_budget_by_generator"].get(g, 0)) < 1:
            raise ValueError(f"missing positive budget for generator {g}")

    d0 = parse_window(m["d0_search_window"], "d0")
    d2 = parse_window(m["d2_sealed_confirmation"], "d2")
    d3 = parse_window(m["d3_reserved_cp5"], "d3")
    if overlaps(d0, d2) or overlaps(d0, d3) or overlaps(d2, d3):
        raise ValueError("D0/D2/D3 windows must be disjoint")
    if d2[1] > d3[0]:
        raise ValueError("D2 must end no later than D3 start")

    for i, fold in enumerate(m["d1_walk_forward_folds"]):
        tr = parse_window(fold["train"], f"d1[{i}].train")
        va = parse_window(fold["validation"], f"d1[{i}].validation")
        for w in (tr, va):
            if w[0] < d0[0] or w[1] > d0[1]:
                raise ValueError("D1 folds must stay inside D0")
        if tr[1] > va[0]:
            raise ValueError("D1 train must end no later than validation start")

    expected = manifest_hash(m)
    if require_frozen_hash:
        if m.get("status") != "FROZEN":
            raise ValueError("manifest must be FROZEN")
        if m.get("manifest_sha256") != expected:
            raise ValueError("manifest_sha256 mismatch")
    return {"valid": True, "manifest_sha256": expected}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()
    p = Path(args.manifest)
    m = json.loads(p.read_text())
    if args.freeze:
        m["status"] = "FROZEN"
        m["manifest_sha256"] = manifest_hash(m)
        p.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    print(json.dumps(validate_manifest(m, require_frozen_hash=True), sort_keys=True))


if __name__ == "__main__":
    main()
