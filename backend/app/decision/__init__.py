"""Phase 4 decision-intelligence support: pure, deterministic computations
(sensitivity analysis, risk severity lookup) that back the Decision Analyst
and Risk Analyst agents. No LLM calls live in this package by design — see
`app/agents/decision_analyst.py` and `app/agents/risk_analyst.py` for the
agent modules that call into it.
"""
