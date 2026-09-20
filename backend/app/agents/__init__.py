"""Phase 2 graph-node agents (docs/architecture.md §3-4).

Each module exposes a narrow, typed `Input`/`Output` pair and a `run()`
coroutine. Agents never see the full `ResearchState` and never return one —
`app/orchestration/graph.py` is the only place that knows how an agent's
typed output folds back into the shared graph state.
"""
