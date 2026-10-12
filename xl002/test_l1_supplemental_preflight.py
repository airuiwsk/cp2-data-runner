#!/usr/bin/env python3
"""Offline, outcome-blind fail-closed tests for XL002 four-topic transport preflight.

All RPC responses are synthetic. Passing these tests is NOT live-RPC evidence,
complete supplemental coverage, historical-state validation or replay fidelity.
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
    l0 = types.ModuleType("l0_collect")
    l0.RPC_URL = "https://example.invalid"
    l0.CHAIN_ID_HEX = "0x1237"
    l0.RpcClient = None
    l0.event_topic = lambda sig: "0x" + hashlib.sha256(sig.encode()).hexdigest()
    l0.canonical_bytes = lambda obj: json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    l0.sha256_bytes = lambda data: hashlib.sha256(data).hexdigest()
    l0.utc_now = lambda: "2026-10-12T00:00:00Z"

    control = types.ModuleType("l1_known_positive_control")
    control.BLOCK = 1234595
    control.EXPECTED = {
        "blockHash": "0x" + "1" * 64,
        "transactionHash": "0x" + "2" * 64,
        "logIndex": 21,
        "address": "0x" + "3" * 40,
    }
    control.EVENTS = (
        "Flash(address,address,uint256,uint256,uint256,uint256)",
        "SetFeeProtocol(uint8,uint8,uint8,uint8)",
        "CollectProtocol(address,address,uint128,uint128)",
        "IncreaseObservationCardinalityNext(uint16,uint16)",
    )
    def positive_control(rpc=None, out=None):
        rpc.control_calls += 1
        return {"status": "BLOCKED" if rpc.control_fails else "TRANSPORT_POSITIVE_CONTROL_PASS"}
    control.run = positive_control

    spec = importlib.util.spec_from_file_location("xl002_supplemental_under_test", HERE / "l1_supplemental_preflight.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"l0_collect": l0, "l1_known_positive_control": control}):
        spec.loader.exec_module(module)
    return module


M = load_target()


def known_flash():
    return {
        "blockNumber": hex(M.BLOCK),
        "blockHash": M.EXPECTED["blockHash"],
        "transactionHash": M.EXPECTED["transactionHash"],
        "logIndex": hex(M.EXPECTED["logIndex"]),
        "address": M.EXPECTED["address"],
        "topics": [M.event_topic(M.EVENTS[0])],
        "removed": False,
    }


class FakeRPC:
    def __init__(self, logs=None, chain="0x1237", control_fails=False, fail_method=None):
        self.logs = [known_flash()] if logs is None else logs
        self.chain = chain
        self.control_fails = control_fails
        self.fail_method = fail_method
        self.control_calls = 0
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == self.fail_method:
            raise ConnectionError("synthetic transport failure")
        if method == "eth_chainId":
            return self.chain
        if method == "eth_getLogs":
            return self.logs
        raise AssertionError("unexpected RPC method " + method)


class SupplementalPreflightTests(unittest.TestCase):
    def execute(self, rpc):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "xl002-supplemental"
            result = M.run(rpc=rpc, out=out)
            self.assertEqual(json.loads((out / "quality.json").read_text()), result)
            self.assertFalse(result["performance_computed"])
            self.assertFalse(result["l1_replay_fidelity_pass"])
            self.assertFalse(result["l1_strategy_discovery_authorized"])
            self.assertFalse(result["full_supplemental_coverage"])
            self.assertEqual((out / "range-logs.json").exists(), result["status"] == "SUPPLEMENTAL_TOPIC_TRANSPORT_PREFLIGHT_PASS")
            return result

    def test_valid_bounded_transport_only(self):
        rpc = FakeRPC()
        result = self.execute(rpc)
        self.assertEqual(result["status"], "SUPPLEMENTAL_TOPIC_TRANSPORT_PREFLIGHT_PASS")
        self.assertEqual(result["positive_flash_count"], 1)
        self.assertEqual(result["log_count"], 1)
        self.assertEqual(rpc.control_calls, 1)
        self.assertEqual([m for m, _ in rpc.calls], ["eth_chainId", "eth_getLogs"])
        filt = rpc.calls[1][1][0]
        self.assertEqual(filt["fromBlock"], hex(M.RANGE_START))
        self.assertEqual(filt["toBlock"], hex(M.RANGE_END))
        self.assertEqual(filt["topics"], [sorted(M.event_topic(e).lower() for e in M.EVENTS)])
        self.assertTrue(M.START_BLOCK <= M.RANGE_START <= M.BLOCK <= M.RANGE_END <= M.END_BLOCK)
        self.assertLessEqual(M.RANGE_END - M.RANGE_START + 1, 5000)

    def test_control_failure_blocks_without_rpc(self):
        rpc = FakeRPC(control_fails=True)
        self.assertEqual(self.execute(rpc)["status"], "BLOCKED")
        self.assertEqual(rpc.calls, [])

    def test_chain_mismatch_blocks_before_log_query(self):
        rpc = FakeRPC(chain="0x1")
        self.assertEqual(self.execute(rpc)["status"], "BLOCKED")
        self.assertEqual([m for m, _ in rpc.calls], ["eth_chainId"])

    def test_rpc_failure_blocks(self):
        result = self.execute(FakeRPC(fail_method="eth_getLogs"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("ConnectionError", result["terminal_error"])

    def test_nonlist_response_blocks(self):
        self.assertEqual(self.execute(FakeRPC(logs={"result": []}))["status"], "BLOCKED")

    def test_known_flash_missing_blocks(self):
        result = self.execute(FakeRPC(logs=[]))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("known-positive Flash missing", result["terminal_error"])

    def test_duplicate_identity_blocks(self):
        log = known_flash()
        result = self.execute(FakeRPC(logs=[log, dict(log)]))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("duplicate event identity", result["terminal_error"])

    def test_wrong_topic_blocks(self):
        log = known_flash()
        log["topics"] = ["0x" + "a" * 64]
        self.assertEqual(self.execute(FakeRPC(logs=[log]))["status"], "BLOCKED")

    def test_out_of_range_block_blocks(self):
        log = known_flash()
        log["blockNumber"] = hex(M.RANGE_END + 1)
        self.assertEqual(self.execute(FakeRPC(logs=[log]))["status"], "BLOCKED")

    def test_removed_log_blocks(self):
        log = known_flash()
        log["removed"] = True
        self.assertEqual(self.execute(FakeRPC(logs=[log]))["status"], "BLOCKED")

    def test_malformed_log_blocks(self):
        self.assertEqual(self.execute(FakeRPC(logs=[None]))["status"], "BLOCKED")

    def test_other_supplemental_event_is_counted(self):
        other = known_flash()
        other["topics"] = [M.event_topic(M.EVENTS[1])]
        other["logIndex"] = "0x16"
        result = self.execute(FakeRPC(logs=[known_flash(), other]))
        self.assertEqual(result["status"], "SUPPLEMENTAL_TOPIC_TRANSPORT_PREFLIGHT_PASS")
        self.assertEqual(result["topic_counts"][M.EVENTS[1]], 1)


if __name__ == "__main__":
    unittest.main()
