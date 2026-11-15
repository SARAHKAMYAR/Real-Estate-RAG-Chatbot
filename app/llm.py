"""Model providers.

The agent talks to a model through two small interfaces, so the provider can be swapped in
the settings without touching the agent, the tools or the eval:

    LLM.start(system, tools, messages) -> ChatSession
    ChatSession.step()                 -> ModelTurn (text and/or tool calls)
    ChatSession.submit(results, note)  -> feed tool results back for the next step

Each session keeps the conversation in its provider's own wire format.
"""

import copy
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

StopReason = Literal["end", "tool_use", "max_tokens", "refusal"]

ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMNotConfigured(Exception):
    """No usable model provider is configured."""


class LLMError(Exception):
    """A provider call failed. `status` is the HTTP status to report to the API caller."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolOutput:
    call: ToolCall
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ModelTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: StopReason = "end"
    input_tokens: int = 0
    output_tokens: int = 0


class ChatSession(Protocol):
    def step(self) -> ModelTurn: ...

    def submit(self, outputs: list[ToolOutput], note: str | None = None) -> None: ...


class LLM(Protocol):
    name: str

    def start(self, system: str, tools: list[dict], messages: list[dict]) -> ChatSession:
        """`tools` use the name / description / input_schema shape; `messages` are plain
        {"role", "content"} text turns ending with the user's question."""


# --- Anthropic (Claude) ----------------------------------------------------------------------


class AnthropicLLM:
    def __init__(self, client: Any, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self.name = settings.llm_model

    def start(self, system: str, tools: list[dict], messages: list[dict]) -> ChatSession:
        return _AnthropicSession(self._client, self._settings, system, tools, list(messages))


class _AnthropicSession:
    _STOP: dict[str, StopReason] = {
        "tool_use": "tool_use",
        "max_tokens": "max_tokens",
        "refusal": "refusal",
    }

    def __init__(self, client, settings, system, tools, messages) -> None:
        self._client = client
        self._settings = settings
        self._request = {
            "model": settings.llm_model,
            "max_tokens": settings.llm_max_tokens,
            "system": system,
            "tools": tools,
            "output_config": {"effort": settings.llm_effort},
        }
        self._messages = messages
        self._last_content: list = []

    def step(self) -> ModelTurn:
        import anthropic

        try:
            if self._settings.llm_refusal_fallback:
                # On a safety-classifier decline the API retries on a fallback model in-call.
                response = self._client.beta.messages.create(
                    betas=[ANTHROPIC_FALLBACK_BETA],
                    fallbacks="default",
                    messages=self._messages,
                    **self._request,
                )
            else:
                response = self._client.messages.create(messages=self._messages, **self._request)
        except anthropic.AuthenticationError as exc:
            raise LLMError("The assistant's API key was rejected.", 503) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("The assistant is busy. Please try again in a moment.", 429) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Model API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("The assistant could not be reached.") from exc

        self._last_content = response.content
        return ModelTurn(
            text="".join(b.text for b in response.content if b.type == "text"),
            tool_calls=[
                ToolCall(b.id, b.name, b.input) for b in response.content if b.type == "tool_use"
            ],
            stop_reason=self._STOP.get(response.stop_reason, "end"),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def submit(self, outputs: list[ToolOutput], note: str | None = None) -> None:
        self._messages.append({"role": "assistant", "content": self._last_content})
        content: list[dict] = [
            {
                "type": "tool_result",
                "tool_use_id": output.call.id,
                "content": output.content,
                "is_error": output.is_error,
            }
            for output in outputs
        ]
        if note:
            content.append({"type": "text", "text": note})
        self._messages.append({"role": "user", "content": content})


# --- Groq (OpenAI-compatible chat completions) -----------------------------------------------


def _allow_null_for_optional(schema: dict) -> dict:
    """Open models often send null for parameters they do not use, and Groq validates tool
    calls against the schema before returning them. Declaring optional parameters as nullable
    lets those calls through; the toolbox then drops the nulls."""
    schema = copy.deepcopy(schema)
    required = set(schema.get("required", []))
    for name, spec in schema.get("properties", {}).items():
        if name in required or "type" not in spec:
            continue
        spec["type"] = [spec["type"], "null"]
        if "enum" in spec:
            spec["enum"] = [*spec["enum"], None]
    return schema


class GroqLLM:
    def __init__(self, client: Any, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self.name = settings.groq_model

    def start(self, system: str, tools: list[dict], messages: list[dict]) -> ChatSession:
        return _GroqSession(self._client, self._settings, system, tools, messages)


class _GroqSession:
    def __init__(self, client, settings, system, tools, messages) -> None:
        self._client = client
        self._settings = settings
        self._tools = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": _allow_null_for_optional(tool["input_schema"]),
                },
            }
            for tool in tools
        ]
        self._messages: list[dict] = [{"role": "system", "content": system}, *messages]
        self._last_message: dict = {}

    def _create(self):
        import groq

        request = {
            "model": self._settings.groq_model,
            "messages": self._messages,
            "tools": self._tools,
            "tool_choice": "auto",
            "max_completion_tokens": self._settings.groq_max_tokens,
            "temperature": 0,
        }
        if self._settings.groq_reasoning_effort:
            request["reasoning_effort"] = self._settings.groq_reasoning_effort
        malformed_retry_left = True
        rate_limit_waits = self._settings.groq_rate_limit_waits
        try:
            while True:
                try:
                    return self._client.chat.completions.create(**request)
                except groq.BadRequestError as exc:
                    # Open models occasionally emit a malformed tool call, which Groq rejects
                    # with a 400. The same request usually succeeds on a second attempt.
                    if not malformed_retry_left or "tool" not in str(exc).lower():
                        raise
                    malformed_retry_left = False
                except groq.RateLimitError as exc:
                    # Free-tier limits are per minute, so waiting is usually enough.
                    if rate_limit_waits <= 0:
                        raise
                    rate_limit_waits -= 1
                    try:
                        delay = float(exc.response.headers.get("retry-after", 15))
                    except ValueError:
                        delay = 15.0
                    if delay > 5:
                        # A long wait means the daily quota is used up; waiting will not help.
                        raise
                    delay = max(delay, 1.0)
                    log.warning("rate limited by Groq, waiting %.0f s", delay)
                    time.sleep(delay)
        except groq.AuthenticationError as exc:
            raise LLMError("The assistant's API key was rejected.", 503) from exc
        except groq.RateLimitError as exc:
            raise LLMError("The assistant is busy. Please try again in a moment.", 429) from exc
        except groq.APIStatusError as exc:
            raise LLMError(f"Model API error {exc.status_code}: {exc.message}") from exc
        except groq.APIConnectionError as exc:
            raise LLMError("The assistant could not be reached.") from exc

    def step(self) -> ModelTurn:
        response = self._create()
        choice = response.choices[0]
        message = choice.message

        calls: list[ToolCall] = []
        raw_calls: list[dict] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = None
            if not isinstance(arguments, dict):
                arguments = {"_unparseable_arguments": call.function.arguments}
            calls.append(ToolCall(call.id, call.function.name, arguments))
            raw_calls.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
            )

        self._last_message = {"role": "assistant", "content": message.content or ""}
        if raw_calls:
            self._last_message["tool_calls"] = raw_calls

        if calls:
            stop: StopReason = "tool_use"
        elif choice.finish_reason == "length":
            stop = "max_tokens"
        else:
            stop = "end"
        usage = response.usage
        return ModelTurn(
            text=message.content or "",
            tool_calls=calls,
            stop_reason=stop,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    def submit(self, outputs: list[ToolOutput], note: str | None = None) -> None:
        self._messages.append(self._last_message)
        for output in outputs:
            self._messages.append(
                {"role": "tool", "tool_call_id": output.call.id, "content": output.content}
            )
        if note:
            self._messages.append({"role": "user", "content": note})


# --- Selection -------------------------------------------------------------------------------


PROVIDERS = ("groq", "anthropic")


def selected_provider(settings: Settings) -> str:
    """The provider named by `LLM_PROVIDER`, defaulting to Groq.

    The paid Claude API is never chosen implicitly: having an ANTHROPIC_API_KEY in the
    environment is not enough, `LLM_PROVIDER=anthropic` must be set as well.
    """
    return (settings.llm_provider or "groq").strip().lower()


def is_configured(settings: Settings) -> bool:
    """Whether the selected provider has its API key."""
    provider = selected_provider(settings)
    if provider == "groq":
        return bool(settings.groq_api_key)
    if provider == "anthropic":
        return bool(settings.anthropic_api_key)
    return False


def get_llm(settings: Settings | None = None) -> LLM:
    """Build the provider selected by `LLM_PROVIDER` (default: groq)."""
    settings = settings or get_settings()
    provider = selected_provider(settings)

    if provider == "groq":
        if not settings.groq_api_key:
            raise LLMNotConfigured(
                "GROQ_API_KEY is missing. Add it to .env, or set LLM_PROVIDER=anthropic "
                "and ANTHROPIC_API_KEY to use Claude instead."
            )
        import groq

        return GroqLLM(
            groq.Groq(
                api_key=settings.groq_api_key,
                max_retries=0,
                timeout=settings.provider_timeout_seconds,
            ),
            settings,
        )
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMNotConfigured("LLM_PROVIDER is anthropic but ANTHROPIC_API_KEY is missing.")
        import anthropic

        return AnthropicLLM(
            anthropic.Anthropic(
                api_key=settings.anthropic_api_key,
                max_retries=0,
                timeout=settings.provider_timeout_seconds,
            ),
            settings,
        )
    raise LLMNotConfigured(
        f"Unknown LLM_PROVIDER: {settings.llm_provider!r}. Use one of: {', '.join(PROVIDERS)}."
    )
