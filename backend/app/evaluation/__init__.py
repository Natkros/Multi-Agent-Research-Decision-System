"""Phase 9 evaluation framework (docs/evaluation.md).

Shared logic lives here so `backend/scripts/evaluate_system.py` stays a thin
CLI: `benchmark.py` (the fixed question set), `metrics.py` (pure metric
functions), `runner.py` (the harness that runs the benchmark through the
graph and aggregates metrics into an `EvaluationReport`).
"""

from __future__ import annotations
