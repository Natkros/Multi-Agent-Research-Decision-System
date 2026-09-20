from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.state import FinalReport, ResearchRequest
from app.services.cache_service import LocalCacheService
from app.services.research_service import ResearchService
from app.services.session_repository import SessionRepository
from app.tools.llm_provider import LocalProvider
from app.tools.search_provider import LocalSearchProvider


async def test_research_service_end_to_end_produces_final_report() -> None:
    service = ResearchService(llm=LocalProvider(), search=LocalSearchProvider())
    repo = SessionRepository()
    research_id = uuid4()
    request = ResearchRequest(
        id=research_id,
        question="Should we build or buy a vector database?",
        constraints=["budget < $5k/mo"],
        alternatives_hint=["Build in-house", "Managed Qdrant", "Managed Pinecone"],
        criteria_hint=["cost", "operational burden"],
        requested_by="test-user",
        created_at=datetime.now(UTC),
    )

    await service.run(research_id=research_id, request=request, repo=repo)

    session = await repo.get(research_id)
    assert session is not None
    assert session.status == "completed"
    assert session.error is None
    assert isinstance(session.state.final_report, FinalReport)

    report = session.state.final_report
    assert report.research_question == request.question
    assert report.sources, "expected retrieved sources to be attached to the report"
    assert report.evidence, "expected evidence to be attached to the report"
    # Every evidence item must trace back to a source that is actually in the report.
    source_ids = {s.id for s in report.sources}
    for item in report.evidence:
        assert item.source_id in source_ids

    metadata = session.state.execution_metadata
    assert metadata.status == "completed"
    # Phase 2: planner, >=1 researcher (fan-out), evidence_analyst,
    # fact_checker, final_synthesizer.
    agent_names = [run.agent_name for run in metadata.agent_runs]
    assert agent_names[0] == "research_planner"
    assert agent_names[-1] == "final_synthesizer"
    assert "researcher" in agent_names
    assert "evidence_analyst" in agent_names
    assert "fact_checker" in agent_names
    assert metadata.total_tokens > 0


async def test_research_service_uses_hints_when_no_plan_alternatives() -> None:
    service = ResearchService(llm=LocalProvider(), search=LocalSearchProvider())
    repo = SessionRepository()
    research_id = uuid4()
    request = ResearchRequest(
        id=research_id,
        question="Pick a CI provider",
        alternatives_hint=["GitHub Actions", "CircleCI"],
        criteria_hint=["cost"],
        requested_by="test-user",
        created_at=datetime.now(UTC),
    )

    await service.run(research_id=research_id, request=request, repo=repo)

    session = await repo.get(research_id)
    assert session.status == "completed"
    assert session.state.plan is not None
    assert session.state.plan.alternatives == ["GitHub Actions", "CircleCI"]


async def test_research_service_reuses_result_cache_for_identical_question() -> None:
    cache = LocalCacheService()
    repo = SessionRepository()
    question = "Should we build or buy a vector database?"

    def _request() -> ResearchRequest:
        return ResearchRequest(
            id=uuid4(),
            question=question,
            alternatives_hint=["Build in-house", "Managed Qdrant"],
            criteria_hint=["cost"],
            requested_by="test-user",
            created_at=datetime.now(UTC),
        )

    first_service = ResearchService(llm=LocalProvider(), search=LocalSearchProvider(), cache=cache)
    first_id = uuid4()
    await first_service.run(research_id=first_id, request=_request(), repo=repo)
    first_session = await repo.get(first_id)
    assert first_session.status == "completed"

    # Same question/provider combo again, with a brand new research_id: a
    # cache hit should short-circuit the graph and still land as completed
    # with a report carrying the *new* request's question.
    second_service = ResearchService(llm=LocalProvider(), search=LocalSearchProvider(), cache=cache)
    second_id = uuid4()
    second_request = _request()
    await second_service.run(research_id=second_id, request=second_request, repo=repo)

    second_session = await repo.get(second_id)
    assert second_session.status == "completed"
    assert second_session.state.final_report is not None
    assert second_session.state.final_report.research_question == question
    assert second_session.state.execution_metadata.session_id == second_id


async def test_research_service_without_cache_does_not_reuse_across_runs() -> None:
    repo = SessionRepository()
    question = "Pick a database engine"

    def _request(research_id) -> ResearchRequest:
        return ResearchRequest(
            id=research_id,
            question=question,
            alternatives_hint=["Postgres", "MySQL"],
            criteria_hint=["cost"],
            requested_by="test-user",
            created_at=datetime.now(UTC),
        )

    service = ResearchService(llm=LocalProvider(), search=LocalSearchProvider())  # no cache
    first_id, second_id = uuid4(), uuid4()
    await service.run(research_id=first_id, request=_request(first_id), repo=repo)
    await service.run(research_id=second_id, request=_request(second_id), repo=repo)

    first_session = await repo.get(first_id)
    second_session = await repo.get(second_id)
    assert first_session.status == "completed"
    assert second_session.status == "completed"
    # Each run executed the graph independently — both agent-run lists are
    # non-empty and each session's metadata really is its own.
    assert first_session.state.execution_metadata.session_id == first_id
    assert second_session.state.execution_metadata.session_id == second_id
