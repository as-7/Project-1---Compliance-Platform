"""Shared agent primitives: tool registry, loop limits, MCP-tool adapters."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger
from app.mcp_clients import registry as mcp_registry
from app.services.llm import ToolCall, ToolResult, ToolSpec

log = get_logger(__name__)

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class AgentTool:
    spec: ToolSpec
    handler: ToolHandler


@dataclass
class AgentRunStats:
    iterations: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    fingerprints: dict[str, int] = field(default_factory=dict)


def make_mcp_tool(
    *,
    server: str,
    tool_name: str,
    spec_name: str,
    description: str,
    input_schema: dict[str, Any],
) -> AgentTool:
    """Adapter: expose an MCP tool to the LLM as a regular ToolSpec."""

    expects_payload_wrapper = (
        isinstance(input_schema, dict)
        and "payload" in (input_schema.get("properties") or {})
    )

    async def _handler(arguments: dict[str, Any]) -> Any:
        # Some LLMs (notably Gemini) flatten the wrapper object even when the
        # schema declares one. Re-wrap so the MCP server's Pydantic model
        # validates correctly.
        if expects_payload_wrapper and "payload" not in arguments:
            arguments = {"payload": arguments}
        result = await mcp_registry.call_tool(server, tool_name, arguments)
        # FastMCP returns a CallToolResult; agents only need the structured payload.
        if hasattr(result, "structured_content") and result.structured_content is not None:
            return result.structured_content
        if hasattr(result, "content") and result.content:
            first = result.content[0]
            text = getattr(first, "text", None)
            if text is not None:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return str(result)

    return AgentTool(
        spec=ToolSpec(name=spec_name, description=description, input_schema=input_schema),
        handler=_handler,
    )


def fingerprint_call(call: ToolCall) -> str:
    """Stable hash of a tool call to detect repeated identical invocations."""
    payload = json.dumps(
        {"name": call.name, "args": call.arguments}, sort_keys=True, default=str
    )
    return payload


async def run_tool(tools: dict[str, AgentTool], call: ToolCall) -> ToolResult:
    handler = tools.get(call.name)
    if handler is None:
        return ToolResult(
            tool_use_id=call.id,
            content=json.dumps({"error": f"Unknown tool: {call.name}"}),
            is_error=True,
        )
    try:
        result = await handler.handler(call.arguments)
        if not isinstance(result, str):
            result = json.dumps(result, default=str)
        return ToolResult(tool_use_id=call.id, content=result)
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.tool_error", tool=call.name, error=str(exc))
        return ToolResult(
            tool_use_id=call.id,
            content=json.dumps({"error": str(exc)}),
            is_error=True,
        )


def build_assistant_message_content(
    *, text: str, tool_calls: list[ToolCall]
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in tool_calls:
        blocks.append(
            {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
        )
    return blocks


def build_user_tool_results(results: list[ToolResult]) -> list[dict[str, Any]]:
    return [
        {
            "type": "tool_result",
            "tool_use_id": r.tool_use_id,
            "content": r.content,
            "is_error": r.is_error,
        }
        for r in results
    ]
