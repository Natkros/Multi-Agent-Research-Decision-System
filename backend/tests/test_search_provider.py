from __future__ import annotations

from app.config.settings import Settings
from app.tools.search_provider import (
    LocalSearchProvider,
    TavilyProvider,
    get_search_provider,
)


def test_factory_returns_local_by_default() -> None:
    provider = get_search_provider(Settings(search_provider="local"))
    assert isinstance(provider, LocalSearchProvider)


def test_factory_returns_tavily() -> None:
    provider = get_search_provider(Settings(search_provider="tavily"))
    assert isinstance(provider, TavilyProvider)


def test_constructing_tavily_never_requires_api_key() -> None:
    TavilyProvider(api_key=None)


async def test_local_search_provider_returns_requested_count() -> None:
    provider = LocalSearchProvider()
    results = await provider.search("vector database", max_results=4)
    assert len(results) == 4
    assert all(r.source == "local" for r in results)
    assert all("vector database" in r.title for r in results)
