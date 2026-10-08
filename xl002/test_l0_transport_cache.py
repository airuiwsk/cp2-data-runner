import pathlib, tempfile, unittest
from l0_transport_cache import VerifiedRpcCache, sha

class CacheTest(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "cache.jsonl"
            u = "https://rpc.mainnet.chain.robinhood.com"
            q = {"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{"fromBlock":"0x1"}]}
            a = {"jsonrpc":"2.0","id":1,"result":[]}
            r = {"endpoint":u,"acquired_at":"2026-10-08T00:00:00Z","attempt":1,"request":q,"response":a,"request_sha256":sha(q),"response_sha256":sha(a)}
            c = VerifiedRpcCache(p,u,{"eth_getLogs"})
            c.put(r)
            self.assertEqual(VerifiedRpcCache(p,u,{"eth_getLogs"}).get([("eth_getLogs",q["params"])])[1],[[]])
            p.write_bytes(p.read_bytes().replace(b'"result":[]',b'"result":[1]'))
            with self.assertRaises(ValueError):
                VerifiedRpcCache(p,u,{"eth_getLogs"})

if __name__=="__main__":
    unittest.main()
