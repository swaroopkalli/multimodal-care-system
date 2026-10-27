# Local Ollama setup

The Flask backend's two existing chat endpoints now call local Ollama at
`/api/chat`. Configure `OLLAMA_BASE_URL` and `OLLAMA_MODEL` in the backend
environment. `OLLAMA_MODEL` must be an exact installed model tag. The default
URL for a backend running directly on the host is `http://localhost:11434`.
For a backend added to the root Compose network, use
`http://ollama:11434`. No external LLM API key is needed.

Start Ollama and persist downloaded model files in the named volume:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull <model-tag>
```

Set `OLLAMA_MODEL=<model-tag>` in the Flask backend environment and start the
Flask application using its existing run command. Ollama's model download is
an explicit one-time setup step; container startup does not download a model.
Compose publishes the Ollama HTTP port on loopback only (`127.0.0.1:11434`),
which lets this repository's host-run Flask backend connect without exposing
Ollama to the network. Do not change this to a public bind address. GPU support
depends on the host's Docker runtime and can be added with the appropriate
optional device reservation.

The client retries transient connection and server failures a bounded number
of times (`OLLAMA_RETRIES`, default 2), with a configurable per-request
timeout (`OLLAMA_TIMEOUT_SECONDS`, default 120). HTTP model-not-found errors,
invalid responses, and final connection failures are returned to the existing
chat handler as HTTP 500 errors. The API remains non-streaming as before.
