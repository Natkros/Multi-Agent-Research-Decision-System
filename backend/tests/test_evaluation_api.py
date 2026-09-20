"""Tests for GET /api/v1/evaluation/latest (Phase 9, docs/evaluation.md §4)."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config.settings import get_settings
from app.evaluation.runner import EvaluationReport
from app.main import create_app


@pytest.fixture
def app():
    return create_app()


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    email = f"user-{uuid.uuid4().hex[:12]}@example.com"
    register = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-1"}
    )
    assert register.status_code == 201, register.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "correct-horse-1"}
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_latest_evaluation_404_when_no_report_on_disk(app, tmp_path, monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("EVALUATION_REPORT_PATH", str(tmp_path / "nonexistent.json"))
    get_settings.cache_clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _auth_headers(client)
            response = await client.get("/api/v1/evaluation/latest", headers=headers)
        assert response.status_code == 404
    finally:
        get_settings.cache_clear()


async def test_latest_evaluation_returns_report_from_disk(app, tmp_path, monkeypatch) -> None:
    report = EvaluationReport(
        generated_at="2026-01-01T00:00:00Z",
        provider="local",
        search_provider="local",
        num_questions=0,
        results=[],
        aggregate={"success_rate": 1.0},
    )
    report_path = tmp_path / "latest.json"
    report_path.write_text(report.model_dump_json(), encoding="utf-8")

    monkeypatch.setenv("EVALUATION_REPORT_PATH", str(report_path))
    get_settings.cache_clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _auth_headers(client)
            response = await client.get("/api/v1/evaluation/latest", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "local"
        assert body["aggregate"]["success_rate"] == 1.0
    finally:
        get_settings.cache_clear()


async def test_latest_evaluation_requires_auth(app) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/evaluation/latest")
    assert response.status_code == 401
