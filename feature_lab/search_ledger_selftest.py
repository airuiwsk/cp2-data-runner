import tempfile
from search_ledger import summarize, write_jsonl

H="a"*64
rows=[]
for i in range(3):
    rows.append({
      "fdc_id":"FDC000","evaluation_index":i,"expression_hash":H if i<2 else "b"*64,
      "normalized_ast":{"type":"field","name":"x0"},"generator":"G0_RANDOM",
      "parent_hashes":[],"random_seed":7,"valid":True,"invalid_reason":None,
      "complexity":1,"discovery_fold_summary":{},"turnover_summary":{},
      "cost_summary":{},"redundancy_cluster":None,"selected_as_champion":i==2,
      "evaluated_at_utc":"2000-01-01T00:00:00Z"
    })
s=summarize(rows)
assert s["raw_expression_evaluations"]==3
assert s["unique_expression_hashes"]==2
assert s["duplicate_evaluations"]==1
assert s["champion_rows"]==1
with tempfile.NamedTemporaryFile() as f:
    write_jsonl(rows,f.name)
print('{"feature_search_ledger_invariants":"PASS"}')
