from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


async def _auth_headers(client: AsyncClient, *, email: str | None = None) -> dict[str, str]:
    """Phase 8: every `/api/v1/research*` route now requires a Bearer JWT
    (docs/api.md). Registers a fresh user and logs in, mirroring the flow a
    real client goes through."""
    email = email or f"user-{uuid.uuid4().hex[:12]}@example.com"
    register = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-1"}
    )
    assert register.status_code == 201, register.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "correct-horse-1"}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _poll_until_done(client: AsyncClient, research_id: str, timeout_s: float = 5.0, headers=None):
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        response = await client.get(f"/api/v1/research/{research_id}", headers=headers)
        body = response.json()
        if body["status"] in ("completed", "failed"):
            return body
        await asyncio.sleep(0.05)
    raise TimeoutError("research did not finish in time")


async def test_health_endpoint(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_submit_and_poll_research_flow(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
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
        created = create_response.json()
        assert created["status"] == "pending"
        research_id = created["research_id"]

        final = await _poll_until_done(client, research_id, headers=headers)

    assert final["status"] == "completed"
    assert final["report"] is not None
    assert final["report"]["research_question"] == (
        "Should a startup build its own vector database?"
    )


async def test_research_endpoints_require_auth(app) -> None:
    """Phase 8: every /api/v1/research* route requires a Bearer JWT except
    health checks -- a request with no token must be rejected, not silently
    treated as some default/anonymous user."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        assert health.status_code == 200

        no_auth = await client.post("/api/v1/research", json={"question": "x"})
        assert no_auth.status_code == 401

        bad_token = await client.get(
            "/api/v1/research/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert bad_token.status_code == 401


async def test_get_unknown_research_returns_404(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.get(
            "/api/v1/research/00000000-0000-0000-0000-000000000000", headers=headers
        )
    assert response.status_code == 404


async def test_phase7_read_endpoints_after_completion(app) -> None:
    """Covers the Phase 7 additions: /sources, /claims, /evidence, /decision,
    /trace, /report and the list endpoint -- all thin reads over an already
    completed `ResearchState`."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
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
        research_id = create_response.json()["research_id"]
        status = await _poll_until_done(client, research_id, headers=headers)

        assert status["status"] == "completed"
        assert status["stage"] == "complete"
        assert status["progress"]["completed_stages"] == status["progress"]["total_stages"]
        assert status["question"] == "Should a startup build its own vector database?"

        listing = await client.get("/api/v1/research", headers=headers)
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert any(item["research_id"] == research_id for item in items)

        sources = await client.get(f"/api/v1/research/{research_id}/sources", headers=headers)
        assert sources.status_code == 200
        assert len(sources.json()["sources"]) > 0

        claims = await client.get(f"/api/v1/research/{research_id}/claims", headers=headers)
        assert claims.status_code == 200
        assert len(claims.json()["claims"]) > 0

        evidence = await client.get(f"/api/v1/research/{research_id}/evidence", headers=headers)
        assert evidence.status_code == 200
        assert len(evidence.json()["evidence"]) > 0
        filtered = await client.get(
            f"/api/v1/research/{research_id}/evidence",
            params={"min_confidence": 1.0},
            headers=headers,
        )
        assert filtered.status_code == 200
        assert len(filtered.json()["evidence"]) <= len(evidence.json()["evidence"])

        decision = await client.get(f"/api/v1/research/{research_id}/decision", headers=headers)
        assert decision.status_code == 200
        assert decision.json()["decision_matrix"]["recommended"]

        trace = await client.get(f"/api/v1/research/{research_id}/trace", headers=headers)
        assert trace.status_code == 200
        agent_names = [r["agent_name"] for r in trace.json()["execution_metadata"]["agent_runs"]]
        assert agent_names[0] == "research_planner"
        assert agent_names[-1] == "final_synthesizer"

        report = await client.get(f"/api/v1/research/{research_id}/report", headers=headers)
        assert report.status_code == 200
        assert report.json()["report"]["research_question"] == (
            "Should a startup build its own vector database?"
        )


async def test_concurrent_polling_does_not_corrupt_session_state(app) -> None:
    """Regression test: SessionRepository's sqlite (StaticPool, single shared
    connection) engine could, under concurrent GET polling racing a run's
    final multi-statement write, persist a session that reads back with
    status="completed" but empty sources/no final_report. Fixed by
    serializing sqlite reads/writes through `SessionRepository._db_lock`.
    Runs the same question twice end-to-end through the real HTTP API with
    tight polling (like a frontend's useResearchStatus hook) to catch a
    regression of that race."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        for _ in range(2):
            create_response = await client.post(
                "/api/v1/research",
                json={"question": "Should a startup build its own vector database?", "mode": "auto"},
                headers=headers,
            )
            research_id = create_response.json()["research_id"]
            status = await _poll_until_done(client, research_id, headers=headers)
            assert status["status"] == "completed"

            sources = await client.get(f"/api/v1/research/{research_id}/sources", headers=headers)
            assert len(sources.json()["sources"]) > 0

            report = await client.get(f"/api/v1/research/{research_id}/report", headers=headers)
            assert report.json()["report"] is not None


async def test_cross_user_cannot_read_or_cancel_others_research(app) -> None:
    """Phase 8 authorization: user B must not be able to read or cancel
    user A's research session (docs/architecture.md §14, brief §27)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers_a = await _auth_headers(client)
        headers_b = await _auth_headers(client)

        create_response = await client.post(
            "/api/v1/research",
            json={"question": "Should a startup build its own vector database?", "mode": "auto"},
            headers=headers_a,
        )
        research_id = create_response.json()["research_id"]

        for path in ("", "/sources", "/claims", "/evidence", "/decision", "/trace", "/report"):
            response = await client.get(f"/api/v1/research/{research_id}{path}", headers=headers_b)
            assert response.status_code == 403, f"path={path!r} leaked cross-user data"

        cancel_response = await client.post(
            f"/api/v1/research/{research_id}/cancel", headers=headers_b
        )
        assert cancel_response.status_code == 403

        # The owner can still read/cancel their own session.
        own_read = await client.get(f"/api/v1/research/{research_id}", headers=headers_a)
        assert own_read.status_code == 200

        listing_b = await client.get("/api/v1/research", headers=headers_b)
        assert all(item["research_id"] != research_id for item in listing_b.json()["items"])


async def test_cancel_research_session(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        create_response = await client.post(
            "/api/v1/research",
            json={"question": "Should a startup build its own vector database?", "mode": "auto"},
            headers=headers,
        )
        research_id = create_response.json()["research_id"]

        cancel_response = await client.post(
            f"/api/v1/research/{research_id}/cancel", headers=headers
        )
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"

        status = await client.get(f"/api/v1/research/{research_id}", headers=headers)
        assert status.json()["status"] == "cancelled"

        # Cancelling an already-cancelled session is rejected, not silently
        # accepted a second time.
        second_cancel = await client.post(
            f"/api/v1/research/{research_id}/cancel", headers=headers
        )
        assert second_cancel.status_code == 409


async def test_research_creation_is_rate_limited_per_user(app) -> None:
    """Phase 8: POST /api/v1/research (the expensive endpoint) is rate
    limited per user via a token bucket (docs/api.md). Default capacity is
    small enough to exhaust within one test."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        from app.config.settings import get_settings

        capacity = get_settings().rate_limit_research_capacity

        statuses = []
        for _ in range(capacity + 2):
            response = await client.post(
                "/api/v1/research",
                json={"question": "Should a startup build its own vector database?", "mode": "auto"},
                headers=headers,
            )
            statuses.append(response.status_code)

        assert 429 in statuses, f"expected a 429 within {capacity + 2} rapid requests, got {statuses}"


async def test_phase7_endpoints_404_for_unknown_research(app) -> None:
    transport = ASGITransport(app=app)
    unknown = "00000000-0000-0000-0000-000000000000"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        for path in ("sources", "claims", "evidence", "decision", "trace", "report"):
            response = await client.get(f"/api/v1/research/{unknown}/{path}", headers=headers)
            assert response.status_code == 404
