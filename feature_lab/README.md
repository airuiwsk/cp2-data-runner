# Feature Lab

Status: FD0/FD1 infrastructure only.

This path is an isolated deterministic compute plane for future Feature Discovery Campaigns (FDCs).

Current guarantees under test:
- typed causal AST/DSL only;
- no unrestricted model-generated Python;
- deterministic expression hashing;
- explicit rejection of leads/centered windows/dimension mismatch;
- causal future-mutation invariant;
- synthetic positive/null controls;
- fixed-seed reproducibility.

No real market feature search is authorized until FD2 calibration is frozen and passes.
