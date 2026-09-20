from __future__ import annotations

from pydantic import BaseModel

from app.config.settings import Settings
from app.schemas.state import FinalReport, ResearchPlan
from app.tools.llm_provider import (
    AnthropicProvider,
    LocalProvider,
    OpenAIProvider,
    get_llm_provider,
)


def test_factory_returns_local_by_default() -> None:
    provider = get_llm_provider(Settings(llm_provider="local"))
    assert isinstance(provider, LocalProvider)


def test_factory_returns_openai() -> None:
    provider = get_llm_provider(Settings(llm_provider="openai"))
    assert isinstance(provider, OpenAIProvider)


def test_factory_returns_anthropic() -> None:
    provider = get_llm_provider(Settings(llm_provider="anthropic"))
    assert isinstance(provider, AnthropicProvider)


def test_constructing_providers_never_requires_api_key() -> None:
    # Must not raise even though no key is configured.
    OpenAIProvider(api_key=None)
    AnthropicProvider(api_key=None)


class _Simple(BaseModel):
    name: str
    count: int
    active: bool
    tags: list[str]


async def test_local_provider_produces_schema_valid_simple_output() -> None:
    provider = LocalProvider()
    response = await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        model="local-model",
        max_tokens=100,
        response_schema=_Simple,
    )
    assert isinstance(response.parsed, _Simple)
    assert response.model == "local-model"
    assert response.provider == "local"
    assert response.total_tokens > 0


async def test_local_provider_produces_valid_research_plan() -> None:
    provider = LocalProvider()
    response = await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "plan this"}],
        model="local-model",
        max_tokens=100,
        response_schema=ResearchPlan,
    )
    assert isinstance(response.parsed, ResearchPlan)


async def test_local_provider_produces_valid_final_report() -> None:
    provider = LocalProvider()
    response = await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "report"}],
        model="local-model",
        max_tokens=100,
        response_schema=FinalReport,
    )
    assert isinstance(response.parsed, FinalReport)


async def test_local_provider_without_schema_returns_text_only() -> None:
    provider = LocalProvider()
    response = await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hello"}],
        model="local-model",
        max_tokens=100,
    )
    assert response.parsed is None
    assert "hello" in response.text or "local-provider" in response.text


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _FakeCompletionsEndpoint:
    """Returns each response in `responses` in order, one per call; tracks
    call count so tests can assert the bounded-retry behavior actually
    happened (rather than just the end result)."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.call_count = 0

    async def create(self, **kwargs):  # noqa: ANN003 - mirrors the real SDK's **kwargs
        content = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return _FakeCompletion(content)


class _FakeChat:
    def __init__(self, completions: _FakeCompletionsEndpoint) -> None:
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, responses: list[str]) -> None:
        self.chat = _FakeChat(_FakeCompletionsEndpoint(responses))


async def test_openai_provider_retries_once_on_invalid_json_then_succeeds() -> None:
    provider = OpenAIProvider(api_key="fake-key-not-used")
    valid = _Simple(name="n", count=1, active=True, tags=[]).model_dump_json()
    fake_client = _FakeOpenAIClient(responses=["not valid json at all", valid])
    provider._client = fake_client  # bypass lazy client construction (no network)

    response = await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o-mini",
        max_tokens=100,
        response_schema=_Simple,
    )

    assert isinstance(response.parsed, _Simple)
    assert response.parsed.name == "n"
    # One failed JSON attempt + one corrected attempt == 2 calls, bounded by
    # MAX_JSON_VALIDATION_RETRIES, never unbounded.
    assert fake_client.chat.completions.call_count == 2


async def test_openai_provider_gives_up_after_bounded_json_validation_retries() -> None:
    from pydantic import ValidationError

    provider = OpenAIProvider(api_key="fake-key-not-used")
    fake_client = _FakeOpenAIClient(responses=["still not valid json"])
    provider._client = fake_client

    try:
        await provider.complete(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-4o-mini",
            max_tokens=100,
            response_schema=_Simple,
        )
        raise AssertionError("expected a ValidationError to propagate")
    except ValidationError:
        pass

    # 1 initial attempt + MAX_JSON_VALIDATION_RETRIES corrections, never more.
    from app.tools.llm_provider import MAX_JSON_VALIDATION_RETRIES

    assert fake_client.chat.completions.call_count == MAX_JSON_VALIDATION_RETRIES + 1
