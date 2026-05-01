"""LLM service.

Primary provider: Anthropic (Claude) — structured output via tool_use.
Fallback provider: Google Gemini, used automatically on repeated overload / 5xx
or when ANTHROPIC_API_KEY is empty but GEMINI_API_KEY is set.

Public surface (used by agents):
    - chat_with_tools(...)            non-streaming, supports Anthropic tool_use loop
    - stream_chat_with_tools(...)     async iterator of typed events for SSE

Both functions go through the rate limiter and update the token budget.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from anthropic import APIError, APIStatusError, AsyncAnthropic
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.logging_config import get_logger
from app.services.rate_limiter import RateLimiter, record_call
from app.services.token_budget import TokenBudgetExceeded, get_token_budget

log = get_logger(__name__)

# ----------------------------------------------------------------------------
# Domain types
# ----------------------------------------------------------------------------


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class LlmMessage:
    role: str  # "user" | "assistant" | "tool"
    content: Any  # str OR list of typed blocks (for tool_use exchanges)


@dataclass
class LlmResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    provider: str = "anthropic"
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamEvent:
    type: str  # "text" | "tool_use" | "message_stop" | "error"
    text: str | None = None
    tool_call: ToolCall | None = None
    error: str | None = None


# ----------------------------------------------------------------------------
# Provider clients
# ----------------------------------------------------------------------------

_settings = get_settings()
_rate_limiter = RateLimiter(rpm_per_provider=_settings.llm_rate_limit_rpm)
_anthropic: AsyncAnthropic | None = None


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = AsyncAnthropic(api_key=_settings.anthropic_api_key)
    return _anthropic


# Gemini is imported lazily so the module does not crash if google-generativeai
# is missing in dev shells without a key.
def _get_gemini():
    if not _settings.gemini_api_key:
        return None
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        log.warning("gemini.import_failed")
        return None
    genai.configure(api_key=_settings.gemini_api_key)
    return genai


# ----------------------------------------------------------------------------
# Anthropic call helpers
# ----------------------------------------------------------------------------

_RETRYABLE_ANTHROPIC = (APIStatusError,)


def _tools_for_anthropic(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def _messages_for_anthropic(messages: list[LlmMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m.content, str):
            out.append({"role": m.role, "content": m.content})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


async def _anthropic_create(
    *,
    model: str,
    system: str,
    messages: list[LlmMessage],
    tools: list[ToolSpec] | None,
    max_tokens: int,
    temperature: float,
) -> LlmResponse:
    client = _get_anthropic()
    await _rate_limiter.acquire("anthropic")

    kwargs: dict[str, Any] = {
        "model": model,
        "system": system,
        "messages": _messages_for_anthropic(messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = _tools_for_anthropic(tools)

    record_call("anthropic")
    response = await client.messages.create(**kwargs)

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in response.content:
        bt = getattr(block, "type", None)
        if bt == "text":
            text_parts.append(block.text)
        elif bt == "tool_use":
            tool_calls.append(
                ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
            )
    usage = response.usage
    in_tok = getattr(usage, "input_tokens", 0)
    out_tok = getattr(usage, "output_tokens", 0)
    await get_token_budget().record(
        provider="anthropic", input_tokens=in_tok, output_tokens=out_tok
    )
    return LlmResponse(
        text="".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=response.stop_reason,
        raw=response.model_dump(),
        provider="anthropic",
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


# ----------------------------------------------------------------------------
# Gemini call helpers (best-effort fallback; supports text + tool calls)
# ----------------------------------------------------------------------------


def _gemini_history(messages: list[LlmMessage]) -> list[dict[str, Any]]:
    """Map our message format to Gemini's contents format (text-only)."""
    history: list[dict[str, Any]] = []
    for m in messages:
        role = "user" if m.role == "user" else "model"
        if isinstance(m.content, str):
            history.append({"role": role, "parts": [m.content]})
        else:
            chunks: list[str] = []
            for blk in m.content:
                if isinstance(blk, dict):
                    if blk.get("type") == "text":
                        chunks.append(blk.get("text", ""))
                    elif blk.get("type") == "tool_use":
                        chunks.append(
                            f"[tool_use {blk.get('name')}({json.dumps(blk.get('input', {}))})]"
                        )
                    elif blk.get("type") == "tool_result":
                        chunks.append(f"[tool_result] {blk.get('content', '')}")
            history.append({"role": role, "parts": [" ".join(c for c in chunks if c)]})
    return history


def _proto_to_python(value: Any) -> Any:
    """Deep-convert proto-plus / MapComposite / RepeatedComposite values to
    plain Python dicts/lists/scalars so they can be json.dumps'd."""
    if hasattr(value, "items") and not isinstance(value, dict):
        return {k: _proto_to_python(v) for k, v in value.items()}
    if isinstance(value, dict):
        return {k: _proto_to_python(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) or (
        hasattr(value, "__iter__") and not isinstance(value, (str, bytes))
    ):
        try:
            return [_proto_to_python(v) for v in value]
        except TypeError:
            return value
    return value


_GEMINI_SCHEMA_ALLOWED = {
    "type", "format", "description", "nullable", "enum",
    "properties", "required", "items",
}


def _sanitize_for_gemini(schema: Any) -> Any:
    """Strip JSON-schema keywords Gemini's function declarations reject
    (minimum/maximum/title/default/$defs/anyOf/allOf/oneOf/etc).
    Recursive; returns a new structure."""
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for k, v in schema.items():
            if k not in _GEMINI_SCHEMA_ALLOWED:
                continue
            if k == "properties" and isinstance(v, dict):
                out[k] = {pk: _sanitize_for_gemini(pv) for pk, pv in v.items()}
            elif k == "items":
                out[k] = _sanitize_for_gemini(v)
            else:
                out[k] = v
        if "type" not in out and ("properties" in out or "required" in out):
            out["type"] = "object"
        return out
    if isinstance(schema, list):
        return [_sanitize_for_gemini(x) for x in schema]
    return schema


async def _gemini_create(
    *,
    system: str,
    messages: list[LlmMessage],
    tools: list[ToolSpec] | None,
    max_tokens: int,
    temperature: float,
) -> LlmResponse:
    genai = _get_gemini()
    if genai is None:
        raise RuntimeError("Gemini fallback unavailable: set GEMINI_API_KEY.")
    await _rate_limiter.acquire("gemini")

    gemini_tools = None
    if tools:
        gemini_tools = [
            {
                "function_declarations": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": _sanitize_for_gemini(t.input_schema),
                    }
                    for t in tools
                ]
            }
        ]

    model = genai.GenerativeModel(
        model_name=_settings.gemini_model,
        system_instruction=system,
        tools=gemini_tools,
    )

    history = _gemini_history(messages)
    record_call("gemini")

    def _do() -> Any:
        return model.generate_content(
            history,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        )

    response = await asyncio.to_thread(_do)

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for cand in response.candidates or []:
        for part in getattr(cand.content, "parts", []) or []:
            if getattr(part, "text", None):
                text_parts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                tool_calls.append(
                    ToolCall(
                        id=f"gemini-{len(tool_calls)}",
                        name=fc.name,
                        arguments=_proto_to_python(fc.args) if fc.args else {},
                    )
                )

    usage = getattr(response, "usage_metadata", None)
    in_tok = getattr(usage, "prompt_token_count", 0) if usage else 0
    out_tok = getattr(usage, "candidates_token_count", 0) if usage else 0
    await get_token_budget().record(
        provider="gemini", input_tokens=in_tok, output_tokens=out_tok
    )
    return LlmResponse(
        text="".join(text_parts),
        tool_calls=tool_calls,
        stop_reason="end_turn" if not tool_calls else "tool_use",
        provider="gemini",
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def _have_anthropic() -> bool:
    return bool(_settings.anthropic_api_key)


def _have_gemini() -> bool:
    return bool(_settings.gemini_api_key)


async def chat_with_tools(
    *,
    system: str,
    messages: list[LlmMessage],
    tools: list[ToolSpec] | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> LlmResponse:
    """Single non-streaming call. Tries Anthropic, falls back to Gemini."""
    chosen_model = model or _settings.anthropic_model_primary

    if _have_anthropic():
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(_RETRYABLE_ANTHROPIC),
                wait=wait_exponential(multiplier=1, min=1, max=15),
                stop=stop_after_attempt(3),
                reraise=True,
            ):
                with attempt:
                    return await _anthropic_create(
                        model=chosen_model,
                        system=system,
                        messages=messages,
                        tools=tools,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
        except (RetryError, APIError, TokenBudgetExceeded) as exc:
            log.warning("anthropic.failed_falling_back", error=str(exc))
            if not _have_gemini():
                raise

    if _have_gemini():
        return await _gemini_create(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    raise RuntimeError(
        "No LLM provider configured. Set ANTHROPIC_API_KEY or GEMINI_API_KEY."
    )


async def stream_chat_with_tools(
    *,
    system: str,
    messages: list[LlmMessage],
    tools: list[ToolSpec] | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> AsyncIterator[StreamEvent]:
    """Stream text deltas and tool_use blocks. Anthropic-only for now;
    Gemini path falls back to a single non-streaming response chunk.
    """
    chosen_model = model or _settings.anthropic_model_primary

    if _have_anthropic():
        client = _get_anthropic()
        await _rate_limiter.acquire("anthropic")
        record_call("anthropic")

        kwargs: dict[str, Any] = {
            "model": chosen_model,
            "system": system,
            "messages": _messages_for_anthropic(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = _tools_for_anthropic(tools)

        try:
            async with client.messages.stream(**kwargs) as stream:
                current_tool: dict[str, Any] | None = None
                async for event in stream:
                    et = getattr(event, "type", None)
                    if et == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", None) == "tool_use":
                            current_tool = {
                                "id": block.id,
                                "name": block.name,
                                "input_json": "",
                            }
                    elif et == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        dt = getattr(delta, "type", None) if delta else None
                        if dt == "text_delta":
                            yield StreamEvent(type="text", text=delta.text)
                        elif dt == "input_json_delta" and current_tool is not None:
                            current_tool["input_json"] += delta.partial_json
                    elif et == "content_block_stop" and current_tool is not None:
                        try:
                            args = json.loads(current_tool["input_json"] or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamEvent(
                            type="tool_use",
                            tool_call=ToolCall(
                                id=current_tool["id"],
                                name=current_tool["name"],
                                arguments=args,
                            ),
                        )
                        current_tool = None
                    elif et == "message_stop":
                        yield StreamEvent(type="message_stop")
                final = await stream.get_final_message()
                usage = getattr(final, "usage", None)
                if usage:
                    await get_token_budget().record(
                        provider="anthropic",
                        input_tokens=getattr(usage, "input_tokens", 0),
                        output_tokens=getattr(usage, "output_tokens", 0),
                    )
            return
        except (APIError, APIStatusError) as exc:
            log.warning("anthropic.stream_failed_falling_back", error=str(exc))
            if not _have_gemini():
                yield StreamEvent(type="error", error=str(exc))
                return

    if _have_gemini():
        resp = await _gemini_create(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if resp.text:
            yield StreamEvent(type="text", text=resp.text)
        for tc in resp.tool_calls:
            yield StreamEvent(type="tool_use", tool_call=tc)
        yield StreamEvent(type="message_stop")
        return

    yield StreamEvent(type="error", error="No LLM provider configured")
