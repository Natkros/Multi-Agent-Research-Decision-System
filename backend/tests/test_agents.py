"""Isolated tests for each Phase 2 agent module (docs/phase0-plan.md Phase 2).

All run against `LocalProvider`/`LocalSearchProvider` — no real API keys,
fully offline and deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.agents import (
    contradiction_detector,
    evidence_analyst,
    fact_checker,
    planner,
    researcher,
    source_evaluator,
    synthesizer,
)
from app.config.settings import SourceScoringWeights
from app.schemas.state import (
    Claim,
    ClaimVerification,
    DecisionCriteria,
    EvidenceItem,
    FinalReport,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
    RetrievedDocument,
    Source,
)
from app.tools.llm_provider import LLMResponse, LocalProvider
from app.tools.search_provider import LocalSearchProvider


def _request() -> ResearchRequest:
    return ResearchRequest(
        id=uuid4(),
        question="Should we build or buy a vector database?",
        alternatives_hint=["Build in-house", "Managed Qdrant"],
        criteria_hint=["cost", "operational burden"],
        requested_by="test-user",
        created_at=datetime.now(UTC),
    )


async def test_planner_produces_grounded_plan() -> None:
    request = _request()
    output = await planner.run(
        planner.PlannerInput(request=request), llm=LocalProvider(), model="planner-model"
    )

    assert isinstance(output.plan, ResearchPlan)
    assert output.plan.alternatives == request.alternatives_hint
    assert [c.name for c in output.plan.criteria] == request.criteria_hint
    assert output.plan.research_questions

    assert output.agent_run.agent_name == "research_planner"
    assert output.agent_run.trace_id == f"trace-{request.id}"
    assert output.agent_run.tokens > 0
    assert "llm.complete" in output.agent_run.tool_calls


async def test_researcher_grounds_claims_in_retrieved_sources() -> None:
    request_id = uuid4()
    question = ResearchQuestion(id="rq-1", text="vector db cost", dimension="cost", priority="high")

    output = await researcher.run(
        researcher.ResearcherInput(request_id=request_id, trace_id="trace-x", question=question),
        search=LocalSearchProvider(),
        llm=LocalProvider(),
        model="researcher-model",
    )

    assert len(output.sources) == researcher.MAX_RESULTS_PER_QUESTION
    assert len(output.retrieved_documents) == len(output.sources)
    assert len(output.claims) == len(output.sources)

    source_ids = {s.id for s in output.sources}
    for claim in output.claims:
        assert claim.source_id in source_ids
        assert claim.research_question_id == question.id

    assert output.agent_run.agent_name == "researcher"
    assert "search.search" in output.agent_run.tool_calls


async def test_researcher_vector_search_grounds_claims_and_merges_with_web() -> None:
    """Phase 5: the Researcher's internal-KB `vector_search` path (brief
    §5.3/§13) runs alongside — not instead of — the existing external
    search, and every resulting `RetrievedDocument`/`Source`/`Claim` is
    grounded in an actually-retrieved KB chunk, same invariant as web
    results (no hallucinated source ids)."""
    from app.retrieval.embeddings import LocalEmbeddingProvider
    from app.retrieval.hybrid_retrieval import HybridRetriever, KeywordIndex
    from app.retrieval.ingestion import DocumentMetadata, IngestionPipeline
    from app.retrieval.vector_store import InMemoryVectorStore

    embeddings = LocalEmbeddingProvider(dimension=32)
    vector_store = InMemoryVectorStore()
    keyword_index = KeywordIndex()
    pipeline = IngestionPipeline(
        embeddings=embeddings, vector_store=vector_store, keyword_index=keyword_index
    )
    await pipeline.ingest_document(
        "Managed Qdrant costs scale with stored vector count and query "
        "volume; self-hosting shifts that cost to infrastructure and "
        "on-call operational burden instead.",
        DocumentMetadata(document_id="kb-1", source="internal-kb", title="Vector DB Cost Notes"),
    )
    kb = HybridRetriever(vector_store=vector_store, embeddings=embeddings, keyword_index=keyword_index)

    request_id = uuid4()
    question = ResearchQuestion(
        id="rq-1",
        text="Managed Qdrant costs scale with stored vector count and query volume",
        dimension="cost",
        priority="high",
    )

    output = await researcher.run(
        researcher.ResearcherInput(request_id=request_id, trace_id="trace-x", question=question),
        search=LocalSearchProvider(),
        llm=LocalProvider(),
        model="researcher-model",
        kb=kb,
    )

    expected_total = researcher.MAX_RESULTS_PER_QUESTION + researcher.MAX_KB_RESULTS_PER_QUESTION
    assert len(output.sources) <= expected_total
    assert len(output.retrieved_documents) == len(output.sources)
    assert len(output.claims) == len(output.sources)

    internal_docs = [d for d in output.retrieved_documents if d.source_type == "internal_kb"]
    assert internal_docs  # the KB hit actually made it through
    assert any("Managed Qdrant" in d.relevant_passage for d in internal_docs)

    source_ids = {s.id for s in output.sources}
    for claim in output.claims:
        assert claim.source_id in source_ids
        assert claim.research_question_id == question.id

    assert "kb.search" in output.agent_run.tool_calls


async def test_researcher_kb_search_failure_is_bounded_not_a_crash() -> None:
    """A broken KB shouldn't take down the Researcher — same bounded-failure
    contract the external search call already has."""

    class _BrokenKB:
        async def search(self, query: str, *, top_k: int = 10, **kwargs):
            raise RuntimeError("kb unavailable")

    request_id = uuid4()
    question = ResearchQuestion(id="rq-1", text="anything", dimension="cost", priority="high")

    output = await researcher.run(
        researcher.ResearcherInput(request_id=request_id, trace_id="trace-x", question=question),
        search=LocalSearchProvider(),
        llm=LocalProvider(),
        model="researcher-model",
        kb=_BrokenKB(),  # type: ignore[arg-type]
    )

    assert len(output.sources) == researcher.MAX_RESULTS_PER_QUESTION  # web results still present
    assert any("vector_search failed" in e for e in output.agent_run.errors)


async def test_evidence_analyst_grounds_every_claim() -> None:
    claims = [
        Claim(id="claim-1", text="X costs $10/mo", source_id="src-1", research_question_id="rq-1"),
        Claim(id="claim-2", text="Y is open source", source_id="src-2", research_question_id="rq-1"),
    ]
    documents = [
        RetrievedDocument(
            source_id="src-1", title="t1", url=None, source_type="blog",
            retrieved_at=datetime.now(UTC), relevant_passage="X costs $10/mo",
            claims=["X costs $10/mo"], relevance_score=0.5,
        ),
        RetrievedDocument(
            source_id="src-2", title="t2", url=None, source_type="blog",
            retrieved_at=datetime.now(UTC), relevant_passage="Y is open source",
            claims=["Y is open source"], relevance_score=0.5,
        ),
    ]

    output = await evidence_analyst.run(
        evidence_analyst.EvidenceAnalystInput(
            trace_id="trace-x", claims=claims, retrieved_documents=documents
        ),
        llm=LocalProvider(),
        model="evidence-model",
    )

    assert len(output.evidence) == len(claims)
    claim_ids = {c.id for c in claims}
    for item in output.evidence:
        assert item.claim_id in claim_ids
        assert item.source_id in {"src-1", "src-2"}
    assert output.agent_run.agent_name == "evidence_analyst"


async def test_fact_checker_produces_one_verdict_per_claim() -> None:
    claims = [
        Claim(id="claim-1", text="X costs $10/mo", source_id="src-1", research_question_id="rq-1"),
    ]
    evidence = [
        EvidenceItem(
            id="ev-claim-1", claim_id="claim-1", evidence_text="X costs $10/mo",
            source_id="src-1", evidence_type="documentation", strength="moderate",
            confidence=0.5, limitations=None,
        )
    ]

    output = await fact_checker.run(
        fact_checker.FactCheckerInput(trace_id="trace-x", claims=claims, evidence=evidence),
        search=LocalSearchProvider(),
        llm=LocalProvider(),
        model="fact-checker-model",
    )

    assert len(output.verified_claims) == 1
    verification = output.verified_claims[0]
    assert verification.claim_id == "claim-1"
    assert verification.status in {
        "VERIFIED", "PARTIALLY_VERIFIED", "CONTRADICTED", "UNSUPPORTED", "OUTDATED",
    }
    assert output.agent_run.agent_name == "fact_checker"
    assert "search.search" in output.agent_run.tool_calls


async def test_synthesizer_grounds_sources_and_evidence_in_report() -> None:
    request = _request()
    plan = ResearchPlan(
        objective=request.question,
        decision_type="other",
        alternatives=["Build in-house", "Managed Qdrant"],
        criteria=[
            DecisionCriteria(
                name="cost", description="cost", weight=1.0,
                direction="minimize", scoring_method="weighted_score",
            )
        ],
        research_questions=[
            ResearchQuestion(id="rq-1", text=request.question, dimension="cost", priority="high")
        ],
        required_evidence=[],
        constraints=[],
        assumptions=[],
    )
    sources = [
        Source(
            id="src-1", title="t1", url=None, publisher="local", author=None,
            published_at=None, retrieved_at=datetime.now(UTC),
            source_type="blog", credibility_score=0.5, content_hash="abc123",
        )
    ]
    evidence = [
        EvidenceItem(
            id="ev-1", claim_id="claim-1", evidence_text="X costs $10/mo",
            source_id="src-1", evidence_type="documentation", strength="moderate",
            confidence=0.5, limitations=None,
        )
    ]

    output = await synthesizer.run(
        synthesizer.SynthesizerInput(
            request=request, plan=plan, sources=sources, evidence=evidence
        ),
        llm=LocalProvider(),
        model="synthesizer-model",
    )

    assert isinstance(output.draft_report, FinalReport)
    assert output.draft_report.sources == sources
    assert output.draft_report.evidence == evidence
    assert output.draft_report.research_question == request.question
    assert output.draft_report.citations == {"[S1]": "src-1"}
    assert output.agent_run.agent_name == "final_synthesizer"
    assert output.agent_run.confidence == output.draft_report.confidence


# -- Source Evaluator (Phase 3, brief §5.5) ----------------------------------


def test_compute_credibility_score_matches_weighted_formula() -> None:
    weights = SourceScoringWeights(
        authority=0.25, relevance=0.25, recency=0.15, specificity=0.20, independence=0.15
    )
    score = source_evaluator.compute_credibility_score(
        authority=0.8, relevance=0.6, recency=0.4, specificity=0.9, independence=1.0,
        weights=weights,
    )
    expected = 0.8 * 0.25 + 0.6 * 0.25 + 0.4 * 0.15 + 0.9 * 0.20 + 1.0 * 0.15
    assert score == expected == 0.74

    # All weight on one factor: the score collapses to exactly that factor.
    authority_only = SourceScoringWeights(
        authority=1.0, relevance=0.0, recency=0.0, specificity=0.0, independence=0.0
    )
    assert source_evaluator.compute_credibility_score(
        authority=0.37, relevance=0.9, recency=0.9, specificity=0.9, independence=0.9,
        weights=authority_only,
    ) == 0.37


def test_compute_credibility_score_is_clipped_to_unit_interval() -> None:
    weights = SourceScoringWeights(
        authority=1.0, relevance=1.0, recency=1.0, specificity=1.0, independence=1.0
    )
    score = source_evaluator.compute_credibility_score(
        authority=1.0, relevance=1.0, recency=1.0, specificity=1.0, independence=1.0,
        weights=weights,
    )
    assert score == 1.0  # would be 5.0 unclipped


def test_recency_score_decays_with_age() -> None:
    now = datetime.now(UTC)
    fresh = source_evaluator.recency_score(now, now)
    one_year_old = source_evaluator.recency_score(now - timedelta(days=365), now)
    unknown = source_evaluator.recency_score(None, now)
    assert fresh == 1.0
    assert 0.45 < one_year_old < 0.55  # one half-life
    assert unknown == 0.4


def test_independence_score_penalizes_shared_publisher() -> None:
    now = datetime.now(UTC)

    def src(id_: str, publisher: str) -> Source:
        return Source(
            id=id_, title=id_, url=None, publisher=publisher, author=None,
            published_at=None, retrieved_at=now, source_type="blog",
            credibility_score=0.0, content_hash=id_,
        )

    sources = [src("a", "Acme"), src("b", "Acme"), src("c", "Other")]
    assert source_evaluator.independence_score(sources[0], sources) == 0.5
    assert source_evaluator.independence_score(sources[2], sources) == 1.0


async def test_source_evaluator_populates_credibility_score_per_source() -> None:
    now = datetime.now(UTC)
    sources = [
        Source(
            id="src-1", title="t1", url=None, publisher="Acme", author=None,
            published_at=now, retrieved_at=now, source_type="vendor_docs",
            credibility_score=0.5, content_hash="h1",
        ),
        Source(
            id="src-2", title="t2", url=None, publisher="Other", author=None,
            published_at=None, retrieved_at=now, source_type="blog",
            credibility_score=0.5, content_hash="h2",
        ),
    ]
    documents = [
        RetrievedDocument(
            source_id="src-1", title="t1", url=None, source_type="vendor_docs",
            retrieved_at=now, relevant_passage="p1", claims=[], relevance_score=0.9,
        ),
        RetrievedDocument(
            source_id="src-2", title="t2", url=None, source_type="blog",
            retrieved_at=now, relevant_passage="p2", claims=[], relevance_score=0.2,
        ),
    ]

    output = await source_evaluator.run(
        source_evaluator.SourceEvaluatorInput(
            trace_id="trace-x", sources=sources, retrieved_documents=documents
        ),
        llm=LocalProvider(),
        model="source-evaluator-model",
    )

    assert len(output.sources) == 2
    for scored in output.sources:
        assert 0.0 <= scored.credibility_score <= 1.0
    # The higher-relevance, dated, well-attributed source should score
    # strictly higher than the lower-relevance, undated one.
    by_id = {s.id: s for s in output.sources}
    assert by_id["src-1"].credibility_score > by_id["src-2"].credibility_score
    assert output.agent_run.agent_name == "source_evaluator"


async def test_source_evaluator_handles_no_sources() -> None:
    output = await source_evaluator.run(
        source_evaluator.SourceEvaluatorInput(trace_id="trace-x", sources=[], retrieved_documents=[]),
        llm=LocalProvider(),
        model="source-evaluator-model",
    )
    assert output.sources == []
    assert output.agent_run.tokens == 0


# -- Contradiction Detector (Phase 3, brief §5.7) ----------------------------


class _ContradictionFixtureProvider(LocalProvider):
    """Returns a crafted `ContradictionJudgments` response so the test can
    assert the detector distinguishes a genuine contradiction from a
    context/version-mismatch one, the same pattern `test_graph.py`'s
    `_MultiQuestionProvider` uses for the planner."""

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
        response_schema=None,
    ) -> LLMResponse:
        if response_schema is contradiction_detector.ContradictionJudgments:
            judgments = contradiction_detector.ContradictionJudgments(
                conflicts=[
                    contradiction_detector.ContradictionJudgment(
                        claim_a_id="claim-cost-1",
                        claim_b_id="claim-cost-2",
                        conflict_type="genuine",
                        explanation="Both claims are about the same version/workload and "
                        "directly disagree on price.",
                    ),
                    contradiction_detector.ContradictionJudgment(
                        claim_a_id="claim-version-1",
                        claim_b_id="claim-version-2",
                        conflict_type="version_mismatch",
                        explanation="One claim is about v1 which lacked the feature; the "
                        "other is about v2 which added it.",
                    ),
                    # References a claim id that was never passed in — must
                    # be dropped (grounding rule), not trusted verbatim.
                    contradiction_detector.ContradictionJudgment(
                        claim_a_id="claim-cost-1",
                        claim_b_id="claim-does-not-exist",
                        conflict_type="genuine",
                        explanation="hallucinated pair",
                    ),
                ]
            )
            text = judgments.model_dump_json()
            return LLMResponse(
                text=text, parsed=judgments, input_tokens=10, output_tokens=10,
                model=model, provider=self.name,
            )
        return await super().complete(
            system=system, messages=messages, model=model, max_tokens=max_tokens,
            temperature=temperature, response_schema=response_schema,
        )


async def test_contradiction_detector_distinguishes_genuine_from_context_mismatch() -> None:
    claims = [
        Claim(id="claim-cost-1", text="Service X costs $10/mo", source_id="src-1",
              research_question_id="rq-cost"),
        Claim(id="claim-cost-2", text="Service X costs $50/mo", source_id="src-2",
              research_question_id="rq-cost"),
        Claim(id="claim-version-1", text="Postgres does not support JSON columns",
              source_id="src-3", research_question_id="rq-features"),
        Claim(id="claim-version-2", text="Postgres 16 supports JSON columns",
              source_id="src-4", research_question_id="rq-features"),
    ]
    verified = [
        ClaimVerification(
            claim_id=c.id, status="VERIFIED", supporting_sources=[c.source_id],
            contradicting_sources=[], confidence=0.8, explanation="",
        )
        for c in claims
    ]

    output = await contradiction_detector.run(
        contradiction_detector.ContradictionDetectorInput(
            trace_id="trace-x", claims=claims, verified_claims=verified
        ),
        llm=_ContradictionFixtureProvider(),
        model="contradiction-detector-model",
    )

    assert len(output.contradictions) == 2  # the hallucinated pair was dropped

    by_type = {c.conflict_type: c for c in output.contradictions}
    assert by_type["genuine"].resolution_status == "unresolved"
    assert by_type["genuine"].claim_a_id == "claim-cost-1"
    assert by_type["genuine"].claim_b_id == "claim-cost-2"

    assert by_type["version_mismatch"].resolution_status == "resolved_context"
    assert by_type["version_mismatch"].claim_a_id == "claim-version-1"

    referenced_ids = {c.claim_a_id for c in output.contradictions} | {
        c.claim_b_id for c in output.contradictions
    }
    assert "claim-does-not-exist" not in referenced_ids
    assert output.agent_run.agent_name == "contradiction_detector"


async def test_contradiction_detector_no_op_below_two_claims() -> None:
    claims = [
        Claim(id="claim-1", text="only one claim", source_id="src-1", research_question_id="rq-1"),
    ]
    output = await contradiction_detector.run(
        contradiction_detector.ContradictionDetectorInput(
            trace_id="trace-x", claims=claims, verified_claims=[]
        ),
        llm=LocalProvider(),
        model="contradiction-detector-model",
    )
    assert output.contradictions == []
    assert output.agent_run.tokens == 0
