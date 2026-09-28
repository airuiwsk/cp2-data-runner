# T413 runner staging

Trial T413 / EH-20260928-019.

Authoritative evaluator remains frozen in airuiwsk/AI-Trading at blob:
`4a11fbdef1f5f47aaf861c08e602f7ffc9c7a2e7`.

Purpose: shared zero-cost execution plane for the single frozen C6.

Rules:
- T412 must not run.
- CP5 must remain unopened.
- No parameter, universe, horizon, cost, residual, placebo, or PASS-condition changes.
- Bybit public trade archive only.
- Performance execution only after exact evaluator and frozen input artifacts are staged byte-for-byte.
