# Local Ollama setup

The backend talks to Ollama's HTTP API (`/api/chat`, `/api/embed`). Settings (root `.env`, see `.env.example`):

| Variable | Meaning |
|---|---|
| `OLLAMA_BASE_URL` | default `http://localhost:11434` (Ollama installed on the host) |
| `OLLAMA_MODEL` | exact installed chat model tag; configured: `llama3.2:3b` |
| `OLLAMA_EMBED_MODEL`, `EMBED_DIMENSIONS` | embedding model and its vector size; configured: `nomic-embed-text`, 768 |
| `OLLAMA_NUM_CTX` | context window requested on every call (default 8192) |
| `OLLAMA_PROMPT_BUDGET_RATIO` | share of the window the prompt may use (default 0.8); the remainder is reserved for the reply and sent as `num_predict` |
| `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_RETRIES` | per-request timeout and bounded retries |

Why `llama3.2:3b` with 8192: the development machine has an 8 GB GPU / 15.6 GB RAM; a 3B Q4 model plus an 8k KV cache
fits comfortably, while the installed `phi3` has a 4k native context and cannot produce embeddings.
If you change `OLLAMA_EMBED_MODEL` to one with a different dimension, update `EMBED_DIMENSIONS` and drop the
Neo4j vector indexes (they are recreated on start) before re-embedding with
`cd backend && python -m services.graph.sync backfill`.

Models: `ollama pull llama3.2:3b` and `ollama pull nomic-embed-text` (one-time).
To run Ollama in a container instead of on the host: stop the host Ollama, then
`docker compose --profile ollama-container up -d ollama` and pull the models inside it.
