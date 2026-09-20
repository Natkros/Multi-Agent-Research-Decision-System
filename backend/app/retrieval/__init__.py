"""Phase 5 RAG pipeline (docs/architecture.md §2 RAG box, brief §8): ingest ->
chunk -> embed -> Qdrant -> hybrid retrieval -> rerank. See `ingestion.py` for
the end-to-end entrypoint and `hybrid_retrieval.py` for the query-side
entrypoint used by `app/agents/researcher.py`'s internal-KB search tool.
"""
