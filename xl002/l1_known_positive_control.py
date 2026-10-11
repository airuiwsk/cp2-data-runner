#!/usr/bin/env python3
"""XL002 read-only historical Flash positive control. Transport evidence only."""
import json
from pathlib import Path
from l0_collect import RPC_URL, CHAIN_ID_HEX, RpcClient, event_topic, canonical_bytes, sha256_bytes, utc_now

BLOCK = 1234595
EXPECTED = {
    "blockHash": "0x7ef7c8dc8fd001a8cbf8a91b03b37eb02c0a6b6a4270db52cf823673d8ba55c1",
    "transactionHash": "0xfce091d5967dae6d2c5a87d7d10d173abc71f4a605ce3882f08bb9190be2ccf8",
    "logIndex": 21,
    "address": "0x67f9a98220201f9cca2f5a911d382ba5dc7abdd5",
}
EVENTS = (
    "Flash(address,address,uint256,uint256,uint256,uint256)",
    "SetFeeProtocol(uint8,uint8,uint8,uint8)",
    "CollectProtocol(address,address,uint128,uint128)",
    "IncreaseObservationCardinalityNext(uint16,uint16)",
)
OUT = Path("artifacts/xl002-l1-known-positive-control")

def run(rpc=None, out=OUT):
    out.mkdir(parents=True, exist_ok=True)
    rpc = rpc or RpcClient(RPC_URL, out / "raw" / "rpc-requests.jsonl")
    topics = sorted(event_topic(s).lower() for s in EVENTS)
    filt = {"fromBlock": hex(BLOCK), "toBlock": hex(BLOCK), "topics": [topics]}
    report = {
        "schema": "XL002_L1_KNOWN_POSITIVE_CONTROL_V1",
        "source_l0_run": 38073851189,
        "status": "BLOCKED",
        "performance_computed": False,
        "l1_replay_fidelity_pass": False,
        "l1_discovery_authorized": False,
        "block": BLOCK,
        "filter_sha256": sha256_bytes(canonical_bytes(filt)),
        "started_at": utc_now(),
    }
    try:
        if rpc.call("eth_chainId", []) != CHAIN_ID_HEX:
            raise ValueError("chain ID mismatch")
        logs = rpc.call("eth_getLogs", [filt])
        if not isinstance(logs, list):
            raise ValueError("non-list eth_getLogs response")
        flash_topic = event_topic(EVENTS[0]).lower()
        matches = []
        for log in logs:
            if log.get("removed") is True:
                raise ValueError("removed log")
            if int(log["blockNumber"], 16) != BLOCK:
                raise ValueError("out-of-range log")
            if log["topics"][0].lower() not in topics:
                raise ValueError("unexpected topic")
            if (log["topics"][0].lower() == flash_topic
                and log["blockHash"].lower() == EXPECTED["blockHash"]
                and log["transactionHash"].lower() == EXPECTED["transactionHash"]
                and int(log["logIndex"], 16) == EXPECTED["logIndex"]
                and log["address"].lower() == EXPECTED["address"]):
                if len(log["topics"]) != 3 or len(log["data"]) != 2 + 64 * 4:
                    raise ValueError("Flash ABI structural mismatch")
                matches.append(log)
        if len(matches) != 1:
            raise ValueError("known-positive Flash event missing or duplicated")
        header = rpc.call("eth_getBlockByNumber", [hex(BLOCK), False])
        if not isinstance(header, dict) or header.get("hash", "").lower() != EXPECTED["blockHash"]:
            raise ValueError("known-positive block header hash mismatch")
        report.update(
            status="TRANSPORT_POSITIVE_CONTROL_PASS",
            log_count=len(logs),
            positive_flash_count=len(matches),
            response_sha256=sha256_bytes(canonical_bytes(logs)),
        )
        (out / "logs.json").write_bytes(canonical_bytes(logs) + b"\n")
    except Exception as exc:
        report["terminal_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["finished_at"] = utc_now()
        (out / "quality.json").write_bytes(canonical_bytes(report) + b"\n")
    return report

if __name__ == "__main__":
    result = run()
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "TRANSPORT_POSITIVE_CONTROL_PASS" else 1)
