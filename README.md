# cp2-data-runner

Public execution runner for `airuiwsk/AI-Trading`.

This repository is a shared, zero-secret research execution plane. It hosts data-integrity collectors, frozen evaluators, replay/search jobs and other reproducible workflows whose authoritative governance lives in the private `AI-Trading` repository.

## Isolation model

A new research hypothesis does **not** require a new repository by default.

Isolation is provided by:
- project/lane-specific code namespaces;
- lane-specific GitHub Actions workflows and trigger paths;
- lane-prefixed artifacts/evidence;
- frozen input/evaluator identities;
- read-only/default-minimum workflow permissions;
- no wallet/private-key/signing capability for research-only lanes.

Examples already present include T406-T411, FDC001 and XL001.

For XL002, use:
- code: `xl002/`;
- workflows: `.github/workflows/xl002-*.yml`;
- artifacts/triggers: `xl002-*` / `XL002_*`;
- no imports from unrelated candidate/evaluator namespaces.

## Security boundary

No real-capital execution or unrestricted secrets belong in the shared research runner.

If a future stage requires wallet signing, real capital, materially different credentials, or an incompatible runtime/security model, create a separate execution boundary at that point.

## Canonical authority

Canonical research/governance repository: `airuiwsk/AI-Trading`.

A successful workflow is never sufficient by itself to declare a research gate PASS. Results must be interpreted under the frozen contracts and holdout rules in the canonical repository.
