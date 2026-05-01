# Conversation so far

{conversation_history}

# Retrieved context

The following passages were retrieved from the regulatory corpus. Use them as
your primary evidence. If they are insufficient, call `search_documents` again
with a refined query before answering.

{retrieved_context}

# Current question

{question}

# Instructions for this turn

1. Reason briefly about what information is needed to answer the question.
2. If the retrieved context above is empty, generic, or off-topic, call the
   appropriate MCP tool (`search_documents`, `search_regulatory_controls`,
   `search_organization_controls`, or `get_gap_summary`) before responding.
3. For "are we compliant with X" style questions, you must check both the
   regulatory text AND the organization control registry. Do not answer from
   regulatory text alone.
4. Every regulatory claim must be cited as `[chunk_id: <id>]`. Every claim
   about an organization control must be cited as `[control: <code>]`.
5. If the evidence is insufficient, state that explicitly. Do not fabricate.
