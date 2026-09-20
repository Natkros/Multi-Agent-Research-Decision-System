"""Sensitivity analysis (docs/architecture.md §4, brief §11).

Mandatory, deterministic, code-only — never another LLM call. Given the
`AlternativeScore`s the Decision Analyst already produced, perturb each
criterion's normalized weight by ±`Settings.sensitivity_weight_perturbation`
(default 20%), renormalize the remaining weights proportionally so the set
still sums to 1, recompute `weighted_totals` with the *same* scores, and
record whether the recommended alternative changes.

Kept as its own module (not inlined in `decision_analyst.py`) so it can be
unit-tested against a fixed, hand-computed fixture without going through an
LLM call at all.
"""

from __future__ import annotations

from app.schemas.state import AlternativeScore, DecisionCriteria, SensitivityResult

DEFAULT_PERTURBATION = 0.20


def perturb_weights(
    normalized_weights: dict[str, float], criterion: str, delta: float
) -> dict[str, float]:
    """Scale `criterion`'s weight by `(1 + delta)`, clip to [0, 1], then
    renormalize every other weight proportionally so the full set still
    sums to 1.0. Pure function, no side effects."""
    if criterion not in normalized_weights:
        return dict(normalized_weights)

    target = normalized_weights[criterion]
    new_target = max(0.0, min(1.0, target * (1.0 + delta)))
    others = {k: v for k, v in normalized_weights.items() if k != criterion}
    others_total = sum(others.values())
    remaining_budget = 1.0 - new_target

    perturbed = {criterion: new_target}
    if others_total > 0:
        for name, weight in others.items():
            perturbed[name] = weight / others_total * remaining_budget
    else:
        for name in others:
            perturbed[name] = 0.0
    return perturbed


def run_sensitivity(
    *,
    criteria: list[DecisionCriteria],
    scores: list[AlternativeScore],
    alternatives: list[str],
    baseline_recommended: str,
    perturbation: float = DEFAULT_PERTURBATION,
) -> list[SensitivityResult]:
    """Test both a +`perturbation` and -`perturbation` swing on every
    criterion's weight. Returns one `SensitivityResult` per (criterion,
    direction) pair — flags `recommendation_changed` whenever the perturbed
    argmax differs from `baseline_recommended`."""
    # Local import to avoid a module import cycle: `decision_analyst.py`
    # imports this module for the sensitivity pass, and this module reuses
    # its pure weighting helpers rather than duplicating them.
    from app.agents.decision_analyst import (
        compute_weighted_totals,
        normalize_weights,
        pick_recommended,
    )

    normalized = normalize_weights(criteria)
    results: list[SensitivityResult] = []
    for criterion in criteria:
        for delta in (perturbation, -perturbation):
            perturbed_weights = perturb_weights(normalized, criterion.name, delta)
            perturbed_totals = compute_weighted_totals(scores, perturbed_weights, alternatives)
            new_recommended = pick_recommended(perturbed_totals, alternatives)
            results.append(
                SensitivityResult(
                    criterion=criterion.name,
                    weight_delta=delta,
                    recommendation_changed=new_recommended != baseline_recommended,
                    new_recommended=new_recommended,
                )
            )
    return results


def is_sensitive(sensitivity: list[SensitivityResult]) -> bool:
    """True if ANY perturbation flips the recommendation — the trigger for
    the Final Synthesizer to surface "Decision is sensitive to weighting"
    language (brief §11)."""
    return any(r.recommendation_changed for r in sensitivity)
