#!/usr/bin/env python3
"""XL002 L1 outcome-blind public historical-state availability probe."""
import datetime
import hashlib
import json
import pathlib
import urllib.request
import urllib.error

CHAIN = "0x1237"
BLOCK = 1241589
POOL = "0x67f9a98220201f9cca2f5a911d382ba5dc7abdd5"
PRIMARY = "https://rpc.mainnet.chain.robinhood.com"
CANDIDATES = {"publicnode": "https://robinhood-rpc.publicnode.com", "triport_public": "https://triport.io/rpc/robinhood/public"}
SELECTORS = {
    "slot0": "0x3850c7bd",
    "liquidity": "0x1a686502",
    "feeGrowthGlobal0X128": "0xf3058399",
    "feeGrowthGlobal1X128": "0x46141319",
}

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

def sha(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()

def rpc(url, method, params):
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    evidence = {"endpoint": url, "method": method, "params": params,
                "request_sha256": sha(request),
                "acquired_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        req = urllib.request.Request(url, canonical(request), {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "AI-Trading-XL002-L0/1.0"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read())
        evidence["response_sha256"] = sha(payload)
        if not isinstance(payload, dict) or payload.get("id") != 1 or payload.get("jsonrpc") != "2.0":
            evidence["status"] = "INVALID_ENVELOPE"
            return None, evidence
        if payload.get("error") is not None:
            evidence["status"] = "RPC_ERROR"
            evidence["error"] = payload["error"]
            return None, evidence
        evidence["status"] = "OK"
        return payload.get("result"), evidence
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        evidence["status"] = "TRANSPORT_ERROR"
        evidence["error"] = str(exc)[:250]
        return None, evidence

def probe(endpoint, expected_hash):
    rows = []
    def call(method, params):
        value, row = rpc(endpoint, method, params)
        rows.append(row)
        return value
    chain = call("eth_chainId", [])
    if not isinstance(chain, str) or chain.lower() != CHAIN:
        return {"status": "CHAIN_UNAVAILABLE_OR_MISMATCH", "evidence": rows}
    block = call("eth_getBlockByNumber", [hex(BLOCK), False])
    if not isinstance(block, dict) or not isinstance(block.get("hash"), str):
        return {"status": "HEADER_UNAVAILABLE", "evidence": rows}
    if not expected_hash:
        return {"status": "REFERENCE_HEADER_UNAVAILABLE", "evidence": rows}
    if block["hash"].lower() != expected_hash.lower():
        return {"status": "HEADER_HASH_MISMATCH", "evidence": rows}
    code = call("eth_getCode", [POOL, hex(BLOCK)])
    if not isinstance(code, str) or not code.startswith("0x") or len(code) <= 2:
        return {"status": "HISTORICAL_CODE_UNAVAILABLE", "evidence": rows}
    hashes = {}
    for name, selector in SELECTORS.items():
        value = call("eth_call", [{"to": POOL, "data": selector}, hex(BLOCK)])
        min_length = 2 + 64 * (7 if name == "slot0" else 1)
        if not isinstance(value, str) or not value.startswith("0x") or len(value) < min_length:
            return {"status": "HISTORICAL_STATE_UNAVAILABLE", "failed": name, "evidence": rows}
        hashes[name] = sha(value)
    return {"status": "HISTORICAL_STATE_AVAILABLE_FOR_ONE_BLOCK",
            "code_sha256": sha(code), "state_sha256": hashes, "evidence": rows}

def main():
    pathlib.Path("artifacts/xl002-l1-state-probe").mkdir(parents=True, exist_ok=True)
    chain, c = rpc(PRIMARY, "eth_chainId", [])
    block, b = rpc(PRIMARY, "eth_getBlockByNumber", [hex(BLOCK), False]) if isinstance(chain, str) and chain.lower() == CHAIN else (None, None)
    expected = block.get("hash") if isinstance(block, dict) else None
    result = {
        "schema": "xl002-l1-state-probe-v1",
        "frozen_blocks": [954800, 1591011],
        "probe_block": BLOCK,
        "performance_computed": False,
        "l0_contract_changed": False,
        "l1_strategy_discovery_authorized": False,
        "reference": {"chain_status": c["status"], "chain_evidence": c, "block_evidence": b, "block_hash": expected},
        "independent_candidates": {name: probe(url, expected) for name, url in CANDIDATES.items()},
        "l1_replay_fidelity": "NOT_TESTED",
    }
    result["historical_state_probe_pass"] = any(item["status"] == "HISTORICAL_STATE_AVAILABLE_FOR_ONE_BLOCK" for item in result["independent_candidates"].values())
    pathlib.Path("artifacts/xl002-l1-state-probe/quality-report.json").write_bytes(canonical(result) + b"\n")
    print(json.dumps({"historical_state_probe_pass": result["historical_state_probe_pass"],
                      "independent_statuses": {k: v["status"] for k, v in result["independent_candidates"].items()},
                      "l1_replay_fidelity": "NOT_TESTED", "performance_computed": False}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
