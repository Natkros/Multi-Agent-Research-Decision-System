"""Repository tests (Phase 3, docs/database-schema.md) for the Postgres-backed
`SessionRepository`, exercised against the sqlite/aiosqlite test-mode path
(`app/models/database.py`) so nothing here requires a live Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.config.settings import Settings
from app.models.orm import (
    AgentRunORM,
    AlternativeORM,
    AssumptionORM,
    AuditLogORM,
    ClaimORM,
    CriterionORM,
    DecisionScoreORM,
    ReportORM,
    ResearchPlanORM,
    ResearchSessionORM,
    RiskORM,
    SourceORM,
)
from app.schemas.state import (
    AgentRunMeta,
    AlternativeScore,
    Assumption,
    Claim,
    ClaimVerification,
    DecisionCriteria,
    DecisionMatrix,
    EvidenceItem,
    ExecutionMetadata,
    FinalReport,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
    ResearchState,
    Risk,
    Source,
)
from app.services.session_repository import ResearchSession, SessionRepository


def _in_memory_settings() -> Settings:
    # `database_url=None` -> effective_database_url falls back to sqlite
    # in-memory (app/models/database.py); explicit here for clarity.
    return Settings(database_url=None)


def _request(research_id) -> ResearchRequest:
    return ResearchRequest(
        id=research_id, question="Build or buy?", requested_by="test-user",
        created_at=datetime.now(UTC),
    )


def _full_state(research_id) -> ResearchState:
    now = datetime.now(UTC)
    request = _request(research_id)
    plan = ResearchPlan(
        objective="Pick a strategy", decision_type="build_vs_buy",
        alternatives=["Build", "Buy"],
        criteria=[
            DecisionCriteria(
                name="cost", description="cost", weight=1.0, direction="minimize",
                scoring_method="weighted_score",
            )
        ],
        research_questions=[
            ResearchQuestion(id="rq-1", text="cost", dimension="cost", priority="high")
        ],
        required_evidence=[], constraints=[], assumptions=[],
    )
    source = Source(
        id="src-1", title="t1", url=None, publisher="Acme", author=None,
        published_at=now, retrieved_at=now, source_type="vendor_docs",
        credibility_score=0.8, content_hash="h1",
    )
    claim = Claim(id="claim-1", text="X costs $10/mo", source_id="src-1", research_question_id="rq-1")
    evidence = EvidenceItem(
        id="ev-1", claim_id="claim-1", evidence_text="X costs $10/mo", source_id="src-1",
        evidence_type="documentation", strength="strong", confidence=0.9, limitations=None,
    )
    verified = ClaimVerification(
        claim_id="claim-1", status="VERIFIED", supporting_sources=["src-1"],
        contradicting_sources=[], confidence=0.9, explanation="ok",
    )
    risk = Risk(
        id="risk-0-financial", category="financial", description="Vendor price hike",
        probability="medium", impact="medium", severity=0.444,
        mitigation="Negotiate a multi-year rate lock.", evidence_ids=["ev-1"],
    )
    assumption = Assumption(
        id="assumption-0", text="Traffic stays roughly flat for 12 months",
        origin="hypothetical", affects=["Build", "Buy"],
    )
    decision_matrix = DecisionMatrix(
        criteria=plan.criteria,
        scores=[
            AlternativeScore(
                alternative="Build", criterion="cost", score=6.0,
                rationale="Cheaper at this scale.", evidence_ids=["ev-1"],
            ),
            AlternativeScore(
                alternative="Buy", criterion="cost", score=4.0,
                rationale="Vendor markup.", evidence_ids=["ev-1"],
            ),
        ],
        weighted_totals={"Build": 6.0, "Buy": 4.0},
        recommended="Build",
    )
    report = FinalReport(
        executive_summary="s", research_question=request.question, decision_context="c",
        alternatives=["Build", "Buy"], criteria=plan.criteria, key_findings=["X costs $10/mo"],
        evidence=[evidence], contradictions=[],
        comparative_analysis=decision_matrix,
        risk_analysis=[risk], assumptions=[assumption], decision_rationale="cheaper",
        confidence=0.9, limitations=[], sources=[source], citations={"[S1]": "src-1"},
    )
    agent_run = AgentRunMeta(
        agent_name="research_planner", trace_id=f"trace-{research_id}", start_time=now,
        end_time=now, latency_ms=5, tokens=10, model="local", tool_calls=["llm.complete"],
        errors=[], confidence=None,
    )
    metadata = ExecutionMetadata(
        trace_id=f"trace-{research_id}", session_id=research_id, started_at=now,
        completed_at=now, status="completed", agent_runs=[agent_run], total_tokens=10,
        verification_cycles_used=1,
    )
    return ResearchState(
        request=request, plan=plan, retrieved_documents=[], sources=[source], claims=[claim],
        evidence=[evidence], verified_claims=[verified], contradictions=[],
        risks=[risk], assumptions=[assumption], decision_matrix=decision_matrix,
        final_report=report, execution_metadata=metadata,
    )


async def test_create_then_get_round_trips_pending_session() -> None:
    repo = SessionRepository(_in_memory_settings())
    research_id = uuid4()
    request = _request(research_id)
    metadata = ExecutionMetadata(
        trace_id=f"trace-{research_id}", session_id=research_id,
        started_at=datetime.now(UTC), status="pending",
    )
    state = ResearchState(request=request, execution_metadata=metadata)

    await repo.create(ResearchSession(research_id=research_id, status="pending", state=state))
    fetched = await repo.get(research_id)

    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.state.request.question == request.question
    assert fetched.error is None


async def test_get_unknown_session_returns_none() -> None:
    repo = SessionRepository(_in_memory_settings())
    assert await repo.get(uuid4()) is None


async def test_update_persists_full_state_and_normalized_tables() -> None:
    repo = SessionRepository(_in_memory_settings())
    research_id = uuid4()
    state = _full_state(research_id)

    await repo.update(ResearchSession(research_id=research_id, status="completed", state=state))
    fetched = await repo.get(research_id)

    assert fetched is not None
    assert fetched.status == "completed"
    assert fetched.state.final_report is not None
    assert fetched.state.final_report.research_question == state.request.question
    assert fetched.state.plan is not None
    assert fetched.state.plan.alternatives == ["Build", "Buy"]
    assert [s.id for s in fetched.state.sources] == ["src-1"]

    async with repo._sessionmaker() as db:  # noqa: SLF001 - inspecting persistence internals in a test
        assert (await db.get(ResearchSessionORM, research_id)) is not None
        assert (await db.get(SourceORM, "src-1")) is not None
        assert (await db.get(ClaimORM, "claim-1")) is not None
        plan_row = (
            await db.execute(select(ResearchPlanORM).where(ResearchPlanORM.session_id == research_id))
        ).scalar_one()
        alternatives = (
            await db.execute(select(AlternativeORM).where(AlternativeORM.plan_id == plan_row.id))
        ).scalars().all()
        criteria = (
            await db.execute(select(CriterionORM).where(CriterionORM.plan_id == plan_row.id))
        ).scalars().all()
        assert {a.name for a in alternatives} == {"Build", "Buy"}
        assert len(criteria) == 1
        report_row = (
            await db.execute(select(ReportORM).where(ReportORM.session_id == research_id))
        ).scalar_one()
        assert report_row.confidence == 0.9
        agent_runs = (
            await db.execute(select(AgentRunORM).where(AgentRunORM.session_id == research_id))
        ).scalars().all()
        assert len(agent_runs) == 1
        assert agent_runs[0].agent_name == "research_planner"


async def test_update_persists_phase4_risks_assumptions_decision_scores() -> None:
    repo = SessionRepository(_in_memory_settings())
    research_id = uuid4()
    state = _full_state(research_id)

    await repo.update(ResearchSession(research_id=research_id, status="completed", state=state))
    fetched = await repo.get(research_id)

    assert fetched is not None
    assert [r.id for r in fetched.state.risks] == ["risk-0-financial"]
    assert [a.id for a in fetched.state.assumptions] == ["assumption-0"]
    assert fetched.state.decision_matrix is not None
    assert fetched.state.decision_matrix.recommended == "Build"

    async with repo._sessionmaker() as db:  # noqa: SLF001 - inspecting persistence internals in a test
        risk_row = await db.get(RiskORM, "risk-0-financial")
        assert risk_row is not None
        assert risk_row.severity == 0.444
        assert risk_row.evidence_ids == ["ev-1"]

        assumption_row = await db.get(AssumptionORM, "assumption-0")
        assert assumption_row is not None
        assert assumption_row.origin == "hypothetical"

        score_rows = (
            await db.execute(select(DecisionScoreORM).where(DecisionScoreORM.session_id == research_id))
        ).scalars().all()
        assert len(score_rows) == 2
        by_alt = {row.alternative_name: row for row in score_rows}
        assert by_alt["Build"].score == 6.0
        # Resolved via (plan_id, name) lookup against the freshly-recreated
        # `alternatives` rows, not echoed back from the agent verbatim.
        assert by_alt["Build"].alternative_id is not None
        assert by_alt["Buy"].alternative_id is not None


async def test_update_is_idempotent_and_does_not_duplicate_agent_runs() -> None:
    repo = SessionRepository(_in_memory_settings())
    research_id = uuid4()
    state = _full_state(research_id)
    session = ResearchSession(research_id=research_id, status="completed", state=state)

    await repo.update(session)
    await repo.update(session)  # simulate the pending->running->completed rewrite pattern

    async with repo._sessionmaker() as db:  # noqa: SLF001
        agent_runs = (
            await db.execute(select(AgentRunORM).where(AgentRunORM.session_id == research_id))
        ).scalars().all()
        assert len(agent_runs) == 1


async def test_two_repository_instances_are_isolated_in_memory_databases() -> None:
    repo_a = SessionRepository(_in_memory_settings())
    repo_b = SessionRepository(_in_memory_settings())
    research_id = uuid4()
    state = _full_state(research_id)

    await repo_a.update(ResearchSession(research_id=research_id, status="completed", state=state))

    assert await repo_a.get(research_id) is not None
    assert await repo_b.get(research_id) is None


async def test_record_audit_writes_a_row() -> None:
    repo = SessionRepository(_in_memory_settings())
    research_id = uuid4()
    state = _full_state(research_id)
    await repo.update(ResearchSession(research_id=research_id, status="completed", state=state))

    await repo.record_audit(
        session_id=research_id, actor="fact_checker", action="agent_run", payload={"ok": True}
    )

    async with repo._sessionmaker() as db:  # noqa: SLF001
        rows = (
            await db.execute(select(AuditLogORM).where(AuditLogORM.session_id == research_id))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor == "fact_checker"
        assert rows[0].payload == {"ok": True}
