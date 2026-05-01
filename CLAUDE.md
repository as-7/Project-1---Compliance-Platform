# CLAUDE.md


# Project

REGULATORY COMPLIANCE INTELLIGENCE PLATFORM

# Tech Stack

- Backend: Python, FastAPI
- Frontend: React
- Database: Postgres
- Vector Database: Chroma
- LLM: Claude / Gemini as fallback
- Embedding: Local sentence-transformers (all-MiniLM-L6-v2, 384 dims) - free to use on local

## Conventions

- Entire web app must be asynchronous, no blocking of events
- Endpoints should be SSE(Server Sent Events) for the chat interface
- Always use asyncio library for async funtionality, in case we want to run parallel tasks
- Always type hinting for functions
- Use pydantic for structured outputs
- Major pieces should have rate limiting, token budget tracking (For Agents, tool calls)
- Proper logging of events in the entire application
- Prompts must have values passed as variables whever applicable

## Low Level Design
- Use OOP concepts for creation of classes
- Use SOLID principles wherever applicable. Do not force them. See where a pattern is forming and then decide if it fits.

## Domain Notes
- Compliance work often involves sensitive data. When applicable:
- Never commit secrets, credentials, PII, or regulated data related to organizations.

## General instructions
- Prefer environment variables and a `.env` (gitignored) for local config.

## Workflow
- Ask before taking destructive or shared-state actions (push, force-push, deleting branches/files).

