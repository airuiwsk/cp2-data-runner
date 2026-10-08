"""Fail-closed raw JSON-RPC cache for XL002 outcome-blind transport."""
import hashlib
import json
import pathlib
import threading

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def sha(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()

class VerifiedRpcCache:
    def __init__(self, path, endpoint, methods):
        self.path = pathlib.Path(path)
        self.endpoint = endpoint
        self.methods = methods
        self.lock = threading.RLock()
        self.index = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with self.path.open("rb") as fh:
                while True:
                    offset = fh.tell()
                    line = fh.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        raise ValueError("incomplete raw cache record")
                    record = json.loads(line)
                    key, result_sha, _ = self._validate(record)
                    if key in self.index and self.index[key][1] != result_sha:
                        raise ValueError("conflicting historical RPC results")
                    self.index.setdefault(key, (offset, result_sha))

    def _validate(self, record):
        if record.get("endpoint") != self.endpoint or not record.get("acquired_at"):
            raise ValueError("RPC provenance/endpoint mismatch")
        if not isinstance(record.get("attempt"), int) or record["attempt"] < 1:
            raise ValueError("invalid retry provenance")
        req, resp = record.get("request"), record.get("response")
        if sha(req) != record.get("request_sha256") or sha(resp) != record.get("response_sha256"):
            raise ValueError("RPC request/response SHA-256 mismatch")
        requests = req if isinstance(req, list) else [req]
        responses = resp if isinstance(resp, list) else [resp]
        if not requests or len(requests) != len(responses):
            raise ValueError("RPC response cardinality mismatch")
        if not all(isinstance(x, dict) and x.get("jsonrpc") == "2.0" and x.get("id") is not None for x in requests):
            raise ValueError("invalid RPC requests")
        ids = [x["id"] for x in requests]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate RPC request IDs")
        calls = [[x.get("method"), x.get("params")] for x in requests]
        if any(m not in self.methods or not isinstance(p, list) for m, p in calls):
            raise ValueError("unapproved cached method or params")
        if not all(isinstance(x, dict) for x in responses):
            raise ValueError("invalid RPC responses")
        by_id = {x.get("id"): x for x in responses}
        if len(by_id) != len(requests):
            raise ValueError("duplicate RPC response IDs")
        results = []
        for request in requests:
            response = by_id.get(request["id"])
            if response is None or "error" in response or response.get("result") is None:
                raise ValueError("incomplete/error RPC response")
            result = response["result"]
            if request["method"] == "eth_getLogs" and not isinstance(result, list):
                raise ValueError("invalid eth_getLogs result")
            results.append(result)
        return sha(calls), sha(results), results

    def get(self, calls):
        key = sha([[m, p] for m, p in calls])
        with self.lock:
            found = self.index.get(key)
            if found is None:
                return None
            with self.path.open("rb") as fh:
                fh.seek(found[0])
                record = json.loads(fh.readline())
            verified_key, result_sha, results = self._validate(record)
            if verified_key != key or result_sha != found[1]:
                raise ValueError("RPC cache index integrity mismatch")
            return record, results

    def put(self, record):
        key, result_sha, _ = self._validate(record)
        with self.lock:
            old = self.index.get(key)
            if old is not None:
                if old[1] != result_sha:
                    raise ValueError("conflicting historical RPC results")
                return
            with self.path.open("ab") as fh:
                offset = fh.tell()
                fh.write(canonical(record) + b"\n")
                fh.flush()
            self.index[key] = (offset, result_sha)
