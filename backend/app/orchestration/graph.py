"""Phase 4 LangGraph `StateGraph` over `ResearchState` (docs/architecture.md
§3, §4; docs/state-schema.md; brief §5.5/§5.6/§5.7/§5.9/§5.10/§5.11/§5.13).

Planner -> [fan-out] Researcher x N -> [join] Source Evaluator ->
Evidence Analyst -> Fact Checker -> Contradiction Detector -> Advocate/Critic
-> Assumption Analyst -> Decision Analyst -> Risk Analyst -> Final
Synthesizer -> Verification Gate (conditional loop, capped at
`Settings.verification_max_cycles`, hard-enforced in code below — not just
described in a prompt) -> END.

The Phase 4 decision-intelligence stage (debate -> assumptions -> decision
-> risk) runs sequentially rather than as a parallel fan-out: Decision
Analyst needs `evidence` (same as Assumption Analyst) but Risk Analyst needs
the Decision Analyst's `decision_matrix` as context, so a true fan-out would
still need a join before Risk Analyst — sequential is simpler and no less
correct for four single-shot, cheap-relative-to-Researcher nodes (brief:
"otherwise sequential is fine, don't force parallelism the graph doesn't
need").

`ResearchState` itself stays the plain pydantic model every agent module
type-checks against; LangGraph needs a state shape with per-field merge
semantics (`Annotated[list[X], operator.add]`) to fan values back in from
parallel branches, so `GraphState` is a thin `TypedDict` view used only by
the orchestration runtime. `run_research_graph` is the only place that
translates between the two.
"""

from __future__ import annotations

import operator
from datetime import UTC, datetime
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents import (
    assumption_analyst,
    contradiction_detector,
    debate,
    decision_analyst,
    evidence_analyst,
    fact_checker,
    planner,
    researcher,
    risk_analyst,
    source_evaluator,
    synthesizer,
)
from app.config.settings import Settings, get_settings
from app.retrieval.hybrid_retrieval import HybridRetriever
from app.schemas.state import (
    AgentRunMeta,
    Assumption,
    Claim,
    ClaimVerification,
    Conflict,
    DebateNote,
    DecisionMatrix,
    EvidenceItem,
    ExecutionMetadata,
    FinalReport,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
    ResearchState,
    RetrievedDocument,
    Risk,
    Source,
    VerificationResult,
)
from app.tools.llm_provider import LLMProvider
from app.tools.search_provider import SearchProvider
from app.verification import gate as verification_gate


class GraphState(TypedDict, total=False):
    """LangGraph-runtime state. List fields that a fan-out branch or a
    repeated (retried) node writes into use `operator.add` so they merge
    instead of overwriting each other; fields only ever replaced wholesale
    by a single node use LangGraph's default last-write-wins."""

    request: ResearchRequest
    trace_id: str
    plan: ResearchPlan | None
    question: ResearchQuestion | None  # set only on a Researcher fan-out branch
    retrieved_documents: Annotated[list[RetrievedDocument], operator.add]
    sources: Annotated[list[Source], operator.add]  # raw, as fanned in by Researcher
    evaluated_sources: list[Source] | None  # Source Evaluator's scored replacement
    claims: Annotated[list[Claim], operator.add]
    evidence: Annotated[list[EvidenceItem], operator.add]
    verified_claims: Annotated[list[ClaimVerification], operator.add]
    contradictions: list[Conflict]  # replaced wholesale each Contradiction Detector run
    debate_notes: list[DebateNote]  # replaced wholesale each Advocate/Critic run
    assumptions: list[Assumption]  # replaced wholesale each Assumption Analyst run
    decision_matrix: DecisionMatrix | None  # replaced wholesale each Decision Analyst run
    risks: list[Risk]  # replaced wholesale each Risk Analyst run
    draft_report: FinalReport | None
    final_report: FinalReport | None
    verification_cycle: int
    verification_results: Annotated[list[VerificationResult], operator.add]
    agent_runs: Annotated[list[AgentRunMeta], operator.add]


def build_graph(
    *,
    llm: LLMProvider,
    search: SearchProvider,
    settings: Settings,
    kb: HybridRetriever | None = None,
):
    """Wire the Phase 3 agents into a compiled `StateGraph`. Providers and
    model-tier config are closed over here (not routed through graph state)
    so `GraphState` only ever carries research data, not infrastructure.
    `kb` is optional (Phase 5): when omitted, the Researcher falls back to
    external web search only, matching every prior phase's graph shape."""

    graph: StateGraph = StateGraph(GraphState)

    async def planner_node(state: GraphState) -> dict:
        output = await planner.run(
            planner.PlannerInput(request=state["request"]),
            llm=llm,
            model=settings.model_name_for_tier("mid"),
        )
        return {"plan": output.plan, "agent_runs": [output.agent_run]}

    def fan_out_to_researchers(state: GraphState) -> list[Send]:
        plan = state["plan"]
        assert plan is not None, "planner must run before fan-out"
        questions = plan.research_questions or []
        return [
            Send(
                "researcher",
                {
                    "request": state["request"],
                    "trace_id": state["trace_id"],
                    "question": question,
                },
            )
            for question in questions
        ]

    async def researcher_node(state: GraphState) -> dict:
        question = state["question"]
        assert question is not None, "researcher branch must carry a question"
        output = await researcher.run(
            researcher.ResearcherInput(
                request_id=state["request"].id,
                trace_id=state["trace_id"],
                question=question,
            ),
            search=search,
            llm=llm,
            model=settings.model_name_for_tier("mid"),
            kb=kb,
        )
        return {
            "retrieved_documents": output.retrieved_documents,
            "sources": output.sources,
            "claims": output.claims,
            "agent_runs": [output.agent_run],
        }

    async def source_evaluator_node(state: GraphState) -> dict:
        output = await source_evaluator.run(
            source_evaluator.SourceEvaluatorInput(
                trace_id=state["trace_id"],
                sources=state.get("sources", []),
                retrieved_documents=state.get("retrieved_documents", []),
                weights=settings.source_scoring_weights(),
            ),
            llm=llm,
            model=settings.model_name_for_tier("small"),
        )
        # Wholesale replacement, not a fan-in append: written to a separate
        # key (`evaluated_sources`) so it never collides with `sources`'s
        # `operator.add` reducer, which exists only for the Researcher's
        # parallel fan-out.
        return {"evaluated_sources": output.sources, "agent_runs": [output.agent_run]}

    async def evidence_analyst_node(state: GraphState) -> dict:
        output = await evidence_analyst.run(
            evidence_analyst.EvidenceAnalystInput(
                trace_id=state["trace_id"],
                claims=state.get("claims", []),
                retrieved_documents=state.get("retrieved_documents", []),
            ),
            llm=llm,
            model=settings.model_name_for_tier("mid"),
        )
        return {"evidence": output.evidence, "agent_runs": [output.agent_run]}

    async def fact_checker_node(state: GraphState) -> dict:
        output = await fact_checker.run(
            fact_checker.FactCheckerInput(
                trace_id=state["trace_id"],
                claims=state.get("claims", []),
                evidence=state.get("evidence", []),
            ),
            search=search,
            llm=llm,
            model=settings.model_name_for_tier("mid"),
        )
        return {"verified_claims": output.verified_claims, "agent_runs": [output.agent_run]}

    async def contradiction_detector_node(state: GraphState) -> dict:
        output = await contradiction_detector.run(
            contradiction_detector.ContradictionDetectorInput(
                trace_id=state["trace_id"],
                claims=state.get("claims", []),
                verified_claims=state.get("verified_claims", []),
            ),
            llm=llm,
            model=settings.model_name_for_tier("mid"),
        )
        return {"contradictions": output.contradictions, "agent_runs": [output.agent_run]}

    async def debate_node(state: GraphState) -> dict:
        plan = state["plan"]
        assert plan is not None, "debate requires a plan"
        output = await debate.run(
            debate.DebateInput(
                trace_id=state["trace_id"],
                plan=plan,
                evidence=state.get("evidence", []),
                max_alternatives=settings.debate_max_alternatives,
                advocate_max_tokens=settings.debate_advocate_max_tokens,
                critic_max_tokens=settings.debate_critic_max_tokens,
            ),
            llm=llm,
            model=settings.model_name_for_tier("strong"),
        )
        return {"debate_notes": output.debate_notes, "agent_runs": [output.agent_run]}

    async def assumption_analyst_node(state: GraphState) -> dict:
        plan = state["plan"]
        assert plan is not None, "assumption analyst requires a plan"
        output = await assumption_analyst.run(
            assumption_analyst.AssumptionAnalystInput(
                trace_id=state["trace_id"],
                plan=plan,
                evidence=state.get("evidence", []),
                debate_notes=state.get("debate_notes", []),
            ),
            llm=llm,
            model=settings.model_name_for_tier("small"),
        )
        return {"assumptions": output.assumptions, "agent_runs": [output.agent_run]}

    async def decision_analyst_node(state: GraphState) -> dict:
        plan = state["plan"]
        assert plan is not None, "decision analyst requires a plan"
        output = await decision_analyst.run(
            decision_analyst.DecisionAnalystInput(
                trace_id=state["trace_id"],
                plan=plan,
                evidence=state.get("evidence", []),
            ),
            llm=llm,
            model=settings.model_name_for_tier("strong"),
        )
        return {"decision_matrix": output.decision_matrix, "agent_runs": [output.agent_run]}

    async def risk_analyst_node(state: GraphState) -> dict:
        output = await risk_analyst.run(
            risk_analyst.RiskAnalystInput(
                trace_id=state["trace_id"],
                evidence=state.get("evidence", []),
                decision_matrix=state.get("decision_matrix"),
                contradictions=state.get("contradictions", []),
                thin_evidence_threshold=settings.risk_thin_evidence_threshold,
            ),
            llm=llm,
            model=settings.model_name_for_tier("mid"),
        )
        return {"risks": output.risks, "agent_runs": [output.agent_run]}

    async def synthesizer_node(state: GraphState) -> dict:
        plan = state["plan"]
        assert plan is not None, "synthesizer requires a plan"
        sources = state.get("evaluated_sources") or state.get("sources", [])
        output = await synthesizer.run(
            synthesizer.SynthesizerInput(
                request=state["request"],
                plan=plan,
                sources=sources,
                evidence=state.get("evidence", []),
                verified_claims=state.get("verified_claims", []),
                contradictions=state.get("contradictions", []),
                risks=state.get("risks", []),
                assumptions=state.get("assumptions", []),
                decision_matrix=state.get("decision_matrix"),
            ),
            llm=llm,
            model=settings.model_name_for_tier("strong"),
        )
        return {"draft_report": output.draft_report, "agent_runs": [output.agent_run]}

    async def verification_gate_node(state: GraphState) -> dict:
        report = state.get("draft_report")
        assert report is not None, "verification gate requires a draft report"
        cycle = state.get("verification_cycle", 0) + 1
        result = verification_gate.run_gate(
            verification_gate.VerificationGateInput(
                report=report,
                contradictions=state.get("contradictions", []),
                verified_claims=state.get("verified_claims", []),
                cycle=cycle,
            )
        )
        updates: dict = {"verification_cycle": cycle, "verification_results": [result]}
        if result.passed:
            updates["final_report"] = report
        elif cycle >= settings.verification_max_cycles:
            # Hard cap enforced here in code, not just in a prompt: ship the
            # report anyway with every unresolved issue surfaced under
            # `limitations` rather than looping forever.
            updates["final_report"] = verification_gate.apply_cap_reached_limitations(
                report, result.failed_checks
            )
        return updates

    def route_after_gate(state: GraphState) -> str:
        results = state.get("verification_results", [])
        if not results:
            return END  # defensive: should never happen, gate always appends one
        last = results[-1]
        if last.passed or state.get("verification_cycle", 0) >= settings.verification_max_cycles:
            return END
        if last.routed_to == "fact_checker":
            return "fact_checker"
        return "synthesizer"

    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("source_evaluator", source_evaluator_node)
    graph.add_node("evidence_analyst", evidence_analyst_node)
    graph.add_node("fact_checker", fact_checker_node)
    graph.add_node("contradiction_detector", contradiction_detector_node)
    graph.add_node("debate", debate_node)
    graph.add_node("assumption_analyst", assumption_analyst_node)
    graph.add_node("decision_analyst", decision_analyst_node)
    graph.add_node("risk_analyst", risk_analyst_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("verification_gate", verification_gate_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", fan_out_to_researchers, ["researcher"])
    graph.add_edge("researcher", "source_evaluator")  # join: waits for every fanned branch
    graph.add_edge("source_evaluator", "evidence_analyst")
    graph.add_edge("evidence_analyst", "fact_checker")
    graph.add_edge("fact_checker", "contradiction_detector")
    graph.add_edge("contradiction_detector", "debate")
    graph.add_edge("debate", "assumption_analyst")
    graph.add_edge("assumption_analyst", "decision_analyst")
    graph.add_edge("decision_analyst", "risk_analyst")
    graph.add_edge("risk_analyst", "synthesizer")
    graph.add_edge("synthesizer", "verification_gate")
    graph.add_conditional_edges(
        "verification_gate", route_after_gate, ["fact_checker", "synthesizer", END]
    )

    return graph.compile()


async def run_research_graph(
    request: ResearchRequest,
    *,
    llm: LLMProvider,
    search: SearchProvider,
    settings: Settings | None = None,
    kb: HybridRetriever | None = None,
) -> ResearchState:
    """Async entrypoint: run the full Phase 3 graph for one request and
    return a validated `ResearchState`. Failures propagate to the caller
    (`ResearchService` is responsible for catching them and recording a
    failed session), matching the Phase 1 service's error-handling contract."""

    settings = settings or get_settings()
    trace_id = f"trace-{request.id}"
    started_at = datetime.now(UTC)

    compiled = build_graph(llm=llm, search=search, settings=settings, kb=kb)
    initial_state: GraphState = {
        "request": request,
        "trace_id": trace_id,
        "plan": None,
        "question": None,
        "retrieved_documents": [],
        "sources": [],
        "evaluated_sources": None,
        "claims": [],
        "evidence": [],
        "verified_claims": [],
        "contradictions": [],
        "debate_notes": [],
        "assumptions": [],
        "decision_matrix": None,
        "risks": [],
        "draft_report": None,
        "final_report": None,
        "verification_cycle": 0,
        "verification_results": [],
        "agent_runs": [],
    }
    # Default recursion limit assumes a small graph; fan-out adds one
    # super-step per research question and the verification loop adds up
    # to 3 retry cycles (4 nodes each), so give it real headroom.
    result = await compiled.ainvoke(initial_state, config={"recursion_limit": 100})

    agent_runs: list[AgentRunMeta] = result.get("agent_runs", [])
    verification_results: list[VerificationResult] = result.get("verification_results", [])
    metadata = ExecutionMetadata(
        trace_id=trace_id,
        session_id=request.id,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        status="completed",
        agent_runs=agent_runs,
        total_tokens=sum(run.tokens for run in agent_runs),
        verification_cycles_used=result.get("verification_cycle", 0),
    )

    return ResearchState(
        request=request,
        plan=result.get("plan"),
        retrieved_documents=result.get("retrieved_documents", []),
        sources=result.get("evaluated_sources") or result.get("sources", []),
        claims=result.get("claims", []),
        evidence=result.get("evidence", []),
        verified_claims=result.get("verified_claims", []),
        contradictions=result.get("contradictions", []),
        debate_notes=result.get("debate_notes", []),
        assumptions=result.get("assumptions", []),
        risks=result.get("risks", []),
        decision_matrix=result.get("decision_matrix"),
        draft_report=result.get("draft_report"),
        verification_results=verification_results,
        final_report=result.get("final_report"),
        execution_metadata=metadata,
    )
