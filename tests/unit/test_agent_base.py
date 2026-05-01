"""Tests for the agent base helpers — fingerprinting + tool dispatch."""
from __future__ import annotations

import pytest

from app.agents.base import AgentTool, fingerprint_call, run_tool
from app.services.llm import ToolCall, ToolSpec


def test_fingerprint_stable():
    a = ToolCall(id="x", name="foo", arguments={"a": 1, "b": 2})
    b = ToolCall(id="y", name="foo", arguments={"b": 2, "a": 1})
    assert fingerprint_call(a) == fingerprint_call(b)


def test_fingerprint_distinct():
    a = ToolCall(id="x", name="foo", arguments={"a": 1})
    b = ToolCall(id="y", name="foo", arguments={"a": 2})
    assert fingerprint_call(a) != fingerprint_call(b)


@pytest.mark.asyncio
async def test_run_tool_dispatch_and_serialize():
    async def handler(args):
        return {"echo": args["msg"]}

    tools = {
        "echo": AgentTool(
            spec=ToolSpec(
                name="echo",
                description="echo back",
                input_schema={
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                    "required": ["msg"],
                },
            ),
            handler=handler,
        )
    }
    result = await run_tool(tools, ToolCall(id="1", name="echo", arguments={"msg": "hi"}))
    assert result.is_error is False
    assert "hi" in result.content


@pytest.mark.asyncio
async def test_run_tool_unknown_returns_error():
    result = await run_tool({}, ToolCall(id="1", name="ghost", arguments={}))
    assert result.is_error is True
    assert "Unknown tool" in result.content
