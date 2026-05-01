# Prompts

## Files the backend loads

| File | Loaded by | Purpose |
| --- | --- | --- |
| `extraction_agent.system.md` | `app/agents/extraction_agent.py` | System prompt for the Extraction Agent (Plan-and-Execute pattern). |
| `extraction_classification.user.md` | `app/agents/extraction_agent.py` | User-prompt template for control extraction. Variables: `{chunk_text}`, `{document_name}`. |
| `qa_agent.system.md` | `app/agents/qa_agent.py` | System prompt for the Q&A Agent (ReAct pattern, RAG citations, MCP cross-reference). |
| `qa_agent.user.md` | `app/agents/qa_agent.py` | User-prompt template for Q&A. Variables: `{question}`, `{retrieved_context}`, `{conversation_history}`. |
| `triage_planner.system.md` | `app/agents/extraction_agent.py` (planning step) | Optional: system prompt for the planner step that decides which chunks to read first. |
| `few_shot_examples.md` | both agents | Optional: few-shot extraction / Q&A examples to ship into the user prompt. |

