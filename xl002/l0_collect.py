#!/usr/bin/env python3
"""
XL002 L0 read-only collector for Robinhood Chain / Uniswap v3.

Canonical research contract:
  AI-Trading/research/external-leads/XL-20260927-002-v3-readonly-data-contract-v1.md

This program contains no wallet/signing/transaction-submission capability and computes
no strategy return, LP PnL, APR/APY, ranking, signal, or net edge.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Iterable

try:
    from Crypto.Hash import keccak
except ImportError as exc:
    raise SystemExit("pycryptodome is required: pip install pycryptodome==3.23.0") from exc


RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
CHAIN_ID_DEC = 4663
CHAIN_ID_HEX = "0x1237"
FACTORY = "0x1f7d7550b1b028f7571e69a784071f0205fd2efa"
WINDOW_START = "2026-07-02T00:00:00Z"
WINDOW_END = "2026-07-03T00:00:00Z"
MAX_ATTEMPTS = 5
USER_AGENT = "AI-Trading-XL002-L0/1.0"

EVENT_SIGNATURES = {
    "PoolCreated": "PoolCreated(address,address,uint24,int24,address)",
    "Initialize": "Initialize(uint160,int24)",
    "Mint": "Mint(address,address,int24,int24,uint128,uint256,uint256)",
    "Burn": "Burn(address,int24,int24,uint128,uint256,uint256)",
    "Collect": "Collect(address,address,int24,int24,uint128,uint128)",
    "Swap": "Swap(address,address,int256,int256,uint160,uint128,int24)",
}

CALL_SELECTORS = {
    "decimals": "0x313ce567",
    "symbol": "0x95d89b41",
    "name": "0x06fdde03",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(s: str) -> int:
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def event_topic(signature: str) -> str:
    k = keccak.new(digest_bits=256)
    k.update(signature.encode("ascii"))
    return "0x" + k.hexdigest()


TOPICS = {name: event_topic(sig) for name, sig in EVENT_SIGNATURES.items()}
TOPIC_TO_NAME = {topic.lower(): name for name, topic in TOPICS.items()}


class RpcClient:
    def __init__(self, url: str, raw_log: pathlib.Path):
        self.url = url
        self.raw_log = raw_log
        self.next_id = 1
        self.request_count = 0
        self.failure_count = 0
        raw_log.parent.mkdir(parents=True, exist_ok=True)

    def _append_raw(self, record: dict[str, Any]) -> None:
        with self.raw_log.open("ab") as fh:
            fh.write(canonical_bytes(record) + b"\n")

    def call(self, method: str, params: list[Any]) -> Any:
        request_id = self.next_id
        self.next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        request_bytes = canonical_bytes(payload)
        request_sha = sha256_bytes(request_bytes)
        last_error = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            acquired_at = utc_now()
            try:
                req = urllib.request.Request(
                    self.url,
                    data=request_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": USER_AGENT,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    response_bytes = resp.read()
                response_obj = json.loads(response_bytes)
                canonical_response = canonical_bytes(response_obj)
                self.request_count += 1
                self._append_raw(
                    {
                        "endpoint": self.url,
                        "acquired_at": acquired_at,
                        "attempt": attempt,
                        "request_sha256": request_sha,
                        "request": payload,
                        "response_sha256": sha256_bytes(canonical_response),
                        "response": response_obj,
                    }
                )
                if "error" in response_obj:
                    err = response_obj["error"]
                    last_error = f"RPC error: {err}"
                    if attempt < MAX_ATTEMPTS and _is_transient_rpc_error(err):
                        time.sleep(min(2 ** (attempt - 1), 8))
                        continue
                    raise RuntimeError(last_error)
                return response_obj.get("result")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self.failure_count += 1
                self._append_raw(
                    {
                        "endpoint": self.url,
                        "acquired_at": acquired_at,
                        "attempt": attempt,
                        "request_sha256": request_sha,
                        "request": payload,
                        "transport_error": last_error,
                    }
                )
                if attempt == MAX_ATTEMPTS:
                    raise RuntimeError(f"terminal RPC transport failure for {method}: {last_error}") from exc
                time.sleep(min(2 ** (attempt - 1), 8))

        raise RuntimeError(f"terminal RPC failure for {method}: {last_error}")


def _is_transient_rpc_error(err: Any) -> bool:
    text = json.dumps(err, ensure_ascii=False).lower()
    # Retry only failures that may clear without changing the request.
    # Deterministic log-range/result-size errors must return immediately so
    # get_logs_split() can bisect the range instead of sleeping/retrying it.
    markers = ("rate limit", "timeout", "temporar", "429", "overload", "busy", "try again")
    return any(m in text for m in markers)


def hex_int(v: str | None) -> int:
    if v is None:
        return 0
    return int(v, 16)


def block_header(client: RpcClient, number: int) -> dict[str, Any]:
    block = client.call("eth_getBlockByNumber", [hex(number), False])
    if block is None:
        raise RuntimeError(f"missing block {number}")
    return block


def find_first_block_at_or_after(client: RpcClient, target_ts: int, latest: int) -> int:
    lo, hi = 0, latest
    while lo < hi:
        mid = (lo + hi) // 2
        b = block_header(client, mid)
        ts = hex_int(b.get("timestamp"))
        if ts >= target_ts:
            hi = mid
        else:
            lo = mid + 1
    b = block_header(client, lo)
    if hex_int(b.get("timestamp")) < target_ts:
        raise RuntimeError(f"no block found at/after timestamp {target_ts}")
    return lo


def get_logs_split(
    client: RpcClient,
    address: str | list[str],
    from_block: int,
    to_block: int,
    topics: list[Any] | None,
    depth: int = 0,
) -> list[dict[str, Any]]:
    if from_block > to_block:
        return []
    # Robinhood Chain produces ~636k blocks/day in the frozen window.
    # Never begin with a 600k+ eth_getLogs request: proactively partition
    # into small deterministic ranges, then retain recursive bisection as
    # a fallback for provider-specific limits.
    MAX_LOG_BLOCKS = 5000
    if depth == 0 and (to_block - from_block + 1) > MAX_LOG_BLOCKS:
        out: list[dict[str, Any]] = []
        lo = from_block
        while lo <= to_block:
            hi = min(lo + MAX_LOG_BLOCKS - 1, to_block)
            out.extend(get_logs_split(client, address, lo, hi, topics, depth + 1))
            lo = hi + 1
        return out
    filt: dict[str, Any] = {
        "address": address,
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
    }
    if topics is not None:
        filt["topics"] = topics
    try:
        result = client.call("eth_getLogs", [filt])
        if not isinstance(result, list):
            raise RuntimeError("eth_getLogs result is not a list")
        return result
    except RuntimeError as exc:
        if from_block == to_block or depth >= 30:
            raise
        msg = str(exc).lower()
        split_markers = ("rate", "limit", "range", "response size", "timeout", "too many", "temporar")
        if not any(m in msg for m in split_markers):
            raise
        mid = (from_block + to_block) // 2
        return (
            get_logs_split(client, address, from_block, mid, topics, depth + 1)
            + get_logs_split(client, address, mid + 1, to_block, topics, depth + 1)
        )


def topic_address(topic: str) -> str:
    h = topic[2:] if topic.startswith("0x") else topic
    if len(h) != 64:
        raise ValueError(f"unexpected address topic length: {topic}")
    return "0x" + h[-40:]


def decode_signed_word(word_hex: str, bits: int) -> int:
    value = int(word_hex, 16)
    if value >= (1 << (bits - 1)):
        value -= 1 << bits
    return value


def decode_pool_created(log: dict[str, Any]) -> dict[str, Any]:
    topics = log.get("topics") or []
    if len(topics) != 4 or topics[0].lower() != TOPICS["PoolCreated"].lower():
        raise ValueError("invalid PoolCreated log topics")
    data = (log.get("data") or "0x")[2:]
    if len(data) < 128:
        raise ValueError("invalid PoolCreated data")
    words = [data[i:i+64] for i in range(0, len(data), 64)]
    tick_spacing = decode_signed_word(words[0], 256)
    pool = "0x" + words[1][-40:]
    return {
        "pool": pool.lower(),
        "token0": topic_address(topics[1]).lower(),
        "token1": topic_address(topics[2]).lower(),
        "fee": int(topics[3], 16),
        "tickSpacing": tick_spacing,
        "blockNumber": hex_int(log.get("blockNumber")),
        "transactionHash": log.get("transactionHash"),
        "transactionIndex": hex_int(log.get("transactionIndex")),
        "logIndex": hex_int(log.get("logIndex")),
        "blockHash": log.get("blockHash"),
    }


def event_sort_key(log: dict[str, Any]) -> tuple[int, int, int]:
    return (
        hex_int(log.get("blockNumber")),
        hex_int(log.get("transactionIndex")),
        hex_int(log.get("logIndex")),
    )


def chunks(seq: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i:i+size]


def decode_abi_string(raw: str | None) -> Any:
    if not raw or raw == "0x":
        return None
    data = bytes.fromhex(raw[2:])
    if len(data) == 32:
        stripped = data.rstrip(b"\x00")
        try:
            return stripped.decode("utf-8")
        except UnicodeDecodeError:
            return raw
    if len(data) >= 64:
        try:
            offset = int.from_bytes(data[:32], "big")
            if offset + 32 > len(data):
                return raw
            length = int.from_bytes(data[offset:offset+32], "big")
            value = data[offset+32:offset+32+length]
            return value.decode("utf-8")
        except Exception:
            return raw
    return raw


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def write_jsonl(path: pathlib.Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        for row in rows:
            fh.write(canonical_bytes(row) + b"\n")


def run_preflight(client: RpcClient, out: pathlib.Path, start_block: int, end_block: int) -> dict[str, Any]:
    # Robinhood's public RPC exposes historical block/log data but the measured
    # endpoint does not expose historical state. Factory identity is therefore
    # checked at latest; the historical existence proof comes from canonical
    # Factory PoolCreated logs inside the frozen window.
    factory_code = client.call("eth_getCode", [FACTORY, "latest"])
    if not factory_code or factory_code == "0x":
        raise RuntimeError("canonical v3 factory has no bytecode at latest state")

    pool_logs = get_logs_split(
        client,
        FACTORY,
        start_block,
        end_block,
        [TOPICS["PoolCreated"]],
    )
    pools = [decode_pool_created(log) for log in sorted(pool_logs, key=event_sort_key)]
    write_jsonl(out / "decoded" / "pools-created.jsonl", pools)

    event_counts = {name: 0 for name in ("Initialize", "Mint", "Burn", "Collect", "Swap")}
    pool_events: list[dict[str, Any]] = []

    addresses = sorted({p["pool"] for p in pools})
    allowed_topics = [[TOPICS[n] for n in event_counts]]
    for addr_chunk in chunks(addresses, 50):
        logs = get_logs_split(client, addr_chunk, start_block, end_block, allowed_topics)
        for log in logs:
            name = TOPIC_TO_NAME.get((log.get("topics") or [""])[0].lower())
            if name in event_counts:
                event_counts[name] += 1
                pool_events.append(
                    {
                        "event": name,
                        "address": (log.get("address") or "").lower(),
                        "blockNumber": hex_int(log.get("blockNumber")),
                        "transactionHash": log.get("transactionHash"),
                        "transactionIndex": hex_int(log.get("transactionIndex")),
                        "logIndex": hex_int(log.get("logIndex")),
                        "blockHash": log.get("blockHash"),
                    }
                )
    pool_events.sort(key=lambda x: (x["blockNumber"], x["transactionIndex"], x["logIndex"]))
    write_jsonl(out / "decoded" / "event-index.jsonl", pool_events)

    density_ok = (
        event_counts["Initialize"] >= 1
        and event_counts["Swap"] >= 100
        and (event_counts["Mint"] + event_counts["Burn"]) >= 1
    )

    return {
        "factory_code_sha256": sha256_bytes(canonical_bytes(factory_code)),
        "state_read_reference": "latest",
        "historical_state_available_on_public_rpc": False,
        "pool_created_count": len(pools),
        "event_counts": event_counts,
        "l1_fixture_sufficient": density_ok,
    }


def run_full(
    client: RpcClient,
    out: pathlib.Path,
    start_block: int,
    end_block: int,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    blocks_path = out / "decoded" / "blocks.jsonl"
    blocks_path.parent.mkdir(parents=True, exist_ok=True)
    previous_hash = None
    continuity_ok = True
    block_count = 0
    with blocks_path.open("wb") as fh:
        for number in range(start_block, end_block + 1):
            b = block_header(client, number)
            row = {
                "number": hex_int(b.get("number")),
                "hash": b.get("hash"),
                "parentHash": b.get("parentHash"),
                "timestamp": hex_int(b.get("timestamp")),
                "gasUsed": hex_int(b.get("gasUsed")),
                "baseFeePerGas": hex_int(b.get("baseFeePerGas")) if b.get("baseFeePerGas") else None,
            }
            if previous_hash is not None and row["parentHash"] != previous_hash:
                continuity_ok = False
            previous_hash = row["hash"]
            fh.write(canonical_bytes(row) + b"\n")
            block_count += 1

    pools = []
    pools_file = out / "decoded" / "pools-created.jsonl"
    if pools_file.exists():
        with pools_file.open("r", encoding="utf-8") as fh:
            pools = [json.loads(line) for line in fh if line.strip()]

    addresses = sorted({p["pool"] for p in pools})
    event_topics = [[TOPICS[n] for n in ("Initialize", "Mint", "Burn", "Collect", "Swap")]]
    all_logs: list[dict[str, Any]] = []
    for addr_chunk in chunks(addresses, 50):
        logs = get_logs_split(client, addr_chunk, start_block, end_block, event_topics)
        all_logs.extend(logs)
    all_logs.sort(key=event_sort_key)
    write_jsonl(out / "raw" / "pool-event-logs.jsonl", all_logs)

    unique_txs = sorted({log.get("transactionHash") for log in all_logs if log.get("transactionHash")})
    tx_rows = []
    receipt_rows = []
    receipt_classification = {"success": 0, "failed": 0, "unknown": 0}
    for txh in unique_txs:
        tx = client.call("eth_getTransactionByHash", [txh])
        receipt = client.call("eth_getTransactionReceipt", [txh])
        if tx is None or receipt is None:
            raise RuntimeError(f"unresolvable event transaction/receipt: {txh}")
        tx_rows.append(
            {
                "hash": txh,
                "transactionIndex": hex_int(tx.get("transactionIndex")),
                "blockNumber": hex_int(tx.get("blockNumber")),
                "from": tx.get("from"),
                "to": tx.get("to"),
                "input": tx.get("input"),
            }
        )
        status_raw = receipt.get("status")
        if status_raw == "0x1":
            classification = "success"
        elif status_raw == "0x0":
            classification = "failed"
        else:
            classification = "unknown"
        receipt_classification[classification] += 1
        receipt_rows.append(
            {
                "transactionHash": txh,
                "status": status_raw,
                "classification": classification,
                "gasUsed": hex_int(receipt.get("gasUsed")),
                "effectiveGasPrice": hex_int(receipt.get("effectiveGasPrice")) if receipt.get("effectiveGasPrice") else None,
                "logs": receipt.get("logs") or [],
            }
        )
    write_jsonl(out / "decoded" / "transactions.jsonl", tx_rows)
    write_jsonl(out / "decoded" / "receipts.jsonl", receipt_rows)

    token_addresses = sorted({p[k] for p in pools for k in ("token0", "token1")})
    metadata = []
    for token in token_addresses:
        row: dict[str, Any] = {"address": token, "state_reference": "latest"}
        for field, selector in CALL_SELECTORS.items():
            try:
                raw = client.call("eth_call", [{"to": token, "data": selector}, "latest"])
                row[field + "_raw"] = raw
                if field == "decimals" and raw and raw != "0x":
                    row[field] = int(raw, 16)
                else:
                    row[field] = decode_abi_string(raw)
            except Exception as exc:
                row[field + "_error"] = f"{type(exc).__name__}: {exc}"
        metadata.append(row)
    write_jsonl(out / "decoded" / "token-metadata.jsonl", metadata)

    duplicate_keys = set()
    seen = set()
    for log in all_logs:
        key = (
            CHAIN_ID_DEC,
            log.get("blockHash"),
            log.get("transactionHash"),
            hex_int(log.get("logIndex")),
        )
        if key in seen:
            duplicate_keys.add(key)
        seen.add(key)

    return {
        **preflight,
        "block_count": block_count,
        "block_continuity_ok": continuity_ok,
        "event_transaction_count": len(unique_txs),
        "receipt_classification": receipt_classification,
        "duplicate_event_log_keys": len(duplicate_keys),
    }


def build_file_manifest(out: pathlib.Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        rel = str(path.relative_to(out))
        rows.append(
            {
                "path": rel,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preflight", "full"), default="preflight")
    parser.add_argument("--out", default="artifacts/xl002-l0")
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw_log = out / "raw" / "rpc-requests.jsonl"
    client = RpcClient(RPC_URL, raw_log)

    start_ts = parse_utc(WINDOW_START)
    end_ts = parse_utc(WINDOW_END)

    chain_id = client.call("eth_chainId", [])
    if chain_id != CHAIN_ID_HEX:
        raise RuntimeError(f"chain id mismatch: expected {CHAIN_ID_HEX}, got {chain_id}")

    latest_hex = client.call("eth_blockNumber", [])
    latest = hex_int(latest_hex)
    start_block = find_first_block_at_or_after(client, start_ts, latest)
    first_at_or_after_end = find_first_block_at_or_after(client, end_ts, latest)
    end_block = first_at_or_after_end - 1
    if end_block < start_block:
        raise RuntimeError("resolved empty block window")

    start_header = block_header(client, start_block)
    end_header = block_header(client, end_block)

    preflight = run_preflight(client, out, start_block, end_block)
    result = {
        "schema": "xl002-l0-v1",
        "mode": args.mode,
        "performance_computed": False,
        "chain_id": CHAIN_ID_DEC,
        "chain_id_hex": chain_id,
        "rpc_url": RPC_URL,
        "factory": FACTORY,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "start_block": start_block,
        "start_block_hash": start_header.get("hash"),
        "start_block_timestamp": hex_int(start_header.get("timestamp")),
        "end_block": end_block,
        "end_block_hash": end_header.get("hash"),
        "end_block_timestamp": hex_int(end_header.get("timestamp")),
        "block_span": end_block - start_block + 1,
        **preflight,
    }

    if args.mode == "full":
        result = run_full(client, out, start_block, end_block, preflight) | {
            k: v for k, v in result.items() if k not in preflight
        }

    result["rpc_request_count"] = client.request_count
    result["rpc_failure_attempts"] = client.failure_count

    if args.mode == "full":
        l0_pass = (
            result.get("block_continuity_ok") is True
            and result.get("duplicate_event_log_keys") == 0
            and result.get("receipt_classification", {}).get("failed", 0) == 0
            and result.get("receipt_classification", {}).get("unknown", 0) == 0
        )
        result["l0_integrity_status"] = "PASS" if l0_pass else "FAIL"
        result["l1_fixture_status"] = "SUFFICIENT" if result["l1_fixture_sufficient"] else "INSUFFICIENT_ACTIVITY"
    else:
        result["l0_integrity_status"] = "PRECHECK_ONLY"
        result["l1_fixture_status"] = "PRECHECK_SUFFICIENT" if result["l1_fixture_sufficient"] else "PRECHECK_INSUFFICIENT"

    write_json(out / "quality-report.json", result)
    write_json(out / "file-manifest.json", build_file_manifest(out))

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"XL002_L0_FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
