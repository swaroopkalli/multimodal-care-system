# NVIDIA NIM setup

The backend uses NVIDIA NIM for both chat completions and Neo4j RAG embeddings.
Set the following in the ignored repository-root `.env` file:

```dotenv
NVIDIA_API_KEY=your-nvidia-api-key
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=nvidia/nemotron-3.5-bolt-e4b
NVIDIA_EMBED_MODEL=nvidia/nemotron-3.5-embed-1b
NVIDIA_EMBED_DIMENSIONS=768
EMBED_DIMENSIONS=768
```

The embedding API creates 768-dimensional vectors to match the current Neo4j
vector indexes. Chat and embeddings use the same API key. The exact chat and
embedding model IDs can be changed independently if the NVIDIA account has
access to them.

## Re-embed existing Neo4j records

Existing nodes may contain vectors made by the previous embedding model. New
query vectors cannot be compared reliably with those old vectors, even though
both have 768 dimensions. Retrieval filters for the configured model version,
so old vectors are ignored until re-embedded. Re-embed existing records before
expecting existing history and notes to appear in RAG:

```bash
cd backend
python -m services.graph.sync backfill
```

The backfill enqueues PostgreSQL records and the graph sync process recomputes
their vectors using the NVIDIA embedding model. It does not delete patient
records. Monitor progress with:

```bash
python -m services.graph.sync reconcile
```

Keep the same embedding model and dimensions for both indexing and query
embedding. If changing either later, enqueue a full backfill again. Changing
the vector dimension also requires recreating the Neo4j vector indexes with the
new matching `EMBED_DIMENSIONS` value.
