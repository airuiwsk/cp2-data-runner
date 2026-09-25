"""FD1 synthetic invariants and calibration smoke.

This script MUST NOT load real market data. It tests the feature-lab engine only.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from dsl import evaluate, expression_hash, normalized_ast, validate


FIELD_DIMS = {"x1": "dimensionless", "x2": "dimensionless", "price": "price"}


def corr(a, b):
    pairs = [(x, y) for x, y in zip(a, b)
             if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 10:
        return 0.0
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx < 1e-18 or vy < 1e-18:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(vx * vy)


def make_data(seed=42, n=1000):
    r = random.Random(seed)
    x1 = [r.gauss(0, 1) for _ in range(n)]
    x2 = [r.gauss(0, 1) for _ in range(n)]
    eps = [r.gauss(0, 1) for _ in range(n)]
    target = [None] + [0.25 * x1[t - 1] + 0.97 * eps[t] for t in range(1, n)]
    null_target = [r.gauss(0, 1) for _ in range(n)]
    return {"x1": x1, "x2": x2, "price": [100.0 + 0.01 * i for i in range(n)]}, target, null_target


def random_expr(r):
    fields = [{"type": "field", "name": "x1"}, {"type": "field", "name": "x2"}]
    choice = r.randrange(5)
    f = fields[r.randrange(len(fields))]
    if choice == 0:
        return {"type": "op", "op": "lag", "args": [f], "params": {"n": r.choice([1, 2, 3, 5, 8])}}
    if choice == 1:
        return {"type": "op", "op": "rolling_mean", "args": [{"type": "op", "op": "lag", "args": [f], "params": {"n": 1}}], "params": {"window": r.choice([2, 3, 5, 8])}}
    if choice == 2:
        return {"type": "op", "op": "sign", "args": [{"type": "op", "op": "lag", "args": [f], "params": {"n": r.choice([1, 2, 3])}}], "params": {}}
    other = fields[r.randrange(len(fields))]
    op = "add" if choice == 3 else "mul"
    return {"type": "op", "op": op,
            "args": [
                {"type": "op", "op": "lag", "args": [f], "params": {"n": r.choice([1, 2, 3])}},
                {"type": "op", "op": "lag", "args": [other], "params": {"n": r.choice([1, 2, 3])}}
            ], "params": {}}


def deterministic_search(data, target, seed=7, budget=250):
    r = random.Random(seed)
    rows = []
    seen = set()
    for _ in range(budget):
        ast = random_expr(r)
        v = validate(ast, FIELD_DIMS)
        if not v["valid"]:
            continue
        h = expression_hash(ast)
        if h in seen:
            continue
        seen.add(h)
        score = corr(evaluate(ast, data), target)
        rows.append((score, h, normalized_ast(ast)))
    rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="fd1-report.json")
    args = ap.parse_args()

    data, target, null_target = make_data()

    planted = {"type": "op", "op": "lag", "args": [{"type": "field", "name": "x1"}], "params": {"n": 1}}
    causal = {"type": "op", "op": "rolling_mean", "args": [planted], "params": {"window": 5}}
    illegal_lead = {"type": "op", "op": "lag", "args": [{"type": "field", "name": "x1"}], "params": {"n": -1}}
    illegal_centered = {"type": "op", "op": "rolling_mean", "args": [{"type": "field", "name": "x1"}], "params": {"window": 5, "center": True}}
    dim_bad = {"type": "op", "op": "add", "args": [{"type": "field", "name": "price"}, {"type": "field", "name": "x1"}], "params": {}}

    assert validate(planted, FIELD_DIMS)["valid"]
    assert validate(causal, FIELD_DIMS)["valid"]
    assert not validate(illegal_lead, FIELD_DIMS)["valid"]
    assert not validate(illegal_centered, FIELD_DIMS)["valid"]
    assert not validate(dim_bad, FIELD_DIMS)["valid"]

    # Canonical serialization/hash invariant.
    planted_reordered = {"params": {"n": 1}, "args": [{"name": "x1", "type": "field"}], "op": "lag", "type": "op"}
    assert expression_hash(planted) == expression_hash(planted_reordered)

    # Causality sentinel: mutating observations after cutoff cannot alter earlier feature values.
    cutoff = 600
    base = evaluate(causal, data)
    mutated = {k: list(v) for k, v in data.items()}
    for i in range(cutoff + 1, len(mutated["x1"])):
        mutated["x1"][i] = 1_000_000.0 + i
    changed = evaluate(causal, mutated)
    assert base[:cutoff + 1] == changed[:cutoff + 1]

    planted_corr = corr(evaluate(planted, data), target)
    planted_null_corr = corr(evaluate(planted, data), null_target)
    unrelated_corr = corr(evaluate({"type": "field", "name": "x2"}, data), target)
    assert planted_corr > 0.20
    assert abs(planted_null_corr) < 0.10
    assert abs(unrelated_corr) < 0.10

    # Fixed-seed deterministic search invariant.
    s1 = deterministic_search(data, target)
    s2 = deterministic_search(data, target)
    assert [(a, b) for a, b, _ in s1] == [(a, b) for a, b, _ in s2]
    assert len(s1) >= 20

    report = {
        "fd_stage": "FD1_ENGINE_INVARIANTS",
        "status": "PASS",
        "real_market_data_loaded": False,
        "real_market_performance_inspected": False,
        "tests": {
            "typed_validation": "PASS",
            "lead_rejected": "PASS",
            "centered_window_rejected": "PASS",
            "dimension_mismatch_rejected": "PASS",
            "canonical_hash": "PASS",
            "future_mutation_invariance": "PASS",
            "synthetic_positive_control_smoke": "PASS",
            "synthetic_null_smoke": "PASS",
            "fixed_seed_search_determinism": "PASS"
        },
        "synthetic_metrics": {
            "planted_lag_corr": planted_corr,
            "planted_vs_null_corr": planted_null_corr,
            "unrelated_feature_corr": unrelated_corr,
            "deterministic_search_unique_expressions": len(s1),
            "deterministic_top_hash": s1[0][1],
            "deterministic_top_score": s1[0][0]
        }
    }
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
