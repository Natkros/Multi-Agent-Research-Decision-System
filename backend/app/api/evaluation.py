"""Evaluation report read endpoint (Phase 9, docs/evaluation.md §4).

Thin router only: reads the static JSON report `scripts/evaluate_system.py`
already wrote to disk and returns it. No live evaluation run happens on
request -- this is a read of a static artifact, not a "run the benchmark
now" endpoint (that stays a manual/CI-optional CLI step, per the brief)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_settings_dep
from app.config.settings import Settings
from app.evaluation.runner import EvaluationReport
from app.security.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

# backend/app/api/evaluation.py -> backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _resolve_report_path(settings: Settings) -> Path:
    path = Path(settings.evaluation_report_path)
    return path if path.is_absolute() else _BACKEND_ROOT / path


@router.get("/latest", response_model=EvaluationReport)
async def get_latest_evaluation(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> EvaluationReport:
    path = _resolve_report_path(settings)
    if not path.exists():
        raise HTTPException(status_code=404, detail="EVALUATION_REPORT_NOT_FOUND")
    data = json.loads(path.read_text(encoding="utf-8"))
    return EvaluationReport.model_validate(data)
