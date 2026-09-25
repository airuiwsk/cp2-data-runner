"""FD2 synthetic calibration for the Feature Discovery random-search baseline.

No real market data is loaded. All data are deterministic synthetic controls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from dsl import evaluate, expression_hash, normalized_ast, validate

LAGS = [1, 2, 3, 5, 8]
FIELDS = ["x0", "x1", "x2", "x3"]
FIELD_DIMS = {k: "dimensionless" for k in FIELDS}


def corr(a, b):
    pairs = [(x, y) for x, y in zip(a, b)
             if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 20:
        return 0.0
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx < 1e-18 or vy < 1e-18:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(vx * vy)


def make_fields(seed, n):
    r = random.Random(seed)
    return {f: [r.gauss(0.0, 1.0) for _ in range(n)] for f in FIELDS}


def planted_ast(rep_seed):
    r = random.Random(rep_seed ^ 0x5F3759DF)
    f = FIELDS[r.randrange(len(FIELDS))]
    lag = LAGS[r.randrange(len(LAGS))]
    return {"type": "op", "op": "lag", "args": [{"type": "field", "name": f}], "params": {"n": lag}}


def make_target(data, seed, planted=None, beta=0.12):
    r = random.Random(seed)
    noise = [r.gauss(0.0, 1.0) for _ in range(len(next(iter(data.values()))))]
    if planted is None:
        return noise
    signal = evaluate(planted, data)
    out = []
    for s, e in zip(signal, noise):
        out.append(None if s is None else beta * s + e)
    return out


def random_expr(r):
    field = {"type": "field", "name": FIELDS[r.randrange(len(FIELDS))]}
    choice = r.randrange(8)
    if choice == 0:
        return {"type": "op", "op": "lag", "args": [field], "params": {"n": r.choice(LAGS)}}
    if choice == 1:
        return {"type": "op", "op": "rolling_mean",
                "args": [{"type": "op", "op": "lag", "args": [field], "params": {"n": r.choice([1, 2, 3])}}],
                "params": {"window": r.choice([2, 3, 5, 8])}}
    if choice == 2:
        return {"type": "op", "op": "zscore",
                "args": [{"type": "op", "op": "lag", "args": [field], "params": {"n": r.choice([1, 2, 3])}}],
                "params": {"window": r.choice([5, 8, 13])}}
    if choice == 3:
        return {"type": "op", "op": "sign",
                "args": [{"type": "op", "op": "lag", "args": [field], "params": {"n": r.choice([1, 2, 3, 5])}}],
                "params": {}}
    other = {"type": "field", "name": FIELDS[r.randrange(len(FIELDS))]}
    op = r.choice(["add", "sub", "mul"])
    return {"type": "op", "op": op,
            "args": [
                {"type": "op", "op": "lag", "args": [field], "params": {"n": r.choice([1, 2, 3, 5])}},
                {"type": "op", "op": "lag", "args": [other], "params": {"n": r.choice([1, 2, 3, 5])}}
            ], "params": {}}


def search(data, target, seed, budget=500):
    r = random.Random(seed)
    rows = []
    seen = set()

    # Include the simple causal lag basis as part of the frozen baseline grammar.
    basis = [
        {"type": "op", "op": "lag", "args": [{"type": "field", "name": f}], "params": {"n": lag}}
        for f in FIELDS for lag in LAGS
    ]

    candidates = basis + [random_expr(r) for _ in range(max(0, budget - len(basis)))]
    for ast in candidates[:budget]:
        if not validate(ast, FIELD_DIMS, max_depth=6)["valid"]:
            continue
        h = expression_hash(ast)
        if h in seen:
            continue
        seen.add(h)
        score = corr(evaluate(ast, data), target)
        rows.append({"score": score, "hash": h, "ast": normalized_ast(ast)})

    rows.sort(key=lambda x: (x["score"], x["hash"]), reverse=True)
    if not rows:
        raise RuntimeError("no valid expressions")
    return rows


def one_rep(kind, rep_index):
    base = 100_000 + rep_index * 997
    search_data = make_fields(base + 1, 800)
    confirm_data = make_fields(base + 2, 400)
    plant = planted_ast(base) if kind == "positive" else None
    target_search = make_target(search_data, base + 3, planted=plant)
    target_confirm = make_target(confirm_data, base + 4, planted=plant)

    rows = search(search_data, target_search, base + 5, budget=500)
    champion = rows[0]
    d2_corr = corr(evaluate(champion["ast"], confirm_data), target_confirm)
    planted_hash = expression_hash(plant) if plant is not None else None

    return {
        "kind": kind,
        "replicate": rep_index,
        "unique_valid_expressions": len(rows),
        "champion_hash": champion["hash"],
        "champion_d0_score": champion["score"],
        "d2_corr": d2_corr,
        "d2_pass": d2_corr > 0.08,
        "planted_hash": planted_hash,
        "exact_planted_recovered": bool(planted_hash and champion["hash"] == planted_hash),
    }


def canonical_digest(payload):
    b = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def run_once():
    nulls = [one_rep("null", i) for i in range(32)]
    positives = [one_rep("positive", i) for i in range(32)]

    summary = {
        "protocol": "FD2_CALIBRATION_V1",
        "real_market_data_loaded": False,
        "real_market_performance_inspected": False,
        "null_replicates": 32,
        "positive_replicates": 32,
        "budget_per_replicate": 500,
        "synthetic_d2_threshold_corr_gt": 0.08,
        "null_false_confirmations": sum(r["d2_pass"] for r in nulls),
        "positive_d2_passes": sum(r["d2_pass"] for r in positives),
        "positive_exact_planted_recoveries": sum(r["exact_planted_recovered"] for r in positives),
        "min_unique_valid_expressions": min(r["unique_valid_expressions"] for r in nulls + positives),
        "null_max_d0_score": max(r["champion_d0_score"] for r in nulls),
        "null_max_d2_corr": max(r["d2_corr"] for r in nulls),
        "positive_median_d2_corr": sorted(r["d2_corr"] for r in positives)[len(positives)//2],
        "rows": nulls + positives,
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="fd2-calibration-report.json")
    args = ap.parse_args()

    a = run_once()
    b = run_once()
    da = canonical_digest(a)
    db = canonical_digest(b)
    deterministic = da == db

    gates = {
        "null_false_confirmations_le_4": a["null_false_confirmations"] <= 4,
        "positive_d2_passes_ge_18": a["positive_d2_passes"] >= 18,
        "min_unique_valid_expressions_ge_20": a["min_unique_valid_expressions"] >= 20,
        "deterministic_digest_match": deterministic,
        "no_real_market_data": not a["real_market_data_loaded"],
        "no_real_market_performance": not a["real_market_performance_inspected"],
    }
    status = "PASS" if all(gates.values()) else "FAIL"

    out = {
        "fd_stage": "FD2_SYNTHETIC_CALIBRATION",
        "status": status,
        "gates": gates,
        "canonical_result_digest": da,
        "summary": {k: v for k, v in a.items() if k != "rows"},
        "rows": a["rows"],
    }
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: out[k] for k in ["fd_stage", "status", "gates", "canonical_result_digest", "summary"]}, sort_keys=True))
    if status != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
