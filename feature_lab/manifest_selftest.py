from copy import deepcopy
from manifest import manifest_hash, validate_manifest

BASE={
 "fdc_id":"FDC000","status":"FROZEN","objective":"synthetic infrastructure proof",
 "market_surface":"SYNTHETIC","instruments":["SYNTH"],"data_source":"synthetic_only",
 "d0_search_window":{"start":"2000-01-01","end":"2005-01-01"},
 "d1_walk_forward_folds":[
   {"train":{"start":"2000-01-01","end":"2002-01-01"},"validation":{"start":"2002-01-01","end":"2003-01-01"}},
   {"train":{"start":"2000-01-01","end":"2003-01-01"},"validation":{"start":"2003-01-01","end":"2004-01-01"}}
 ],
 "d2_sealed_confirmation":{"start":"2005-01-01","end":"2006-01-01"},
 "d3_reserved_cp5":{"start":"2006-01-01","end":"2007-01-01"},
 "label_definition":"synthetic","primary_discovery_objective":"synthetic correlation",\n "action_mapping":{"kind":"synthetic_only"},"decision_timing":"synthetic","execution_price_semantics":"synthetic",\n "baseline":"synthetic null","turnover_definition":"synthetic","cost_model":{"kind":"synthetic"},
 "capital_jpy":1000000,"dsl_version":"fd1-v1","generators":["G0_RANDOM"],
 "evaluation_budget_by_generator":{"G0_RANDOM":500},"random_seeds":{"G0_RANDOM":7},
 "max_ast_depth":6,"max_complexity":20,"ranking_rule":"synthetic",
 "turnover_cap":1.0,"minimum_n":100,"champion_count":1,
 "null_control":"synthetic independent target","positive_control":"weak planted causal lag",
 "forbidden_data":["real_market"],"lineage":[]
}
BASE["manifest_sha256"]=manifest_hash(BASE)
assert validate_manifest(BASE)["valid"]

bad=deepcopy(BASE)
bad["d2_sealed_confirmation"]={"start":"2004-01-01","end":"2006-01-01"}
bad["manifest_sha256"]=manifest_hash(bad)
try:
    validate_manifest(bad)
    raise AssertionError("overlap accepted")
except ValueError as e:
    assert "disjoint" in str(e)

bad2=deepcopy(BASE)
bad2["manifest_sha256"]="0"*64
try:
    validate_manifest(bad2)
    raise AssertionError("bad hash accepted")
except ValueError as e:
    assert "mismatch" in str(e)

print('{"fd1_manifest_invariants":"PASS","real_market_data_loaded":false}')
