# Regulatory Compliance Agents

## Foundational Framework
Both agents share a common base in `backend/app/agents/base.py` and the LLM service in `backend/app/services/llm.py`, which enforce strict operational rules:
- **Fallback Capability**: Uses Claude (Sonnet 4.6) as the primary model. If Anthropic returns 5xx / overload (after 3 retries with exponential backoff), it falls back to Gemini.
- **Budget Tracking**: Every call tracks input/output tokens through the `TokenBudget` service and is enforced per-request and per-day to prevent runaway spend.
- **MCP-only data access**: Agents never import the database or Chroma directly. All reads/writes go through the two MCP servers (Control Registry on `:9001`, Document Store on `:9002`).
- **Loop Guards**: Each run is bounded by `max_iterations` and a tool-call fingerprint. If the same tool is called with identical args twice in a row, the agent halts.
- **Externalized Prompts**: System and user prompts live in `/prompts/*.md` and are rendered with `str.format(**vars)`. The loader strips HTML comments and fails fast on empty files.

---

## 1. Extraction Agent
- **Role**: First-responder to a freshly ingested regulatory document. Reads it chunk-by-chunk and writes every extracted control into the registry.
- **Integration**: Hosted on an A2A endpoint at `POST /a2a/tasks` and discoverable via `GET /.well-known/agent.json`. External systems can submit a PDF/text/markdown document directly.
- **Reasoning Pattern**: Plan and Execute. The agent first records a chunk-by-chunk plan, then iterates over it.
- **Tools**:
  - `document_store_list_chunks` (MCP Server 2): Lists every chunk for the document in order.
  - `document_store_get_chunk` (MCP Server 2): Fetches a single chunk's text + metadata.
  - `document_store_search` (MCP Server 2): Semantic search across the corpus when cross-referencing is needed.
  - `control_registry_search_regulatory` (MCP Server 1): Checks what's already extracted to avoid duplicates.
  - `control_registry_create_control` (MCP Server 1): Persists each extracted control as a `ControlSpec` (Pydantic structured output via `tool_use`).
  - `planning_record_plan` / `planning_mark_step_done` (in-process): Records the plan and tracks progress.
- **Input**: `document_id` (UUID) and document name, dispatched by the ingestion pipeline or by an A2A client.
- **Output**: JSON `ControlSpec` rows in the `regulatory_controls` table — `title`, `description`, `framework`, `risk_domain`, `severity`, `source_chunk_id`, `source_quote`. Triggers gap analysis which writes `GapMapping` rows.
- **Failure Handling**: Anthropic failures hand off to Gemini inside the LLM service. Repeated identical tool calls halt the loop. On unrecoverable failure, the document is flipped to `FAILED`. A startup hook in `main.py` resets any rows stuck in `EXTRACTING` from a prior crash.
- **Token Budget**: ~4,096 max output tokens per call. `max_iterations = 25`. Per-call usage recorded in `AgentRunStats`.
- **Coordination**: Writes to the **Control Registry MCP**. The ingestion pipeline then runs the **Gap Analyzer**, which embeds regulatory + org controls and persists `COVERED / PARTIAL / MISSING` decisions. Sets document status to `READY`, which the frontend surfaces with a `Start Q&A` action.

---

## 2. Q&A Agent
- **Role**: Answers natural-language questions about the regulatory corpus and the org's compliance posture, with citations. Streams responses to the chat UI over SSE.
- **Reasoning Pattern**: ReAct (Reason + Act). The agent decides whether more retrieval is needed, calls a tool, observes the result, and either loops or commits to a streamed final answer.
- **Tools**:
  - `document_store_search` (MCP Server 2): Semantic search over Chroma. Optional `document_id` filter scopes retrieval to one document — used when the user clicks `Start Q&A` from the Upload page.
  - `document_store_list_documents` (MCP Server 2): Disambiguates when the user mentions a doc by name.
  - `control_registry_search_regulatory` (MCP Server 1): Searches extracted regulatory controls.
  - `control_registry_search_organization` (MCP Server 1): Searches the org's existing controls — the second half of every "are we compliant with X" question.
  - `control_registry_gap_summary` (MCP Server 1): Aggregate coverage counts by framework × severity.
- **Input**: A user question, the chat session's prior turns, and an optional `document_id` scope from the URL params.
- **Output**: A streamed answer assembled from `token` SSE events with `[chunk_id: ...]` citations for regulatory claims and `[control: ...]` citations for org-control claims. A final `final` event carries the complete answer + `Citation` list, persisted as a `ChatMessage` row.
- **Failure Handling**: Anthropic streaming failures fall back to a single non-streaming Gemini response. The MCP-tool adapter auto-rewraps flat args under `payload` to handle Gemini's tendency to flatten wrapper objects. Tool errors are returned as `tool_result` with `is_error=true` so the model can self-correct on the next turn. Hard failures emit an `error` SSE event and log `chat.producer_failed`.
- **Token Budget**: ~2,048 max output tokens per call. `max_iterations = 6`.
- **Coordination**: Pulls from both MCP servers — that's the agent-to-agent coordination, mediated through MCP instead of direct function calls. For "are we compliant" / "what gaps exist" questions, the agent checks both the regulatory text and the org control registry before answering, enforced by the system prompt in `prompts/qa_agent.system.md`.
