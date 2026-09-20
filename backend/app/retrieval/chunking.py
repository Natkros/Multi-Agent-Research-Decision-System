"""Recursive character chunker (Phase 5 RAG, brief §8).

Not a naive fixed-length split: text is recursively split on a hierarchy of
separators (paragraph -> line -> sentence -> word -> character) so a chunk
boundary prefers a natural break, then the resulting pieces are greedily
packed up to `chunk_size` characters with `chunk_overlap` characters of
trailing context repeated at the start of the next chunk, so a fact split
across a chunk boundary is still retrievable from either side.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

DEFAULT_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")


@dataclass
class ChunkConfig:
    chunk_size: int = 800
    chunk_overlap: int = 150
    separators: tuple[str, ...] = field(default_factory=lambda: DEFAULT_SEPARATORS)

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be in [0, chunk_size)")


class TextChunk(BaseModel):
    """One chunk of a source document, positioned in the original text so a
    citation can point back at an exact span."""

    text: str
    index: int
    start_char: int
    end_char: int


def _split_recursive(text: str, separators: tuple[str, ...], chunk_size: int) -> list[str]:
    """Split `text` into atomic pieces no larger than `chunk_size` where
    possible, preferring the earliest (coarsest) separator that achieves it."""
    if len(text) <= chunk_size or not separators:
        return [text] if text else []

    sep, *rest = separators
    if sep == "":
        # Last resort: hard character split, no separator left to try.
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    pieces = text.split(sep)
    result: list[str] = []
    for i, piece in enumerate(pieces):
        # Re-attach the separator (except after the final piece) so no text
        # is silently dropped and reconstruction stays lossless-ish.
        restored = piece + sep if i < len(pieces) - 1 else piece
        if not restored:
            continue
        if len(restored) > chunk_size:
            result.extend(_split_recursive(restored, tuple(rest), chunk_size))
        else:
            result.append(restored)
    return result


def chunk_text(text: str, config: ChunkConfig | None = None) -> list[TextChunk]:
    """Chunk `text` into overlapping `TextChunk`s per `config`."""
    config = config or ChunkConfig()
    cleaned = text.strip()
    if not cleaned:
        return []

    atoms = _split_recursive(cleaned, config.separators, config.chunk_size)
    if not atoms:
        return []

    # Raw packed strings first; wrapped into `TextChunk`s (with span info) in
    # the second pass below — annotated `list[str]`, not `list[TextChunk]`,
    # since nothing here is a `TextChunk` yet (a stale annotation, not a
    # runtime bug: `.append(current)` always held a `str`).
    chunks: list[str] = []
    current = ""
    for atom in atoms:
        if current and len(current) + len(atom) > config.chunk_size:
            chunks.append(current)
            # Carry the trailing `chunk_overlap` characters into the next
            # chunk so context isn't lost at the boundary.
            overlap_tail = current[-config.chunk_overlap :] if config.chunk_overlap else ""
            current = overlap_tail + atom
        else:
            current += atom
    if current:
        chunks.append(current)

    result: list[TextChunk] = []
    search_from = 0
    for i, chunk_str in enumerate(chunks):
        # Locate this chunk's true span in the original text for citation
        # traceability; overlap means a naive running offset would drift, so
        # anchor each chunk's *unique* (non-overlapping) suffix instead.
        probe = chunk_str[-min(len(chunk_str), 64) :]
        found = cleaned.find(probe, max(0, search_from - config.chunk_overlap))
        if found == -1:
            found = search_from
        start = max(0, found + len(probe) - len(chunk_str))
        end = start + len(chunk_str)
        result.append(TextChunk(text=chunk_str, index=i, start_char=start, end_char=end))
        search_from = end

    return result
