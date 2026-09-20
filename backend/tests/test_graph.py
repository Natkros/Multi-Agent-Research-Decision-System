"""Tests for the Phase 2 LangGraph `StateGraph` (docs/phase0-plan.md Phase 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.config.settings import get_settings
from app.orchestration.graph import build_graph, run_research_graph
from app.schemas.state import (
    DecisionCriteria,
    FinalReport,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
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


class _MultiQuestionProvider(LocalProvider):
    """LocalProvider whose planner call returns a plan with several research
    questions, so the graph's fan-out actually fans out to more than one
    Researcher branch — exercises the `Send`-based parallel path."""

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
        if response_schema is ResearchPlan:
            plan = ResearchPlan(
                objective="Pick a vector database strategy",
                decision_type="build_vs_buy",
                alternatives=["Build in-house", "Managed Qdrant"],
                criteria=[
                    DecisionCriteria(
                        name="cost", description="cost", weight=0.5,
                        direction="minimize", scoring_method="weighted_score",
                    ),
                    DecisionCriteria(
                        name="ops burden", description="ops burden", weight=0.5,
                        direction="minimize", scoring_method="weighted_score",
                    ),
                ],
                research_questions=[
                    ResearchQuestion(id="rq-1", text="cost comparison", dimension="cost", priority="high"),
                    ResearchQuestion(id="rq-2", text="operational burden", dimension="ops", priority="medium"),
                    ResearchQuestion(id="rq-3", text="security posture", dimension="security", priority="low"),
                ],
                required_evidence=[],
                constraints=[],
                assumptions=[],
            )
            text = plan.model_dump_json()
            return LLMResponse(
                text=text, parsed=plan, input_tokens=10, output_tokens=10,
                model=model, provider=self.name,
            )
        return await super().complete(
            system=system, messages=messages, model=model, max_tokens=max_tokens,
            temperature=temperature, response_schema=response_schema,
        )


def test_build_graph_compiles_without_error() -> None:
    settings = get_settings()
    compiled = build_graph(llm=LocalProvider(), search=LocalSearchProvider(), settings=settings)
    node_names = set(compiled.get_graph().nodes.keys())
    assert {
        "planner", "researcher", "source_evaluator", "evidence_analyst", "fact_checker",
        "contradiction_detector", "debate", "assumption_analyst", "decision_analyst",
        "risk_analyst", "synthesizer", "verification_gate",
    } <= node_names


async def test_run_research_graph_end_to_end_populates_state() -> None:
    settings = get_settings()
    request = _request()

    state = await run_research_graph(
        request, llm=LocalProvider(), search=LocalSearchProvider(), settings=settings
    )

    assert state.plan is not None
    assert state.retrieved_documents
    assert state.claims
    assert state.evidence
    assert state.verified_claims
    assert isinstance(state.draft_report, FinalReport)
    assert isinstance(state.final_report, FinalReport)
    # `state.sources` carries the Source Evaluator's scored replacement,
    # not the Researcher's raw placeholder-credibility sources.
    assert state.sources
    assert all(0.0 <= s.credibility_score <= 1.0 for s in state.sources)
    assert state.verification_results  # the gate always runs at least once

    # Phase 4: the decision-intelligence stage always runs and its output is
    # what ends up on the report, not an LLM-guessed placeholder.
    assert state.decision_matrix is not None
    assert state.final_report.comparative_analysis == state.decision_matrix
    assert state.final_report.risk_analysis == state.risks
    assert state.final_report.assumptions == state.assumptions

    metadata = state.execution_metadata
    assert metadata.status == "completed"
    agent_names = [run.agent_name for run in metadata.agent_runs]
    assert agent_names[0] == "research_planner"
    assert agent_names[-1] == "final_synthesizer"
    assert "researcher" in agent_names
    assert "source_evaluator" in agent_names
    assert "evidence_analyst" in agent_names
    assert "fact_checker" in agent_names
    assert "contradiction_detector" in agent_names
    assert "debate" in agent_names
    assert "assumption_analyst" in agent_names
    assert "decision_analyst" in agent_names
    assert "risk_analyst" in agent_names
    assert metadata.total_tokens == sum(run.tokens for run in metadata.agent_runs)
    assert metadata.verification_cycles_used == len(state.verification_results)


class _SensitiveDecisionProvider(LocalProvider):
    """Forces a plan with near-tied criteria weights and a decision matrix
    with sharply opposed scores, so a +/-20% weight perturbation actually
    flips the recommendation — lets the end-to-end test assert the Final
    Synthesizer surfaces the "sensitive to weighting" language (brief §11)
    rather than just wiring the field through untested."""

    async def complete(self, *, system, messages, model, max_tokens, temperature=0.0, response_schema=None):
        from app.agents.decision_analyst import _ScoreJudgment, _ScoreJudgments

        if response_schema is ResearchPlan:
            plan = ResearchPlan(
                objective="Pick a vector database strategy",
                decision_type="build_vs_buy",
                alternatives=["Build in-house", "Managed Qdrant"],
                criteria=[
                    DecisionCriteria(
                        name="cost", description="cost", weight=0.55,
                        direction="minimize", scoring_method="weighted_score",
                    ),
                    DecisionCriteria(
                        name="operational burden", description="ops", weight=0.45,
                        direction="minimize", scoring_method="weighted_score",
                    ),
                ],
                research_questions=[
                    ResearchQuestion(id="rq-1", text="cost comparison", dimension="cost", priority="high"),
                ],
                required_evidence=[], constraints=[], assumptions=[],
            )
            text = plan.model_dump_json()
            return LLMResponse(text=text, parsed=plan, input_tokens=10, output_tokens=10, model=model, provider=self.name)
        if response_schema is _ScoreJudgments:
            judgments = _ScoreJudgments(
                scores=[
                    _ScoreJudgment(alternative="Build in-house", criterion="cost", score=10.0, rationale="r", evidence_ids=[]),
                    _ScoreJudgment(alternative="Build in-house", criterion="operational burden", score=0.0, rationale="r", evidence_ids=[]),
                    _ScoreJudgment(alternative="Managed Qdrant", criterion="cost", score=0.0, rationale="r", evidence_ids=[]),
                    _ScoreJudgment(alternative="Managed Qdrant", criterion="operational burden", score=10.0, rationale="r", evidence_ids=[]),
                ]
            )
            text = judgments.model_dump_json()
            return LLMResponse(text=text, parsed=judgments, input_tokens=5, output_tokens=5, model=model, provider=self.name)
        return await super().complete(
            system=system, messages=messages, model=model, max_tokens=max_tokens,
            temperature=temperature, response_schema=response_schema,
        )


async def test_run_research_graph_surfaces_sensitivity_in_final_report() -> None:
    settings = get_settings()
    request = _request()

    state = await run_research_graph(
        request, llm=_SensitiveDecisionProvider(), search=LocalSearchProvider(), settings=settings
    )

    assert state.decision_matrix is not None
    from app.decision.sensitivity import is_sensitive

    assert is_sensitive(state.decision_matrix.sensitivity)
    assert state.final_report is not None
    assert any("sensitive to weighting" in note for note in state.final_report.limitations)
    assert "sensitive to weighting" in state.final_report.decision_rationale


async def test_run_research_graph_fans_out_one_researcher_per_question() -> None:
    settings = get_settings()
    request = _request()

    state = await run_research_graph(
        request, llm=_MultiQuestionProvider(), search=LocalSearchProvider(), settings=settings
    )

    assert state.plan is not None
    assert len(state.plan.research_questions) == 3

    researcher_runs = [
        run for run in state.execution_metadata.agent_runs if run.agent_name == "researcher"
    ]
    assert len(researcher_runs) == 3

    question_ids = {q.id for q in state.plan.research_questions}
    for claim in state.claims:
        assert claim.research_question_id in question_ids
