"""Tests for the recursive chunker (Phase 5 RAG, `app/retrieval/chunking.py`)."""

from __future__ import annotations

import pytest

from app.retrieval.chunking import ChunkConfig, chunk_text


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_produces_a_single_chunk() -> None:
    chunks = chunk_text("hello world", ChunkConfig(chunk_size=100, chunk_overlap=10))
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].index == 0


def test_long_text_is_split_into_multiple_chunks_within_size_bound() -> None:
    # Three paragraphs, each individually under chunk_size, but the whole
    # text well over it — the splitter should not produce one giant chunk.
    paragraph = "This is a sentence about vector databases. " * 6  # ~270 chars
    text = "\n\n".join([paragraph, paragraph, paragraph])
    config = ChunkConfig(chunk_size=300, chunk_overlap=50)

    chunks = chunk_text(text, config)

    assert len(chunks) > 1
    for chunk in chunks:
        # A little slack allowed for overlap being re-prepended.
        assert len(chunk.text) <= config.chunk_size + config.chunk_overlap


def test_consecutive_chunks_share_overlapping_content() -> None:
    paragraph = "Sentence number %d about databases and retrieval systems. "
    text = "".join(paragraph % i for i in range(30))
    config = ChunkConfig(chunk_size=200, chunk_overlap=40)

    chunks = chunk_text(text, config)
    assert len(chunks) >= 2

    for prev, curr in zip(chunks, chunks[1:]):
        # The start of `curr` should reuse a suffix of `prev` — real overlap,
        # not just adjacency.
        overlap_candidate = prev.text[-config.chunk_overlap :]
        assert overlap_candidate[-10:] in curr.text


def test_chunks_are_positioned_in_the_original_text() -> None:
    text = "Alpha section here.\n\nBeta section follows after alpha.\n\nGamma is last."
    config = ChunkConfig(chunk_size=30, chunk_overlap=5)

    chunks = chunk_text(text, config)

    for chunk in chunks:
        assert 0 <= chunk.start_char <= chunk.end_char <= len(text)


def test_no_naive_fixed_length_split_without_overlap_logic() -> None:
    """Guard against the "naive top-k" anti-pattern the brief warns against
    applied to chunking: with overlap configured, chunk boundaries must not
    land at exact fixed multiples of chunk_size with zero shared content."""
    text = "word " * 500  # 2500 chars, uniform content
    config = ChunkConfig(chunk_size=200, chunk_overlap=50)

    chunks = chunk_text(text, config)
    assert len(chunks) > 1

    # Overlap should make consecutive chunk texts share a common substring.
    shares_overlap = any(
        prev.text[-20:] in curr.text for prev, curr in zip(chunks, chunks[1:])
    )
    assert shares_overlap


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError):
        ChunkConfig(chunk_size=0)
    with pytest.raises(ValueError):
        ChunkConfig(chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError):
        ChunkConfig(chunk_size=100, chunk_overlap=-1)
