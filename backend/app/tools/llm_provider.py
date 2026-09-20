"""Provider-agnostic LLM abstraction (docs/architecture.md §5, §6).

`LLMProvider` is the single seam agent/service code talks to. Swapping
OpenAI <-> Anthropic <-> a deterministic local fake never touches calling
code. Client construction is always lazy: importing this module, or
constructing a provider, must never require an API key — the key is only
read when `complete()` actually runs.
"""

from __future__ import annotations

import json
import types
import typing
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, ValidationError

from app.tools.resilience import ResilienceConfig, with_retry

if typing.TYPE_CHECKING:
    from app.config.settings import Settings

ModelTier = Literal["small", "mid", "strong"]

# docs/architecture.md §7: "a validation failure triggers a bounded retry
# (max 2) with the validation error fed back to the model, then a typed
# failure result — never a silent pass-through of raw text." Applies only to
# the real providers below; `LocalProvider` always emits schema-valid JSON by
# construction, so it never needs this path.
MAX_JSON_VALIDATION_RETRIES = 2


class LLMResponse(BaseModel):
    """Normalized result of a single LLM call."""

    text: str
    parsed: BaseModel | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str
    provider: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMProvider(ABC):
    """Abstract base for chat-completion providers with optional structured output."""

    name: str = "abstract"

    @abstractmethod
    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Run one completion. If `response_schema` is given, `parsed` is a
        validated instance of it; providers must ensure the raw text is valid
        JSON matching the schema (native structured-output mode where the
        provider supports it, prompt-enforced JSON otherwise)."""
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None, resilience: ResilienceConfig | None = None) -> None:
        self._api_key = api_key
        self._client: Any | None = None
        self._resilience = resilience or ResilienceConfig()
        # One breaker per provider *instance*, not shared globally — a
        # circuit opened for a request-scoped `OpenAIProvider` doesn't leak
        # into unrelated callers (brief §26).
        self._breaker = self._resilience.new_breaker()

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not set; cannot use the openai provider."
                )
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        working_messages = list(messages)

        for json_attempt in range(MAX_JSON_VALIDATION_RETRIES + 1):
            full_messages = [{"role": "system", "content": system}, *working_messages]
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": full_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if response_schema is not None:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_schema.__name__,
                        "schema": response_schema.model_json_schema(),
                        "strict": False,
                    },
                }

            async def _call() -> Any:
                return await client.chat.completions.create(**kwargs)

            # Transport-level retry (timeout, rate limit, transient 5xx):
            # bounded, backed off, circuit-breaker-guarded.
            completion = await with_retry(
                _call,
                max_attempts=self._resilience.max_attempts,
                base_delay=self._resilience.base_delay,
                max_delay=self._resilience.max_delay,
                breaker=self._breaker,
            )
            choice = completion.choices[0]
            text = choice.message.content or ""
            usage = completion.usage

            if response_schema is None:
                return LLMResponse(
                    text=text,
                    parsed=None,
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    model=model,
                    provider=self.name,
                )

            try:
                parsed = response_schema.model_validate_json(text)
            except ValidationError as exc:
                if json_attempt >= MAX_JSON_VALIDATION_RETRIES:
                    raise
                working_messages = [
                    *working_messages,
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": (
                            f"That response was invalid JSON for the required schema: {exc}. "
                            "Return ONLY a corrected JSON object matching the schema, no prose."
                        ),
                    },
                ]
                continue

            return LLMResponse(
                text=text,
                parsed=parsed,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                model=model,
                provider=self.name,
            )

        raise RuntimeError("unreachable: loop always returns or raises")


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, resilience: ResilienceConfig | None = None) -> None:
        self._api_key = api_key
        self._client: Any | None = None
        self._resilience = resilience or ResilienceConfig()
        self._breaker = self._resilience.new_breaker()

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set; cannot use the anthropic provider."
                )
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        effective_system = system
        if response_schema is not None:
            effective_system = (
                f"{system}\n\nRespond with ONLY a single JSON object matching "
                f"this JSON Schema, no prose, no markdown fences:\n"
                f"{json.dumps(response_schema.model_json_schema())}"
            )

        working_messages = list(messages)
        for json_attempt in range(MAX_JSON_VALIDATION_RETRIES + 1):

            async def _call() -> Any:
                return await client.messages.create(
                    model=model,
                    system=effective_system,
                    messages=working_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

            response = await with_retry(
                _call,
                max_attempts=self._resilience.max_attempts,
                base_delay=self._resilience.base_delay,
                max_delay=self._resilience.max_delay,
                breaker=self._breaker,
            )
            text = "".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            )
            usage = response.usage

            if response_schema is None:
                return LLMResponse(
                    text=text,
                    parsed=None,
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    model=model,
                    provider=self.name,
                )

            try:
                parsed = response_schema.model_validate_json(_strip_json_fences(text))
            except ValidationError as exc:
                if json_attempt >= MAX_JSON_VALIDATION_RETRIES:
                    raise
                working_messages = [
                    *working_messages,
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": (
                            f"That response was invalid JSON for the required schema: {exc}. "
                            "Return ONLY a corrected JSON object matching the schema, no prose."
                        ),
                    },
                ]
                continue

            return LLMResponse(
                text=text,
                parsed=parsed,
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                model=model,
                provider=self.name,
            )

        raise RuntimeError("unreachable: loop always returns or raises")


def _strip_json_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    return stripped.strip()


class LocalProvider(LLMProvider):
    """Deterministic offline fake. No network calls, no API key.

    Returns a minimally valid instance of `response_schema` when given, built
    by introspecting the Pydantic model's fields. Used for tests and offline
    dev so the whole request->LLM->report path is exercisable without keys.
    """

    name = "local"

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        last_user_text = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )

        if response_schema is None:
            text = (
                f"[local-provider canned reply] system={system[:60]!r} "
                f"prompt={last_user_text[:120]!r}"
            )
            return LLMResponse(
                text=text, parsed=None, input_tokens=len(text) // 4,
                output_tokens=len(text) // 4, model=model, provider=self.name,
            )

        instance = response_schema.model_validate(_build_minimal(response_schema))
        text = instance.model_dump_json()
        return LLMResponse(
            text=text,
            parsed=instance,
            input_tokens=max(1, len(last_user_text) // 4),
            output_tokens=max(1, len(text) // 4),
            model=model,
            provider=self.name,
        )


_SEEN_MARKER = "__local_provider_seen__"


def _build_minimal(model_cls: type[BaseModel], _depth: int = 0) -> dict[str, Any]:
    """Recursively build a dict of minimally-valid values for a Pydantic model."""
    data: dict[str, Any] = {}
    for field_name, field in model_cls.model_fields.items():
        data[field_name] = _value_for_type(field.annotation, field_name, _depth)
    return data


def _value_for_type(annotation: Any, field_name: str, depth: int) -> Any:
    if annotation is None:
        return None

    origin = get_origin(annotation)

    # Optional[X] / X | None
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if not args:
            return None
        return _value_for_type(args[0], field_name, depth)

    if origin is Literal:
        return get_args(annotation)[0]

    if origin in (list, typing.List):  # noqa: UP006
        return []

    if origin in (dict, typing.Dict):  # noqa: UP006
        return {}

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if depth > 4:
            return {}
        return _build_minimal(annotation, depth + 1)

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation)).value

    if annotation is uuid.UUID:
        return uuid.uuid4()
    if annotation is datetime:
        return datetime.now(UTC)
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is str:
        return f"local-{field_name}"

    return None


def get_llm_provider(settings: Settings) -> LLMProvider:
    """Factory selecting the configured provider. Client construction stays lazy."""
    resilience = ResilienceConfig.from_settings(settings)
    if settings.llm_provider == "openai":
        return OpenAIProvider(api_key=settings.openai_api_key, resilience=resilience)
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(api_key=settings.anthropic_api_key, resilience=resilience)
    return LocalProvider()
