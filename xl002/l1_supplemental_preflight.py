#!/usr/bin/env python3
"""XL002 L1: outcome-blind 5,000-block supplemental-topic transport preflight.

Never computes pool economics, strategy rankings, replay fidelity or net edge.
The one-block known-positive Flash control MUST pass before the range query.
"""
import json
from pathlib import Path
from l0_collect import RPC_URL, CHAIN_ID_HEX, RpcClient, event_topic, canonical_bytes, sha256_bytes, utc_now
from l1_known_positive_control import BLOCK, EXPECTED, EVENTS, run as positive_control

START_BLOCK = 954800
END_BLOCK = 1591011
CHUNK_SIZE = 5000
RANGE_START = START_BLOCK + ((BLOCK - START_BLOCK) // CHUNK_SIZE) * CHUNK_SIZE
RANGE_END = min(RANGE_START + CHUNK_SIZE - 1, END_BLOCK)
OUT = Path("artifacts/xl002-l1-supplemental-preflight")


def run(rpc=None, out=OUT):
    out.mkdir(parents=True, exist_ok=True)
    rpc = rpc or RpcClient(RPC_URL, out / "raw" / "rpc-requests.jsonl")
    filt = {
        "fromBlock": hex(RANGE_START),
        "toBlock": hex(RANGE_END),
        "topics": [sorted(event_topic(e).lower() for e in EVENTS)],
    }
    report = {
        "schema": "XL002_L1_SUPPLEMENTAL_PREFLIGHT_V1",
        "status": "BLOCKED",
        "l0_authoritative_run": 38073851189,
        "chain_id_expected": 4663,
        "frozen_window_start_block": START_BLOCK,
        "frozen_window_end_block": END_BLOCK,
        "range_start": RANGE_START,
        "range_end": RANGE_END,
        "filter_sha256": sha256_bytes(canonical_bytes(filt)),
        "performance_computed": False,
        "l1_replay_fidelity_pass": False,
        "l1_strategy_discovery_authorized": False,
        "full_supplemental_coverage": False,
        "started_at": utc_now(),
    }
    try:
        control = positive_control(rpc=rpc, out=out / "known-positive")
        report["positive_control_status"] = control["status"]
        if control["status"] != "TRANSPORT_POSITIVE_CONTROL_PASS":
            raise ValueError("known-positive transport control did not pass")
        if rpc.call("eth_chainId", []) != CHAIN_ID_HEX:
            raise ValueError("chain ID mismatch before range scan")
        logs = rpc.call("eth_getLogs", [filt])
        if not isinstance(logs, list):
            raise ValueError("eth_getLogs returned non-list")
        topic_set = set(filt["topics"][0])
        keys = set()
        positive = 0
        counts = {e: 0 for e in EVENTS}
        by_topic = {event_topic(e).lower(): e for e in EVENTS}
        for log in logs:
            if not isinstance(log, dict) or log.get("removed") is True:
                raise ValueError("removed or malformed log")
            block = int(log["blockNumber"], 16)
            if not RANGE_START <= block <= RANGE_END:
                raise ValueError("out-of-range log")
            topic = log["topics"][0].lower()
            if topic not in topic_set:
                raise ValueError("unexpected event topic")
            key = (log["blockHash"].lower(), log["transactionHash"].lower(), int(log["logIndex"], 16))
            if key in keys:
                raise ValueError("duplicate event identity")
            keys.add(key)
            counts[by_topic[topic]] += 1
            if (block == BLOCK and log["blockHash"].lower() == EXPECTED["blockHash"]
                    and log["transactionHash"].lower() == EXPECTED["transactionHash"]
                    and int(log["logIndex"], 16) == EXPECTED["logIndex"]
                    and log["address"].lower() == EXPECTED["address"]):
                positive += 1
        if positive != 1:
            raise ValueError("known-positive Flash missing from full-range query")
        (out / "range-logs.json").write_bytes(canonical_bytes(logs) + b"\\n")
        report.update(
            status="SUPPLEMENTAL_TOPIC_TRANSPORT_PREFLIGHT_PASS",
            raw_response_sha256=sha256_bytes(canonical_bytes(logs)),
            log_count=len(logs),
            topic_counts=counts,
            positive_flash_count=positive,
        )
    except Exception as exc:
        report["terminal_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["finished_at"] = utc_now()
        (out / "quality.json").write_bytes(canonical_bytes(report) + b"\\n")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "SUPPLEMENTAL_TOPIC_TRANSPORT_PREFLIGHT_PASS" else 1)
