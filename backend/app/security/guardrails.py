"""Prompt-injection scanning for untrusted retrieved content (Phase 8, brief
§14/§12, docs/architecture.md §7: "Retrieved web/document content is always
treated as untrusted data").

Every agent's system prompt already tells the model to treat retrieved
snippets as data, never instructions -- but a prompt-only defense is not a
control (brief §14: enforced in code, not just described in a prompt). This
module is the code-level control: it detects imperative-language patterns
aimed at the model (role markers, "ignore previous instructions", etc.) and
strips them before the text is ever concatenated into an LLM prompt.

Applied at `app/agents/researcher.py`, the single place retrieved
web/document snippets first enter the system -- every downstream agent
(Evidence Analyst, Fact Checker, ...) consumes `RetrievedDocument.
relevant_passage` / `Claim.text`, which are derived from the *sanitized*
snippet, so sanitizing once at the point of entry covers every consumer
without re-scanning the same text at every hop.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

_REDACTION = "[REDACTED-POSSIBLE-INSTRUCTION]"

# Each pattern targets a specific injection technique seen in the wild
# against retrieval-augmented systems: instruction-override phrases, fake
# role/system markers, and chat-template control tokens. Case-insensitive
# except the control-token patterns, which are already unambiguous.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore (all |any )?(the )?(previous|prior|above|preceding) instructions?", re.I),
    re.compile(r"disregard (all |any )?(the )?(previous|prior|above|preceding)", re.I),
    re.compile(r"forget (all |everything )?(you were told|previous instructions?)", re.I),
    re.compile(r"\byou are now\b", re.I),
    re.compile(r"\bact as\b.{0,40}\b(system|admin|root|developer)\b", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"^\s*system\s*:", re.I | re.M),
    re.compile(r"\[\s*(system|assistant|developer)\s*\]", re.I),
    re.compile(r"<\|\s*(system|im_start|im_end|assistant)\s*\|?>?", re.I),
    re.compile(r"###\s*(system|instruction)s?\b", re.I),
    re.compile(r"\breveal (your|the) (system )?prompt\b", re.I),
    re.compile(r"\bdo not (follow|obey|comply with) (the )?(previous|above)\b", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"\boverride (your|the) (instructions|rules|guidelines)\b", re.I),
]


class ScanResult(BaseModel):
    flagged: bool
    matched_patterns: list[str]
    sanitized_text: str


def scan_text(text: str) -> ScanResult:
    """Detects and redacts injection-style imperative language. Never
    raises -- worst case for a false negative is "text passes through
    unredacted", never a crash that would take down a research run over
    untrusted third-party content."""
    if not text:
        return ScanResult(flagged=False, matched_patterns=[], sanitized_text=text)

    matched: list[str] = []
    sanitized = text
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(sanitized):
            matched.append(pattern.pattern)
            sanitized = pattern.sub(_REDACTION, sanitized)

    return ScanResult(flagged=bool(matched), matched_patterns=matched, sanitized_text=sanitized)


def sanitize_retrieved_text(text: str) -> str:
    """Convenience wrapper for call sites that only need the cleaned text."""
    return scan_text(text).sanitized_text
