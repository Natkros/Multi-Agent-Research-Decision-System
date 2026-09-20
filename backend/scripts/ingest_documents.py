#!/usr/bin/env python
"""CLI: ingest a directory of text/markdown files into the RAG vector store
(Phase 5, docs/project-structure.md), for seeding a demo internal knowledge
base the Researcher agent's `vector_search` tool can then query.

Usage (from `backend/`, with the venv active):

    python scripts/ingest_documents.py ./docs/kb --source demo-kb

Reads `.txt`/`.md` files from the given directory (non-recursive by default,
`--recursive` to walk subdirectories), assigns each a stable `document_id`
from its relative path, and ingests it through the same
`app.retrieval.ingestion.IngestionPipeline` the API's request path uses — so
what this script writes is queryable identically to anything ingested at
runtime. Respects `Settings` (`EMBEDDING_PROVIDER`, `QDRANT_URL`, chunk
size/overlap, etc.) exactly like the app does; with the default `.env` this
runs fully offline against the in-memory vector store (useful for a smoke
test of the pipeline, though nothing survives past process exit — point
`QDRANT_URL` at a running Qdrant instance for a persistent demo KB).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.settings import get_settings  # noqa: E402
from app.retrieval.chunking import ChunkConfig  # noqa: E402
from app.retrieval.embeddings import get_embedding_provider  # noqa: E402
from app.retrieval.hybrid_retrieval import KeywordIndex  # noqa: E402
from app.retrieval.ingestion import DocumentMetadata, IngestionPipeline  # noqa: E402
from app.retrieval.vector_store import get_vector_store  # noqa: E402

_DEFAULT_EXTENSIONS = (".txt", ".md")


def _iter_files(directory: Path, *, recursive: bool, extensions: tuple[str, ...]) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in directory.glob(pattern) if p.is_file() and p.suffix.lower() in extensions
    )


def _document_id(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


async def _run(args: argparse.Namespace) -> int:
    root = Path(args.directory).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 1

    settings = get_settings()
    chunk_config = ChunkConfig(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    pipeline = IngestionPipeline(
        embeddings=get_embedding_provider(settings),
        vector_store=get_vector_store(settings),
        keyword_index=KeywordIndex(),
        chunk_config=chunk_config,
    )

    files = _iter_files(root, recursive=args.recursive, extensions=tuple(args.extensions))
    if not files:
        print(f"no matching files under {root} (extensions: {args.extensions})")
        return 0

    total_chunks = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        metadata = DocumentMetadata(
            document_id=_document_id(path, root),
            source=args.source,
            title=path.stem.replace("_", " ").replace("-", " ").title(),
            document_type=args.document_type,
        )
        chunk_ids = await pipeline.ingest_document(text, metadata)
        total_chunks += len(chunk_ids)
        print(f"ingested {metadata.document_id}: {len(chunk_ids)} chunks")

    print(f"done: {len(files)} documents, {total_chunks} chunks")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Directory of .txt/.md files to ingest")
    parser.add_argument(
        "--source", default="local-kb", help="Value stored in each chunk's metadata.source"
    )
    parser.add_argument(
        "--document-type",
        default="internal_kb",
        choices=[
            "official_docs", "paper", "government", "standard", "vendor_docs",
            "blog", "forum", "news", "internal_kb",
        ],
        help="Value stored in each chunk's metadata.document_type",
    )
    parser.add_argument(
        "--recursive", action="store_true", help="Walk subdirectories too (default: top-level only)"
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=list(_DEFAULT_EXTENSIONS),
        help="File extensions to ingest (default: .txt .md)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
