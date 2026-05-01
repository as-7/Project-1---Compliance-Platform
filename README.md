# Regulatory Compliance Intelligence Platform

A full-stack application that ingests regulatory documents (PDF/text), uses AI agents to extract and map compliance controls, classifies them by framework (SOC 2, ISO 27001, GDPR, HIPAA), identifies gaps against your organization's existing controls, and provides an interactive dashboard with natural language Q&A over the regulatory corpus.

## One-command setup

```bash
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY (required) and GEMINI_API_KEY (fallback, optional)
docker compose up --build
```

Once everything is healthy:

| Service | URL |
| --- | --- |
| Frontend (React) | http://localhost:5173 |
| Backend (FastAPI) | http://localhost:8080 |
| API docs | http://localhost:8080/docs |
| A2A agent card | http://localhost:8080/.well-known/agent.json |
| MCP — Control Registry | http://localhost:9001/mcp |
| MCP — Document Store | http://localhost:9002/mcp |
| n8n | http://localhost:5678 (admin / admin) |
| Chroma | http://localhost:8000 |
| Postgres | localhost:5432 |

The backend container runs migrations and seeds 3 regulatory excerpts + 25 organization controls automatically on first start.

## Demo flow

1. Open the frontend, go to **Upload**, drop a regulatory document (or use the seeded ones).
2. Watch the Extraction Agent run in **Controls** — extracted controls populate live.
3. Open **Gaps** — heatmap of org coverage vs. regulatory requirements.
4. Open **Chat** — ask `What does the document say about data retention?` (RAG-powered, streamed, with citations). Ask `Are we compliant with access logging?` — the Q&A Agent will cross-reference the Control Registry MCP, not just search documents.
5. Trigger the n8n workflow webhook to simulate an external upload.
6. Run `python scripts/a2a_client_demo.py` to exercise the Extraction Agent via A2A.

## Architecture

See [architecture.md](architecture.md) for the system diagram, component descriptions, data flow, protocol map, and agent design rationale.
See [agents.md](agents.md) for per-agent specifications (role, reasoning pattern, tools, I/O, failure handling, token budgets).

## Repo layout

```
backend/        FastAPI app, agents, MCP servers, RAG, DB
frontend/       React (Vite + TypeScript)
prompts/        Externalized agent prompts (candidate-authored)
n8n-workflows/  Exported workflow JSON + screenshots
tests/          Unit, API, integration tests
scripts/        A2A client demo, ad-hoc utilities
```

## Tech choices (summary)

- **LLM**: Anthropic Claude (Sonnet 4.6 primary, Haiku 4.5 for fast classification). Gemini 2.5 Pro as automatic fallback if Anthropic returns repeated 5xx/overload.
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (local, 384-dim, no API cost).
- **Vector DB**: Chroma (HTTP mode, persistent volume).
- **Primary DB**: Postgres 16 (async via SQLAlchemy + asyncpg).
- **MCP**: FastMCP, streamable-HTTP transport.
- **Frontend**: React + Vite + TypeScript + Tailwind.
- **Workflow**: n8n.

## Tests

```bash
docker compose exec backend pytest
```

## What I'd improve with more time

(Filled in by the candidate.)
# Project-1---Compliance-Platform
