# XL002 runner namespace

Purpose: execution-only namespace for `XL-20260927-002` autonomous liquidity / market-structure research.

Canonical governance and frozen contracts live in `airuiwsk/AI-Trading`.

## L0-L4 rules

- research/read-only execution only;
- no wallet, private key, transaction signing or real capital;
- no repository secrets unless a future frozen non-trading data contract explicitly requires one;
- do not import T406/T410/T411/XL001/FDC001 candidate or evaluator code;
- workflows must be named `.github/workflows/xl002-*.yml`;
- artifacts must be prefixed `xl002-`;
- repository permissions default to `contents: read`;
- performance/holdout access is controlled by the canonical frozen XL002 contracts.

## Current frozen L0 target

- Robinhood Chain mainnet, chain id 4663;
- Uniswap v3 only;
- UTC window 2026-07-02T00:00:00Z inclusive to 2026-07-03T00:00:00Z exclusive;
- raw-first block/log acquisition and hashes;
- no LP PnL, APR/APY, ranking, signal or net-edge computation.

Next implementation: deterministic read-only L0 collector + dedicated `xl002-l0` workflow.
