"""Extraction Agent — Plan-and-Execute pattern.

Phase 1 (Plan): The LLM is shown the document inventory + a small sample of
chunks via the Document Store MCP. It produces a plan: which chunks to read in
what order, with a brief justification. The plan is recorded via the in-memory
planner tool so it shows up in agent traces.

Phase 2 (Execute): The LLM iterates over the plan. For each chunk it calls
get_chunk via the Document Store MCP, then emits zero-or-more
create_regulatory_control tool calls (Control Registry MCP) using the
ControlSpec schema as structured output.

Loop guards:
    - max_iterations
    - duplicate-call detector (same tool + identical args)
    - per-call tool error budget
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.config import get_settings
from app.logging_config import get_logger
from app.mcp_clients import registry as mcp_registry
from app.schemas.common import ControlSpec
from app.services.llm import (
    LlmMessage,
    ToolCall,
    ToolSpec,
    chat_with_tools,
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


# ----------------------------------------------------------------------------
# In-process planner tool — records the plan so we can stream it to clients.
# ----------------------------------------------------------------------------


@dataclass
class ExtractionRun:
    document_id: UUID
    plan: list[str] = field(default_factory=list)
    completed_steps: list[int] = field(default_factory=list)
    extracted_controls: list[dict[str, Any]] = field(default_factory=list)
    stats: AgentRunStats = field(default_factory=AgentRunStats)


def _planner_tools(run: ExtractionRun) -> list[AgentTool]:
    async def _record_plan(args: dict[str, Any]) -> dict[str, Any]:
        steps = args.get("steps") or []
        run.plan = list(steps)
        log.info("extraction.plan_recorded", document_id=str(run.document_id), steps=len(steps))
        return {"acknowledged": True, "step_count": len(steps)}

    async def _mark_step_done(args: dict[str, Any]) -> dict[str, Any]:
        idx = int(args.get("step_index", -1))
        if 0 <= idx < len(run.plan):
            run.completed_steps.append(idx)
            return {"acknowledged": True, "remaining": len(run.plan) - len(run.completed_steps)}
        return {"acknowledged": False, "error": "step_index out of range"}

    return [
        AgentTool(
            spec=ToolSpec(
                name="planning_record_plan",
                description=(
                    "Record the ordered plan of which chunks to read and what to look for. "
                    "Call this exactly once at the start of the run."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ordered list of plan steps (max 25).",
                        }
                    },
                    "required": ["steps"],
                },
            ),
            handler=_record_plan,
        ),
        AgentTool(
            spec=ToolSpec(
                name="planning_mark_step_done",
                description="Mark a previously recorded plan step as completed.",
                input_schema={
                    "type": "object",
                    "properties": {"step_index": {"type": "integer", "minimum": 0}},
                    "required": ["step_index"],
                },
            ),
            handler=_mark_step_done,
        ),
    ]


# ----------------------------------------------------------------------------
# MCP-backed tools exposed to the agent.
# ----------------------------------------------------------------------------


def _document_store_tools(document_id: UUID) -> list[AgentTool]:
    list_chunks = make_mcp_tool(
        server="document-store",
        tool_name="list_chunks",
        spec_name="document_store_list_chunks",
        description=(
            f"List every chunk for the current document ({document_id}). Returns "
            "chunk_id, text, and metadata in document order."
        ),
        input_schema={
            "type": "object",
            "properties": {"payload": {
                "type": "object",
                "properties": {"document_id": {"type": "string", "format": "uuid"}},
                "required": ["document_id"],
            }},
            "required": ["payload"],
        },
    )
    get_chunk = make_mcp_tool(
        server="document-store",
        tool_name="get_chunk",
        spec_name="document_store_get_chunk",
        description="Fetch full text + metadata for a single chunk by id.",
        input_schema={
            "type": "object",
            "properties": {"payload": {
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}},
                "required": ["chunk_id"],
            }},
            "required": ["payload"],
        },
    )
    search = make_mcp_tool(
        server="document-store",
        tool_name="search_documents",
        spec_name="document_store_search",
        description="Semantic search over all ingested regulatory documents.",
        input_schema={
            "type": "object",
            "properties": {"payload": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5},
                    "document_id": {"type": "string", "format": "uuid"},
                },
                "required": ["query"],
            }},
            "required": ["payload"],
        },
    )
    return [list_chunks, get_chunk, search]


def _control_registry_tool(run: ExtractionRun, document_id: UUID) -> AgentTool:
    spec = ToolSpec(
        name="control_registry_create",
        description=(
            "Persist exactly one extracted regulatory control. Call once per "
            "distinct control found in a chunk. Use the structured ControlSpec."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 512},
                "description": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["SOC2", "ISO27001", "GDPR", "HIPAA", "OTHER"],
                },
                "risk_domain": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                },
                "source_chunk_id": {"type": "string"},
                "source_quote": {"type": "string"},
            },
            "required": [
                "title",
                "description",
                "framework",
                "risk_domain",
                "severity",
                "source_chunk_id",
                "source_quote",
            ],
        },
    )

    async def _handler(arguments: dict[str, Any]) -> Any:
        # Validate against ControlSpec then forward via MCP.
        validated = ControlSpec.model_validate(arguments)
        result = await mcp_registry.call_tool(
            "control-registry",
            "create_regulatory_control",
            {
                "payload": {
                    "document_id": str(document_id),
                    "spec": validated.model_dump(mode="json"),
                }
            },
        )
        payload = (
            result.structured_content
            if hasattr(result, "structured_content") and result.structured_content
            else json.loads(result.content[0].text)
            if hasattr(result, "content") and result.content
            else {}
        )
        run.extracted_controls.append(
            {**validated.model_dump(mode="json"), "id": payload.get("id")}
        )
        return payload

    return AgentTool(spec=spec, handler=_handler)


# ----------------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------------


_MAX_ITERATIONS = 25
_DUP_LIMIT = 2  # same tool + same args may run at most twice


async def run_extraction(
    document_id: UUID,
    *,
    document_name: str,
    max_iterations: int = _MAX_ITERATIONS,
) -> ExtractionRun:
    """Execute the Plan-and-Execute extraction loop for a document."""
    run = ExtractionRun(document_id=document_id)
    tools_list = (
        _planner_tools(run)
        + _document_store_tools(document_id)
        + [_control_registry_tool(run, document_id)]
    )
    tools_index: dict[str, AgentTool] = {t.spec.name: t for t in tools_list}

    system_prompt = load_prompt("extraction_agent.system")
    user_prompt = render_prompt(
        "extraction_classification.user",
        document_id=str(document_id),
        document_name=document_name,
        chunk_text="",  # The agent will fetch chunks via tools; template reserves the slot.
        chunk_id="",
    )

    messages: list[LlmMessage] = [LlmMessage(role="user", content=user_prompt)]

    for _ in range(max_iterations):
        run.stats.iterations += 1
        response = await chat_with_tools(
            system=system_prompt,
            messages=messages,
            tools=[t.spec for t in tools_list],
            model=_settings.anthropic_model_primary,
            max_tokens=4096,
            temperature=0.0,
        )
        run.stats.input_tokens += response.input_tokens
        run.stats.output_tokens += response.output_tokens

        if not response.tool_calls:
            log.info(
                "extraction.done",
                document_id=str(document_id),
                controls=len(run.extracted_controls),
            )
            return run

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
            run.stats.fingerprints[fp] = run.stats.fingerprints.get(fp, 0) + 1
            if run.stats.fingerprints[fp] > _DUP_LIMIT:
                # Refuse repeats so the agent can't loop on identical calls.
                results.append(
                    await run_tool(
                        tools_index,
                        ToolCall(
                            id=call.id,
                            name="__loop_break__",
                            arguments=call.arguments,
                        ),
                    )
                )
                continue
            run.stats.tool_calls += 1
            results.append(await run_tool(tools_index, call))

        messages.append(
            LlmMessage(role="user", content=build_user_tool_results(results))
        )

    log.warning("extraction.iteration_cap_hit", document_id=str(document_id))
    return run
