"""Risk severity lookup table (docs/architecture.md §4, brief §5.10).

`Risk.severity` is always derived deterministically from
`probability x impact`, never LLM-eyeballed. A plain multiplicative formula
on a 1-3 level scale, normalized to 0-1, expressed as an explicit lookup
table so the exact value for every one of the 9 combinations is fixed and
independently testable (rather than "trust the formula").
"""

from __future__ import annotations

from typing import Literal

Level = Literal["low", "medium", "high"]

_LEVEL_WEIGHT: dict[Level, int] = {"low": 1, "medium": 2, "high": 3}

# probability, impact -> severity, 0-1. product / 9, rounded to 3dp.
SEVERITY_TABLE: dict[tuple[Level, Level], float] = {
    (p, i): round((_LEVEL_WEIGHT[p] * _LEVEL_WEIGHT[i]) / 9.0, 3)
    for p in _LEVEL_WEIGHT
    for i in _LEVEL_WEIGHT
}


def compute_severity(probability: Level, impact: Level) -> float:
    """Deterministic lookup; raises KeyError on an invalid level rather than
    silently defaulting, since Pydantic already restricts `probability`/
    `impact` to the three valid literals before this is ever called."""
    return SEVERITY_TABLE[(probability, impact)]
