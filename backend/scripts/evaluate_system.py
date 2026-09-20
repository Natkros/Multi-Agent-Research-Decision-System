#!/usr/bin/env python
"""CLI: run the Phase 9 benchmark through the full graph and write an
evaluation report (docs/evaluation.md §4, brief §24-25).

Usage (from `backend/`, with the venv active):

    python scripts/evaluate_system.py
    python scripts/evaluate_system.py --limit 5 --output evaluation_reports/latest.json

Uses `Settings` (`LLM_PROVIDER`, `SEARCH_PROVIDER`, etc.) exactly like the
app does -- with the default `.env` (`llm_provider=local`,
`search_provider=local`) this runs fully offline, matching every other
script in this codebase (see `ingest_documents.py`). CI does not block on
absolute metric thresholds per docs/evaluation.md §4; this script's job is to
prove the harness executes successfully and computes metrics for every
question, and to persist a report the `/api/v1/evaluation/latest` endpoint
can serve.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.settings import get_settings  # noqa: E402
from app.evaluation.benchmark import BENCHMARK  # noqa: E402
from app.evaluation.runner import EvaluationReport, run_benchmark  # noqa: E402
from app.retrieval.hybrid_retrieval import get_hybrid_retriever  # noqa: E402
from app.tools.llm_provider import get_llm_provider  # noqa: E402
from app.tools.search_provider import get_search_provider  # noqa: E402

_DEFAULT_OUTPUT = "evaluation_reports/latest.json"


def _print_summary(report: EvaluationReport) -> None:
    print(f"\nEvaluation report ({report.provider}/{report.search_provider}, "
          f"{report.num_questions} questions, generated {report.generated_at.isoformat()})")
    print("-" * 100)
    print(f"{'id':<10} {'category':<22} {'status':<10} {'evid/claim':>10} {'tokens':>8}")
    print("-" * 100)
    for r in report.results:
        tokens = r.metrics.get("token_usage", {}).get("total_tokens") if r.metrics else None
        evidence_ratio = r.metrics.get("evidence_to_claim_ratio") if r.metrics else None
        print(
            f"{r.question_id:<10} {r.category:<22} {r.status:<10} "
            f"{'-' if evidence_ratio is None else f'{evidence_ratio:.2f}':>10} "
            f"{tokens if tokens is not None else '-':>8}"
        )
    print("-" * 100)
    agg = report.aggregate
    print(f"success_rate: {agg.get('success_rate'):.2f}  "
          f"completed: {agg.get('num_completed')}/{report.num_questions}  "
          f"failed: {agg.get('num_failed')}")
    for key in sorted(agg):
        if key.startswith("mean_") and agg[key] is not None:
            print(f"  {key}: {agg[key]:.3f}")
    print(f"total_tokens: {agg.get('total_tokens')}  total_latency_ms: {agg.get('total_latency_ms'):.1f}")


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    questions = BENCHMARK[: args.limit] if args.limit else BENCHMARK
    llm = get_llm_provider(settings)
    search = get_search_provider(settings)
    kb = get_hybrid_retriever(settings) if args.use_kb else None

    report = await run_benchmark(questions, llm=llm, search=search, settings=settings, kb=kb)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"wrote report to {output_path}")

    _print_summary(report)
    return 0 if report.aggregate.get("num_failed", 0) == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="Only run the first N benchmark questions"
    )
    parser.add_argument(
        "--output", default=_DEFAULT_OUTPUT, help=f"Output JSON path (default: {_DEFAULT_OUTPUT})"
    )
    parser.add_argument(
        "--use-kb",
        action="store_true",
        help="Wire the process's HybridRetriever (RAG) into the run, not just external search",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
