"""Typed causal feature DSL for AI-Trading Feature Discovery Lab.

FD1 scope only. No real-market campaign is launched by this module.
Expressions are JSON-like AST dictionaries; arbitrary generated Python is not allowed.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Tuple

ALLOWED_OPS = {
    "lag", "diff", "pct_change",
    "rolling_mean", "rolling_std", "rolling_min", "rolling_max", "zscore",
    "sign", "abs", "clip",
    "add", "sub", "mul", "protected_div",
}

UNARY = {"lag", "diff", "pct_change", "rolling_mean", "rolling_std", "rolling_min", "rolling_max", "zscore", "sign", "abs", "clip"}
BINARY = {"add", "sub", "mul", "protected_div"}


class DSLValidationError(ValueError):
    pass


def normalized_ast(ast: Dict[str, Any]) -> Dict[str, Any]:
    kind = ast.get("type")
    if kind == "field":
        return {"type": "field", "name": str(ast["name"])}
    if kind != "op":
        raise DSLValidationError(f"unsupported node type: {kind!r}")
    op = str(ast.get("op"))
    args = [normalized_ast(a) for a in ast.get("args", [])]
    params = ast.get("params", {}) or {}
    clean_params = {str(k): params[k] for k in sorted(params)}
    return {"type": "op", "op": op, "args": args, "params": clean_params}


def expression_hash(ast: Dict[str, Any]) -> str:
    payload = json.dumps(normalized_ast(ast), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _depth(ast: Dict[str, Any]) -> int:
    if ast.get("type") == "field":
        return 1
    return 1 + max((_depth(a) for a in ast.get("args", [])), default=0)


def _validate_node(ast: Dict[str, Any], field_dims: Dict[str, str]) -> str:
    kind = ast.get("type")
    if kind == "field":
        name = ast.get("name")
        if name not in field_dims:
            raise DSLValidationError(f"unknown field: {name}")
        return field_dims[name]

    if kind != "op":
        raise DSLValidationError(f"unsupported node type: {kind!r}")

    op = ast.get("op")
    if op not in ALLOWED_OPS:
        raise DSLValidationError(f"unsupported operator: {op}")

    args = ast.get("args", [])
    params = ast.get("params", {}) or {}

    if op in UNARY and len(args) != 1:
        raise DSLValidationError(f"{op} expects one arg")
    if op in BINARY and len(args) != 2:
        raise DSLValidationError(f"{op} expects two args")

    dims = [_validate_node(a, field_dims) for a in args]

    if op == "lag":
        n = params.get("n")
        if not isinstance(n, int) or n < 1:
            raise DSLValidationError("lag requires integer n >= 1; lead/current shortcuts are forbidden")
        return dims[0]

    if op in {"rolling_mean", "rolling_std", "rolling_min", "rolling_max", "zscore"}:
        window = params.get("window")
        if not isinstance(window, int) or window < 2:
            raise DSLValidationError(f"{op} requires integer window >= 2")
        if params.get("center", False):
            raise DSLValidationError("centered rolling windows are forbidden")
        return "dimensionless" if op == "zscore" else dims[0]

    if op == "clip":
        lo, hi = params.get("lo"), params.get("hi")
        if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)) or lo >= hi:
            raise DSLValidationError("clip requires numeric lo < hi")
        return dims[0]

    if op in {"diff", "abs"}:
        return dims[0]
    if op in {"pct_change", "sign"}:
        return "dimensionless"

    a, b = dims
    if op in {"add", "sub"}:
        if a != b:
            raise DSLValidationError(f"{op} dimension mismatch: {a} vs {b}")
        return a
    if op == "mul":
        if a == "dimensionless":
            return b
        if b == "dimensionless":
            return a
        raise DSLValidationError(f"mul requires at least one dimensionless operand: {a}, {b}")
    if op == "protected_div":
        if a == b:
            return "dimensionless"
        if b == "dimensionless":
            return a
        raise DSLValidationError(f"protected_div dimension mismatch: {a} / {b}")

    raise DSLValidationError(f"unhandled operator: {op}")


def validate(ast: Dict[str, Any], field_dims: Dict[str, str], max_depth: int = 8) -> Dict[str, Any]:
    try:
        depth = _depth(ast)
        if depth > max_depth:
            raise DSLValidationError(f"AST depth {depth} exceeds max_depth {max_depth}")
        dim = _validate_node(ast, field_dims)
        return {"valid": True, "dimension": dim, "depth": depth, "reason": None}
    except (DSLValidationError, KeyError, TypeError) as exc:
        return {"valid": False, "dimension": None, "depth": _depth(ast) if isinstance(ast, dict) else None, "reason": str(exc)}


def _safe_div(a: float, b: float) -> float | None:
    if abs(b) < 1e-12:
        return None
    return a / b


def _rolling(values: List[float | None], window: int, mode: str) -> List[float | None]:
    out: List[float | None] = [None] * len(values)
    for i in range(window - 1, len(values)):
        w = values[i - window + 1:i + 1]
        if any(v is None or not math.isfinite(v) for v in w):
            continue
        xs = [float(v) for v in w]
        if mode == "mean":
            out[i] = sum(xs) / window
        elif mode == "std":
            m = sum(xs) / window
            out[i] = math.sqrt(sum((x - m) ** 2 for x in xs) / window)
        elif mode == "min":
            out[i] = min(xs)
        elif mode == "max":
            out[i] = max(xs)
        else:
            raise ValueError(mode)
    return out


def evaluate(ast: Dict[str, Any], data: Dict[str, List[float]]) -> List[float | None]:
    node = normalized_ast(ast)
    if node["type"] == "field":
        return [float(x) for x in data[node["name"]]]

    op = node["op"]
    params = node["params"]
    args = [evaluate(a, data) for a in node["args"]]
    n = len(args[0])

    if op == "lag":
        k = int(params["n"])
        return [None] * k + args[0][:-k]
    if op == "diff":
        x = args[0]
        return [None] + [None if x[i] is None or x[i - 1] is None else x[i] - x[i - 1] for i in range(1, n)]
    if op == "pct_change":
        x = args[0]
        out = [None]
        for i in range(1, n):
            if x[i] is None or x[i - 1] is None:
                out.append(None)
            else:
                out.append(_safe_div(x[i] - x[i - 1], x[i - 1]))
        return out
    if op in {"rolling_mean", "rolling_std", "rolling_min", "rolling_max"}:
        mode = op.replace("rolling_", "")
        return _rolling(args[0], int(params["window"]), mode)
    if op == "zscore":
        x = args[0]
        w = int(params["window"])
        means = _rolling(x, w, "mean")
        stds = _rolling(x, w, "std")
        out = []
        for v, m, s in zip(x, means, stds):
            out.append(None if v is None or m is None or s is None or s < 1e-12 else (v - m) / s)
        return out
    if op == "sign":
        return [None if v is None else (1.0 if v > 0 else -1.0 if v < 0 else 0.0) for v in args[0]]
    if op == "abs":
        return [None if v is None else abs(v) for v in args[0]]
    if op == "clip":
        lo, hi = float(params["lo"]), float(params["hi"])
        return [None if v is None else min(hi, max(lo, v)) for v in args[0]]

    a, b = args
    out: List[float | None] = []
    for x, y in zip(a, b):
        if x is None or y is None:
            out.append(None)
        elif op == "add":
            out.append(x + y)
        elif op == "sub":
            out.append(x - y)
        elif op == "mul":
            out.append(x * y)
        elif op == "protected_div":
            out.append(_safe_div(x, y))
        else:
            raise ValueError(op)
    return out
