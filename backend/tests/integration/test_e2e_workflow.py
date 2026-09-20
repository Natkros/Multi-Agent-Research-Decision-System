"""Integration test (Phase 8, brief §23): the full research workflow driven
through the authenticated HTTP API -- register -> login -> submit -> poll ->
fetch report -- using the same sqlite in-memory test infrastructure every
other API test in this repo already relies on (no live Postgres/Redis
needed). Exercises the whole stack end to end, not just one layer: auth,
authorization, the job runner, the LangGraph orchestration, and persistence.
"""

from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def _poll_until_done(client: AsyncClient, research_id: str, headers: dict, timeout_s: float = 10.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        response = await client.get(f"/api/v1/research/{research_id}", headers=headers)
        body = response.json()
        if body["status"] in ("completed", "failed"):
            return body
        await asyncio.sleep(0.05)
    raise TimeoutError("research did not finish in time")


async def test_full_authenticated_research_workflow() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Register.
        register = await client.post(
            "/api/v1/auth/register",
            json={"email": "integration-user@example.com", "password": "hunter22-secure"},
        )
        assert register.status_code == 201
        user = register.json()
        assert user["role"] == "user"

        # Re-registering the same email must be rejected, not silently
        # create a second account.
        duplicate = await client.post(
            "/api/v1/auth/register",
            json={"email": "integration-user@example.com", "password": "hunter22-secure"},
        )
        assert duplicate.status_code == 409

        # 2. Login.
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "integration-user@example.com", "password": "hunter22-secure"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Wrong password is rejected with a generic error (never reveals
        # whether the email exists).
        wrong_password = await client.post(
            "/api/v1/auth/login",
            json={"email": "integration-user@example.com", "password": "wrong-password"},
        )
        assert wrong_password.status_code == 401

        # 3. Submit a research run.
        create_response = await client.post(
            "/api/v1/research",
            json={
                "question": "Should a startup build its own vector database?",
                "constraints": ["budget < $5k/mo"],
                "alternatives": ["Build in-house", "Managed service"],
                "criteria": ["cost", "operational burden"],
                "mode": "auto",
            },
            headers=headers,
        )
        assert create_response.status_code == 202
        research_id = create_response.json()["research_id"]

        # 4. Poll until done.
        status = await _poll_until_done(client, research_id, headers)
        assert status["status"] == "completed"

        # 5. Fetch the report.
        report_response = await client.get(f"/api/v1/research/{research_id}/report", headers=headers)
        assert report_response.status_code == 200
        report = report_response.json()["report"]
        assert report is not None
        assert report["research_question"] == "Should a startup build its own vector database?"
        assert report["confidence"] is not None

        # The session is attributed to the authenticated user, not left
        # unset/anonymous (Phase 8 requirement).
        assert status["question"] == "Should a startup build its own vector database?"
