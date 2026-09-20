"""Phase 4 decision-intelligence tests (docs/phase0-plan.md Phase 4, brief
§5.6/§5.9/§5.10/§5.11/§11): Decision Analyst weighted scoring, sensitivity
analysis, Risk Analyst severity lookup + thin-evidence fallback,
Advocate/Critic debate notes, Assumption Analyst origin labeling.

All run against `LocalProvider`/crafted fixture providers — no real API
keys, fully offline and deterministic, matching `tests/test_agents.py`'s
pattern (`_ContradictionFixtureProvider` etc.).
"""

from __future__ import annotations

from app.agents import assumption_analyst, debate, decision_analyst, risk_analyst
from app.decision.sensitivity import perturb_weights, run_sensitivity
from app.decision.severity import compute_severity
from app.schemas.state import (
    AlternativeScore,
    DecisionCriteria,
    EvidenceItem,
    ResearchPlan,
    ResearchQuestion,
)
from app.tools.llm_provider import LLMResponse, LocalProvider


def _plan(*, alternatives=None, criteria=None, assumptions=None) -> ResearchPlan:
    return ResearchPlan(
        objective="Pick a vector database strategy",
        decision_type="build_vs_buy",
        alternatives=alternatives or ["Build in-house", "Managed Qdrant"],
        criteria=criteria
        or [
            DecisionCriteria(
                name="cost", description="cost", weight=0.5, direction="minimize",
                scoring_method="weighted_score",
            ),
            DecisionCriteria(
                name="ops burden", description="ops burden", weight=0.5, direction="minimize",
                scoring_method="weighted_score",
            ),
        ],
        research_questions=[
            ResearchQuestion(id="rq-1", text="cost", dimension="cost", priority="high")
        ],
        required_evidence=[], constraints=[], assumptions=assumptions or [],
    )


def _evidence(n: int = 1) -> list[EvidenceItem]:
    return [
        EvidenceItem(
            id=f"ev-{i}", claim_id=f"claim-{i}", evidence_text=f"fact {i}", source_id=f"src-{i}",
            evidence_type="documentation", strength="moderate", confidence=0.5, limitations=None,
        )
        for i in range(n)
    ]


# -- Decision Analyst: deterministic weighted scoring (brief §5.9/§11) ------


def test_normalize_weights_sums_to_one_regardless_of_input_scale() -> None:
    criteria = [
        DecisionCriteria(name="a", description="", weight=3.0, direction="maximize", scoring_method="weighted_score"),
        DecisionCriteria(name="b", description="", weight=1.0, direction="maximize", scoring_method="weighted_score"),
    ]
    normalized = decision_analyst.normalize_weights(criteria)
    assert abs(sum(normalized.values()) - 1.0) < 1e-9
    assert normalized["a"] == 0.75
    assert normalized["b"] == 0.25


def test_normalize_weights_falls_back_to_equal_split_when_degenerate() -> None:
    criteria = [
        DecisionCriteria(name="a", description="", weight=0.0, direction="maximize", scoring_method="weighted_score"),
        DecisionCriteria(name="b", description="", weight=0.0, direction="maximize", scoring_method="weighted_score"),
    ]
    normalized = decision_analyst.normalize_weights(criteria)
    assert normalized == {"a": 0.5, "b": 0.5}


def test_compute_weighted_totals_matches_hand_computed_expectation() -> None:
    scores = [
        AlternativeScore(alternative="A", criterion="cost", score=8.0, rationale="r", evidence_ids=[]),
        AlternativeScore(alternative="A", criterion="ops", score=4.0, rationale="r", evidence_ids=[]),
        AlternativeScore(alternative="B", criterion="cost", score=2.0, rationale="r", evidence_ids=[]),
        AlternativeScore(alternative="B", criterion="ops", score=9.0, rationale="r", evidence_ids=[]),
    ]
    weights = {"cost": 0.75, "ops": 0.25}
    totals = decision_analyst.compute_weighted_totals(scores, weights, ["A", "B"])
    # A: 8*0.75 + 4*0.25 = 7.0 ; B: 2*0.75 + 9*0.25 = 3.75
    assert totals == {"A": 7.0, "B": 3.75}
    assert decision_analyst.pick_recommended(totals, ["A", "B"]) == "A"


def test_pick_recommended_breaks_ties_by_plan_order() -> None:
    totals = {"A": 5.0, "B": 5.0}
    assert decision_analyst.pick_recommended(totals, ["A", "B"]) == "A"
    assert decision_analyst.pick_recommended(totals, ["B", "A"]) == "B"


class _ScoreFixtureProvider(LocalProvider):
    """Returns fixed AlternativeScore judgments so the Decision Analyst's
    weighted_totals can be checked against a hand-computed expectation
    end-to-end (LLM scoring + deterministic weighting)."""

    async def complete(self, *, system, messages, model, max_tokens, temperature=0.0, response_schema=None):
        if response_schema is decision_analyst._ScoreJudgments:
            judgments = decision_analyst._ScoreJudgments(
                scores=[
                    decision_analyst._ScoreJudgment(
                        alternative="Build in-house", criterion="cost", score=8.0,
                        rationale="Cheaper long-run.", evidence_ids=["ev-0"],
                    ),
                    decision_analyst._ScoreJudgment(
                        alternative="Build in-house", criterion="ops burden", score=3.0,
                        rationale="More ops work.", evidence_ids=["ev-0"],
                    ),
                    decision_analyst._ScoreJudgment(
                        alternative="Managed Qdrant", criterion="cost", score=4.0,
                        rationale="Vendor markup.", evidence_ids=["ev-0"],
                    ),
                    decision_analyst._ScoreJudgment(
                        alternative="Managed Qdrant", criterion="ops burden", score=9.0,
                        rationale="Fully managed.", evidence_ids=["ev-0"],
                    ),
                ]
            )
            text = judgments.model_dump_json()
            return LLMResponse(text=text, parsed=judgments, input_tokens=10, output_tokens=10, model=model, provider=self.name)
        return await super().complete(
            system=system, messages=messages, model=model, max_tokens=max_tokens,
            temperature=temperature, response_schema=response_schema,
        )


async def test_decision_analyst_produces_deterministic_weighted_totals() -> None:
    plan = _plan()
    output = await decision_analyst.run(
        decision_analyst.DecisionAnalystInput(trace_id="trace-x", plan=plan, evidence=_evidence(1)),
        llm=_ScoreFixtureProvider(),
        model="decision-model",
    )
    matrix = output.decision_matrix
    # weights normalize to 0.5/0.5 (already summed to 1): Build = 8*.5+3*.5=5.5, Qdrant = 4*.5+9*.5=6.5
    assert matrix.weighted_totals["Build in-house"] == 5.5
    assert matrix.weighted_totals["Managed Qdrant"] == 6.5
    assert matrix.recommended == "Managed Qdrant"
    assert len(matrix.scores) == 4
    for score in matrix.scores:
        assert score.rationale
        assert score.evidence_ids == ["ev-0"]  # grounded to the one real evidence id


async def test_decision_analyst_grounds_ungrounded_evidence_ids() -> None:
    plan = _plan()

    class _HallucinatedEvidenceProvider(LocalProvider):
        async def complete(self, *, system, messages, model, max_tokens, temperature=0.0, response_schema=None):
            if response_schema is decision_analyst._ScoreJudgments:
                judgments = decision_analyst._ScoreJudgments(
                    scores=[
                        decision_analyst._ScoreJudgment(
                            alternative=alt, criterion=c.name, score=5.0, rationale="r",
                            evidence_ids=["ev-does-not-exist"],
                        )
                        for alt in plan.alternatives
                        for c in plan.criteria
                    ]
                )
                text = judgments.model_dump_json()
                return LLMResponse(text=text, parsed=judgments, input_tokens=1, output_tokens=1, model=model, provider=self.name)
            return await super().complete(
                system=system, messages=messages, model=model, max_tokens=max_tokens,
                temperature=temperature, response_schema=response_schema,
            )

    output = await decision_analyst.run(
        decision_analyst.DecisionAnalystInput(trace_id="trace-x", plan=plan, evidence=_evidence(1)),
        llm=_HallucinatedEvidenceProvider(),
        model="decision-model",
    )
    for score in output.decision_matrix.scores:
        assert score.evidence_ids == []  # hallucinated id dropped, never trusted


# -- Sensitivity analysis (brief §11) ----------------------------------------


def test_perturb_weights_renormalizes_remaining_weights_to_sum_to_one() -> None:
    weights = {"a": 0.5, "b": 0.3, "c": 0.2}
    perturbed = perturb_weights(weights, "a", 0.20)
    assert abs(sum(perturbed.values()) - 1.0) < 1e-9
    assert perturbed["a"] == 0.6
    # b and c keep their 3:2 ratio, now over the remaining 0.4 budget
    assert abs(perturbed["b"] - 0.24) < 1e-9
    assert abs(perturbed["c"] - 0.16) < 1e-9


def test_sensitivity_detects_a_recommendation_flip() -> None:
    criteria = [
        DecisionCriteria(name="cost", description="", weight=0.9, direction="minimize", scoring_method="weighted_score"),
        DecisionCriteria(name="quality", description="", weight=0.1, direction="maximize", scoring_method="weighted_score"),
    ]
    # A wins narrowly on the baseline weights; a big enough swing toward
    # `quality` should flip the recommendation to B.
    scores = [
        AlternativeScore(alternative="A", criterion="cost", score=6.0, rationale="r", evidence_ids=[]),
        AlternativeScore(alternative="A", criterion="quality", score=1.0, rationale="r", evidence_ids=[]),
        AlternativeScore(alternative="B", criterion="cost", score=5.0, rationale="r", evidence_ids=[]),
        AlternativeScore(alternative="B", criterion="quality", score=10.0, rationale="r", evidence_ids=[]),
    ]
    results = run_sensitivity(
        criteria=criteria, scores=scores, alternatives=["A", "B"], baseline_recommended="A",
        perturbation=0.20,
    )
    assert len(results) == 4  # 2 criteria x (+delta, -delta)
    quality_up = next(r for r in results if r.criterion == "quality" and r.weight_delta > 0)
    assert quality_up.recommendation_changed is True
    assert quality_up.new_recommended == "B"


def test_sensitivity_reports_stable_case_when_no_perturbation_flips_it() -> None:
    criteria = [
        DecisionCriteria(name="cost", description="", weight=0.5, direction="minimize", scoring_method="weighted_score"),
        DecisionCriteria(name="quality", description="", weight=0.5, direction="maximize", scoring_method="weighted_score"),
    ]
    # A dominates on both criteria: no plausible reweighting flips it.
    scores = [
        AlternativeScore(alternative="A", criterion="cost", score=9.0, rationale="r", evidence_ids=[]),
        AlternativeScore(alternative="A", criterion="quality", score=9.0, rationale="r", evidence_ids=[]),
        AlternativeScore(alternative="B", criterion="cost", score=1.0, rationale="r", evidence_ids=[]),
        AlternativeScore(alternative="B", criterion="quality", score=1.0, rationale="r", evidence_ids=[]),
    ]
    results = run_sensitivity(
        criteria=criteria, scores=scores, alternatives=["A", "B"], baseline_recommended="A",
        perturbation=0.20,
    )
    assert all(r.recommendation_changed is False for r in results)

    from app.decision.sensitivity import is_sensitive
    assert is_sensitive(results) is False


# -- Risk Analyst: severity lookup + thin-evidence fallback (brief §5.10) ---


def test_severity_lookup_table_is_deterministic_and_covers_all_combinations() -> None:
    assert compute_severity("low", "low") == 0.111
    assert compute_severity("high", "high") == 1.0
    assert compute_severity("medium", "medium") == 0.444
    assert compute_severity("high", "low") == compute_severity("low", "high") == 0.333


async def test_risk_analyst_adds_unknown_risk_when_evidence_is_thin() -> None:
    output = await risk_analyst.run(
        risk_analyst.RiskAnalystInput(
            trace_id="trace-x", evidence=_evidence(1), decision_matrix=None,
            contradictions=[], thin_evidence_threshold=3,
        ),
        llm=LocalProvider(),
        model="risk-model",
    )
    assert any(r.category == "unknown" for r in output.risks)
    unknown = next(r for r in output.risks if r.category == "unknown")
    assert unknown.severity == compute_severity(unknown.probability, unknown.impact)


async def test_risk_analyst_severity_always_matches_lookup_table() -> None:
    class _RiskFixtureProvider(LocalProvider):
        async def complete(self, *, system, messages, model, max_tokens, temperature=0.0, response_schema=None):
            if response_schema is risk_analyst._RiskJudgments:
                judgments = risk_analyst._RiskJudgments(
                    risks=[
                        risk_analyst._RiskJudgment(
                            category="vendor", description="Vendor lock-in", probability="high",
                            impact="medium", mitigation="Keep an exit plan.", evidence_ids=["ev-0"],
                        )
                    ]
                )
                text = judgments.model_dump_json()
                return LLMResponse(text=text, parsed=judgments, input_tokens=1, output_tokens=1, model=model, provider=self.name)
            return await super().complete(
                system=system, messages=messages, model=model, max_tokens=max_tokens,
                temperature=temperature, response_schema=response_schema,
            )

    output = await risk_analyst.run(
        risk_analyst.RiskAnalystInput(
            trace_id="trace-x", evidence=_evidence(5), decision_matrix=None,
            contradictions=[], thin_evidence_threshold=3,
        ),
        llm=_RiskFixtureProvider(),
        model="risk-model",
    )
    vendor_risk = next(r for r in output.risks if r.category == "vendor")
    assert vendor_risk.severity == compute_severity("high", "medium") == 0.667
    # Evidence not thin (5 >= 3): no forced unknown-category fallback needed
    # (fixture provider proposed none either).
    assert not any(r.category == "unknown" for r in output.risks)


# -- Advocate/Critic debate pass (brief §5.6) --------------------------------


class _DebateFixtureProvider(LocalProvider):
    """One advocate claim, one grounded critic attack on it — the minimum
    shape needed to prove the pass produces non-empty, evidence-referencing
    debate notes end to end."""

    async def complete(self, *, system, messages, model, max_tokens, temperature=0.0, response_schema=None):
        if response_schema is debate._AdvocateClaims:
            claims = debate._AdvocateClaims(
                claims=[
                    debate._AdvocateClaim(
                        alternative="Build in-house", claim="Cheapest at our scale.",
                        rationale="Evidence shows lower steady-state cost.", evidence_ids=["ev-0"],
                    )
                ]
            )
            text = claims.model_dump_json()
            return LLMResponse(text=text, parsed=claims, input_tokens=5, output_tokens=5, model=model, provider=self.name)
        if response_schema is debate._CriticClaims:
            claims = debate._CriticClaims(
                claims=[
                    debate._CriticClaim(
                        target_note_id="debate-advocate-0", alternative="Build in-house",
                        claim="Ignores the ongoing ops burden shown in the same evidence.",
                        rationale="The evidence cited also documents added operational load, "
                        "which the advocate claim omits.",
                        evidence_ids=["ev-0"],
                    )
                ]
            )
            text = claims.model_dump_json()
            return LLMResponse(text=text, parsed=claims, input_tokens=5, output_tokens=5, model=model, provider=self.name)
        return await super().complete(
            system=system, messages=messages, model=model, max_tokens=max_tokens,
            temperature=temperature, response_schema=response_schema,
        )


async def test_debate_produces_non_empty_notes_with_evidence_references() -> None:
    plan = _plan()
    output = await debate.run(
        debate.DebateInput(trace_id="trace-x", plan=plan, evidence=_evidence(1)),
        llm=_DebateFixtureProvider(),
        model="debate-model",
    )
    assert output.debate_notes
    roles = {n.role for n in output.debate_notes}
    assert roles == {"advocate", "critic"}
    for note in output.debate_notes:
        assert note.evidence_ids  # every note in this fixture cites evidence
    critic_notes = [n for n in output.debate_notes if n.role == "critic"]
    assert critic_notes[0].target_note_id == "debate-advocate-0"


async def test_debate_drops_unjustified_critic_notes() -> None:
    plan = _plan()

    class _BareDisagreementProvider(LocalProvider):
        async def complete(self, *, system, messages, model, max_tokens, temperature=0.0, response_schema=None):
            if response_schema is debate._AdvocateClaims:
                claims = debate._AdvocateClaims(
                    claims=[
                        debate._AdvocateClaim(
                            alternative="Build in-house", claim="Cheapest.", rationale="r",
                            evidence_ids=["ev-0"],
                        )
                    ]
                )
                text = claims.model_dump_json()
                return LLMResponse(text=text, parsed=claims, input_tokens=1, output_tokens=1, model=model, provider=self.name)
            if response_schema is debate._CriticClaims:
                claims = debate._CriticClaims(
                    claims=[
                        debate._CriticClaim(
                            target_note_id="debate-advocate-0", alternative="Build in-house",
                            claim="Disagree.", rationale="no", evidence_ids=[],
                        )
                    ]
                )
                text = claims.model_dump_json()
                return LLMResponse(text=text, parsed=claims, input_tokens=1, output_tokens=1, model=model, provider=self.name)
            return await super().complete(
                system=system, messages=messages, model=model, max_tokens=max_tokens,
                temperature=temperature, response_schema=response_schema,
            )

    output = await debate.run(
        debate.DebateInput(trace_id="trace-x", plan=plan, evidence=_evidence(1)),
        llm=_BareDisagreementProvider(),
        model="debate-model",
    )
    assert all(n.role != "critic" for n in output.debate_notes)  # unjustified attack dropped


async def test_debate_caps_alternatives_at_configured_max() -> None:
    plan = _plan(alternatives=["A", "B", "C", "D", "E", "F"])
    output = await debate.run(
        debate.DebateInput(trace_id="trace-x", plan=plan, evidence=_evidence(1), max_alternatives=3),
        llm=LocalProvider(),
        model="debate-model",
    )
    # LocalProvider proposes no claims, but the bound itself is what's under
    # test: confirmed indirectly via the agent_run succeeding with no error
    # despite 6 alternatives and a cap of 3 (no unbounded per-alternative call).
    assert output.agent_run.errors == []


# -- Assumption Analyst: origin labeling (brief §5.11) -----------------------


class _AssumptionFixtureProvider(LocalProvider):
    async def complete(self, *, system, messages, model, max_tokens, temperature=0.0, response_schema=None):
        if response_schema is assumption_analyst._AssumptionJudgments:
            judgments = assumption_analyst._AssumptionJudgments(
                assumptions=[
                    assumption_analyst._AssumptionJudgment(
                        text="Vendor SLA holds as published", origin="evidence_backed",
                        affects=["Managed Qdrant"],
                    ),
                    assumption_analyst._AssumptionJudgment(
                        text="Team will not grow headcount next year", origin="hypothetical",
                        affects=["Build in-house"],
                    ),
                ]
            )
            text = judgments.model_dump_json()
            return LLMResponse(text=text, parsed=judgments, input_tokens=5, output_tokens=5, model=model, provider=self.name)
        return await super().complete(
            system=system, messages=messages, model=model, max_tokens=max_tokens,
            temperature=temperature, response_schema=response_schema,
        )


async def test_assumption_analyst_labels_origins_for_crafted_fixture() -> None:
    plan = _plan(assumptions=["The company will not change cloud providers"])
    output = await assumption_analyst.run(
        assumption_analyst.AssumptionAnalystInput(
            trace_id="trace-x", plan=plan, evidence=_evidence(1), debate_notes=[]
        ),
        llm=_AssumptionFixtureProvider(),
        model="assumption-model",
    )
    by_text = {a.text: a for a in output.assumptions}
    # Planner-stated assumption: deterministically labeled, no LLM judgment.
    assert by_text["The company will not change cloud providers"].origin == "hypothetical"
    # LLM-proposed assumptions: origin as labeled by the model.
    assert by_text["Vendor SLA holds as published"].origin == "evidence_backed"
    assert by_text["Team will not grow headcount next year"].origin == "hypothetical"
    assert by_text["Vendor SLA holds as published"].affects == ["Managed Qdrant"]


async def test_assumption_analyst_filters_ungrounded_affects() -> None:
    plan = _plan()

    class _UngroundedAffectsProvider(LocalProvider):
        async def complete(self, *, system, messages, model, max_tokens, temperature=0.0, response_schema=None):
            if response_schema is assumption_analyst._AssumptionJudgments:
                judgments = assumption_analyst._AssumptionJudgments(
                    assumptions=[
                        assumption_analyst._AssumptionJudgment(
                            text="Some assumption", origin="inferred",
                            affects=["Not A Real Alternative", "cost"],
                        )
                    ]
                )
                text = judgments.model_dump_json()
                return LLMResponse(text=text, parsed=judgments, input_tokens=1, output_tokens=1, model=model, provider=self.name)
            return await super().complete(
                system=system, messages=messages, model=model, max_tokens=max_tokens,
                temperature=temperature, response_schema=response_schema,
            )

    output = await assumption_analyst.run(
        assumption_analyst.AssumptionAnalystInput(
            trace_id="trace-x", plan=plan, evidence=[], debate_notes=[]
        ),
        llm=_UngroundedAffectsProvider(),
        model="assumption-model",
    )
    assumption = next(a for a in output.assumptions if a.text == "Some assumption")
    assert assumption.affects == ["cost"]  # "Not A Real Alternative" dropped, "cost" kept
