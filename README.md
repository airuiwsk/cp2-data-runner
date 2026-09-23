# cp2-data-runner

Public, execution-only runner for the AI-Trading CP2 data-integrity gate.

This repository intentionally contains no trading strategy, signals, return/PnL logic, secrets, or private research. It only runs the frozen CP2 Bybit exact-byte collector/verifier and publishes the resulting GitHub Actions artifact.

Canonical research repository: `airuiwsk/AI-Trading` (private).

## Gate

The runner must preserve original Bybit response bytes, record SHA-256 provenance, verify 1-minute gap/duplicate/ordering checks, and deterministically rebuild normalized CSV files from frozen raw bytes.

A successful workflow alone is not sufficient to mark CP2 PASS; the artifact must be independently inspected and verified in the canonical research repository.
