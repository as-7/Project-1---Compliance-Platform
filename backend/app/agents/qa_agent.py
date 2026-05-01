"""Q&A Agent — ReAct pattern, streaming, RAG + Control Registry coordination.

Behavior:
  - Receives a user question + conversation history.
  - Reasons (text) about what info it needs.
  - Calls document_store_search for RAG, and control_registry_* tools when the
    question is about coverage / gaps.
  - Streams text deltas back to the caller via async generator.
  - Emits citations in the final answer; the SSE layer extracts them.

Stop conditions:
  - Model emits no tool calls (turn complete).
  - max_iterations reached.
  - duplicate-call guard trips.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.config import get_settings
from app.logging_config import get_logger
from app.schemas.common import Citation
from app.services.llm import (
    LlmMessage,
    StreamEvent,
    ToolCall,
    ToolSpec,
    chat_with_tools,
    stream_chat_with_tools,
)
from app.services.prompts import load_prompt, render_prompt
from app.agents.base import (
    AgentRunStats,
    AgentTool,
    build_assistant_message_content,
    build_user_tool_results,
    fingerprint_call,
    make_mcp_tool,
    run_tool,
)

log = get_logger(__name__)

_settings = get_settings()
_MAX_ITERATIONS = 6
_DUP_LIMIT = 2


@dataclass
class QaTurn:
    answer: str = ""
    citations: list[Citation] = field(default_factory=list)
    stats: AgentRunStats = field(default_factory=AgentRunStats)


@dataclass
class QaStreamEvent:
    type: str  # "token" | "tool_use" | "tool_result" | "citation" | "final"
    text: str | None = None
    tool: str | None = None
    detail: dict[str, Any] | None = None


_CITATION_RE = re.compile(r"\[chunk_id:\s*([^\]\s]+)\]")
_CONTROL_RE = re.compile(r"\[control:\s*([^\]\s]+)\]")


def _qa_tools() -> list[AgentTool]:
    search = make_mcp_tool(
        server="document-store",
        tool_name="search_documents",
        spec_name="document_store_search",
        description=(
            "Semantic search over regulatory documents. Returns top_k chunks "
            "with text, metadata, and similarity score. Use for any factual "
            "question about a regulation."
        ),
        input_schema={
            "type": "object",
            "properties": {"payload": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 15, "default": 5},
                    "document_id": {"type": "string", "format": "uuid"},
                },
                "required": ["query"],
            }},
            "required": ["payload"],
        },
    )
    list_docs = make_mcp_tool(
        server="document-store",
        tool_name="list_documents",
        spec_name="document_store_list_documents",
        description="List ingested documents. Use to disambiguate when the user mentions a doc by name.",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    reg_search = make_mcp_tool(
        server="control-registry",
        tool_name="search_regulatory_controls",
        spec_name="control_registry_search_regulatory",
        description="Search extracted regulatory controls by free text + framework/severity/risk_domain.",
        input_schema={
            "type": "object",
            "properties": {"payload": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "framework": {"type": "string", "enum": ["SOC2", "ISO27001", "GDPR", "HIPAA", "OTHER"]},
                    "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                    "risk_domain": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
            }},
            "required": ["payload"],
        },
    )
    org_search = make_mcp_tool(
        server="control-registry",
        tool_name="search_organization_controls",
        spec_name="control_registry_search_organization",
        description=(
            "Search the organization's existing controls. Use whenever the question "
            "is about coverage / 'are we compliant' / 'do we already have'."
        ),
        input_schema={
            "type": "object",
            "properties": {"payload": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "risk_domain": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
            }},
            "required": ["payload"],
        },
    )
    gap_summary = make_mcp_tool(
        server="control-registry",
        tool_name="get_gap_summary",
        spec_name="control_registry_gap_summary",
        description="Return aggregate gap counts by framework + severity. Use for high-level coverage questions.",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    return [search, list_docs, reg_search, org_search, gap_summary]


def _build_messages(
    *, history: list[dict[str, str]], question: str
) -> tuple[str, list[LlmMessage]]:
    """Render system + user prompts. The system prompt is candidate-authored;
    we feed the user prompt template `question` and `conversation_history`."""
    system_prompt = load_prompt("qa_agent.system")
    history_str = "\n".join(f"[{m['role']}] {m['content']}" for m in history)
    user_prompt = render_prompt(
        "qa_agent.user",
        conversation_history=history_str or "(no prior turns)",
        retrieved_context="(use the document_store_search tool to retrieve)",
        question=question,
    )
    return system_prompt, [LlmMessage(role="user", content=user_prompt)]


async def _extract_citations(text: str) -> list[Citation]:
    """Best-effort extraction of [chunk_id:...] and [control:...] markers."""
    citations: list[Citation] = []
    for cid in _CITATION_RE.findall(text):
        citations.append(Citation(chunk_id=cid))
    for ctrl in _CONTROL_RE.findall(text):
        try:
            citations.append(Citation(chunk_id="__control__", control_id=UUID(ctrl)))
        except ValueError:
            pass
    return citations


async def stream_answer(
    *,
    question: str,
    history: list[dict[str, str]] | None = None,
    max_iterations: int = _MAX_ITERATIONS,
) -> AsyncIterator[QaStreamEvent]:
    """Run the ReAct loop, streaming tokens out as the final answer is produced."""
    history = history or []
    system_prompt, messages = _build_messages(history=history, question=question)

    tools_list = _qa_tools()
    tools_index: dict[str, AgentTool] = {t.spec.name: t for t in tools_list}
    stats = AgentRunStats()
    final_text_parts: list[str] = []

    for _ in range(max_iterations):
        stats.iterations += 1

        # First, decide whether to act or answer (non-streaming) so we can react
        # to tool calls deterministically. The final answer turn streams below.
        response = await chat_with_tools(
            system=system_prompt,
            messages=messages,
            tools=[t.spec for t in tools_list],
            model=_settings.anthropic_model_primary,
            max_tokens=2048,
            temperature=0.0,
        )
        stats.input_tokens += response.input_tokens
        stats.output_tokens += response.output_tokens

        if not response.tool_calls:
            # Stream the final answer turn so the user sees tokens.
            final_messages = list(messages)
            async for ev in stream_chat_with_tools(
                system=system_prompt,
                messages=final_messages,
                tools=[t.spec for t in tools_list],
                model=_settings.anthropic_model_primary,
                max_tokens=2048,
                temperature=0.0,
            ):
                if ev.type == "text" and ev.text:
                    final_text_parts.append(ev.text)
                    yield QaStreamEvent(type="token", text=ev.text)
                elif ev.type == "tool_use":
                    # Should be rare on the second pass, but handle defensively.
                    pass
                elif ev.type == "error":
                    yield QaStreamEvent(type="final", detail={"error": ev.error})
                    return
            answer = "".join(final_text_parts).strip()
            citations = await _extract_citations(answer)
            yield QaStreamEvent(
                type="final",
                detail={
                    "answer": answer,
                    "citations": [c.model_dump(mode="json") for c in citations],
                    "stats": {
                        "iterations": stats.iterations,
                        "tool_calls": stats.tool_calls,
                        "input_tokens": stats.input_tokens,
                        "output_tokens": stats.output_tokens,
                    },
                },
            )
            return

        # Otherwise: persist assistant message + run tools, then loop.
        messages.append(
            LlmMessage(
                role="assistant",
                content=build_assistant_message_content(
                    text=response.text, tool_calls=response.tool_calls
                ),
            )
        )

        results = []
        for call in response.tool_calls:
            fp = fingerprint_call(call)
            stats.fingerprints[fp] = stats.fingerprints.get(fp, 0) + 1
            if stats.fingerprints[fp] > _DUP_LIMIT:
                results.append(
                    await run_tool(
                        tools_index,
                        ToolCall(id=call.id, name="__loop_break__", arguments=call.arguments),
                    )
                )
                continue
            stats.tool_calls += 1
            yield QaStreamEvent(type="tool_use", tool=call.name, detail=call.arguments)
            tr = await run_tool(tools_index, call)
            results.append(tr)
            try:
                preview = json.loads(tr.content)
            except (json.JSONDecodeError, TypeError):
                preview = {"raw": tr.content[:500]}
            yield QaStreamEvent(type="tool_result", tool=call.name, detail={"preview": preview})

        messages.append(
            LlmMessage(role="user", content=build_user_tool_results(results))
        )

    yield QaStreamEvent(
        type="final",
        detail={
            "answer": "I wasn't able to converge on an answer within the iteration budget. Please refine the question.",
            "citations": [],
            "stats": {
                "iterations": stats.iterations,
                "tool_calls": stats.tool_calls,
                "input_tokens": stats.input_tokens,
                "output_tokens": stats.output_tokens,
            },
        },
    )
