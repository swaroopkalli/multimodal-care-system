# Phase 2: Live chat context management

## Active request flow

Both `/api/patient/chat` and `/api/staff/chat` authenticate and authorize the
caller, check the original user message with the input guard, condense very long
messages without silently truncating them, build current patient state, load
patient conversation history where applicable, and retrieve patient-scoped
evidence from Neo4j hydrated from PostgreSQL. NVIDIA NIM supplies both chat
completions and query/document embeddings. The live handlers pass those
sources to `services/context_manager.assemble_context` before generation.

The manager centrally assembles policy, current authorized state, retrieved
evidence, recent conversation turns, and the current query. Retrieved state and
history are wrapped as untrusted data. It deduplicates evidence, records source
metadata and a per-request manifest, compacts old complete conversation turns
first and then lower-ranked evidence, and returns HTTP 413 if mandatory policy,
state, and query cannot fit. The response includes `context.manifest` with
request ID, role, state version, evidence references, token estimate, output
reserve, and compaction count. The manifest is request metadata; it is not
persisted and contains no prompt text.

The context state version is the existing relational source hash. It covers the
inputs used by the current context builder, but is not a database-wide
transaction revision. Wearable summaries are included in the state text; the
manifest's dedicated wearable-version list remains empty because those records
do not have individual revision identifiers.

## Independent guardrails

Guardrails remain separate from context assembly. The input guard runs on the
original message before any condensation. After context construction, the output
guard independently checks each model draft against the assembled source text,
retries with a correction instruction a bounded number of times, and returns a
fixed fallback if drafts remain unsafe or checking errors. Patient crisis
language is handled by the input guard before model generation. Context
assembly does not make clinical decisions or replace these checks.

## Budget configuration

Unless explicitly overridden, the manager inherits the active LLM context
window and response reserve from `services.llm.context_settings`. The
watermarks and retention defaults are:

```dotenv
CONTEXT_HIGH_WATERMARK=0.80
CONTEXT_LOW_WATERMARK=0.60
CONTEXT_RECENT_TURNS=5
CONTEXT_EVIDENCE_MAX_ITEMS=8
```

Optional overrides are `CONTEXT_WINDOW_TOKENS` and
`CONTEXT_OUTPUT_RESERVE_TOKENS`. The estimator is a conservative fallback of
one token per three UTF-8 bytes plus message overhead; it is not the model's
exact tokenizer. Measured prompt usage continues to calibrate the existing
budget estimator. For a particular model and language, compare estimates with
the provider's reported token counts.

Current state and the query are mandatory. If they cannot fit, the request
fails clearly rather than silently deleting patient facts. Conversation
compaction removes oldest complete user/assistant messages, then evidence from
the end of the ranked list. Source rows are never deleted. Chat history remains
available to patient chat; staff chat uses scoped retrieval instead of patient
chat history.

Neo4j retrieval is required for live model-generated chat. If Neo4j or NVIDIA
embedding inference is unavailable, the endpoint returns HTTP 503 without
calling the chat model. Retrieval filters to the configured embedding model
version, so records created with a previous model are ignored until re-embedded.
See `phase1-nvidia-setup.md`. This integration adds no relational database
migration or new clinical rules.
