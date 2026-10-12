#!/usr/bin/env python3
"""Offline fail-closed tests for XL002 historical Flash transport positive control.

No RPC calls, performance, LP economics, or replay-fidelity assertions.
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent

def load_target():
    stub = types.ModuleType("l0_collect")
    stub.RPC_URL = "https://example.invalid"
    stub.CHAIN_ID_HEX = "0x1237"
    stub.RpcClient = None
    stub.event_topic = lambda sig: "0x" + hashlib.sha256(sig.encode()).hexdigest()
    stub.canonical_bytes = lambda obj: json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    stub.sha256_bytes = lambda data: hashlib.sha256(data).hexdigest()
    stub.utc_now = lambda: "2026-10-12T00:00:00Z"
    spec = importlib.util.spec_from_file_location("xl002_l1_positive_under_test", HERE / "l1_known_positive_control.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"l0_collect": stub}):
        spec.loader.exec_module(module)
    return module

M = load_target()

def positive_flash():
    return {
        "blockNumber": hex(M.BLOCK),
        "blockHash": M.EXPECTED["blockHash"],
        "transactionHash": M.EXPECTED["transactionHash"],
        "logIndex": hex(M.EXPECTED["logIndex"]),
        "address": M.EXPECTED["address"],
        "removed": False,
        "topics": [M.event_topic(M.EVENTS[0]), "0x" + "0" * 64, "0x" + "1" * 64],
        "data": "0x" + "0" * (64 * 4),
    }

class FakeRPC:
    def __init__(self, logs=None, chain="0x1237", header=None, failure=None):
        self.logs = [positive_flash()] if logs is None else logs
        self.chain = chain
        self.header = {"hash": M.EXPECTED["blockHash"]} if header is None else header
        self.failure = failure
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if self.failure == method:
            raise ConnectionError("synthetic RPC transport failure")
        if method == "eth_chainId":
            return self.chain
        if method == "eth_getLogs":
            return self.logs
        if method == "eth_getBlockByNumber":
            return self.header
        raise AssertionError("unexpected RPC method " + method)

class PositiveControlTests(unittest.TestCase):
    def execute(self, rpc):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "xl002-test"
            result = M.run(rpc=rpc, out=out)
            quality = json.loads((out / "quality.json").read_text())
            self.assertEqual(quality, result)
            self.assertFalse(result["performance_computed"])
            self.assertFalse(result["l1_replay_fidelity_pass"])
            self.assertFalse(result["l1_discovery_authorized"])
            self.assertEqual((out / "logs.json").exists(), result["status"] == "TRANSPORT_POSITIVE_CONTROL_PASS")
            return result

    def test_valid_flash_transport_only(self):
        rpc = FakeRPC()
        r = self.execute(rpc)
        self.assertEqual(r["status"], "TRANSPORT_POSITIVE_CONTROL_PASS")
        self.assertEqual(r["positive_flash_count"], 1)
        self.assertEqual([x[0] for x in rpc.calls], ["eth_chainId", "eth_getLogs", "eth_getBlockByNumber"])
        filt = rpc.calls[1][1][0]
        self.assertEqual(filt["fromBlock"], hex(M.BLOCK))
        self.assertEqual(filt["toBlock"], hex(M.BLOCK))
        self.assertEqual(filt["topics"], [sorted(M.event_topic(e).lower() for e in M.EVENTS)])

    def test_missing_flash_blocks(self):
        r = self.execute(FakeRPC(logs=[]))
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("missing or duplicated", r["terminal_error"])

    def test_duplicate_flash_blocks(self):
        log = positive_flash()
        self.assertEqual(self.execute(FakeRPC(logs=[log, dict(log)]))["status"], "BLOCKED")

    def test_chain_mismatch_blocks_before_logs(self):
        rpc = FakeRPC(chain="0x1")
        self.assertEqual(self.execute(rpc)["status"], "BLOCKED")
        self.assertEqual(len(rpc.calls), 1)

    def test_header_hash_mismatch_blocks(self):
        r = self.execute(FakeRPC(header={"hash": "0x" + "f" * 64}))
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("header hash mismatch", r["terminal_error"])

    def test_flash_abi_mismatch_blocks(self):
        log = positive_flash()
        log["data"] = "0x" + "0" * 64
        r = self.execute(FakeRPC(logs=[log]))
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("ABI", r["terminal_error"])

    def test_wrong_block_number_blocks(self):
        log = positive_flash()
        log["blockNumber"] = hex(M.BLOCK + 1)
        self.assertEqual(self.execute(FakeRPC(logs=[log]))["status"], "BLOCKED")

    def test_removed_log_blocks(self):
        log = positive_flash()
        log["removed"] = True
        self.assertEqual(self.execute(FakeRPC(logs=[log]))["status"], "BLOCKED")

    def test_rpc_failure_blocks(self):
        r = self.execute(FakeRPC(failure="eth_getLogs"))
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("ConnectionError", r["terminal_error"])

    def test_unexpected_topic_blocks(self):
        log = positive_flash()
        log["topics"][0] = "0x" + "a" * 64
        self.assertEqual(self.execute(FakeRPC(logs=[log]))["status"], "BLOCKED")

if __name__ == "__main__":
    unittest.main()
