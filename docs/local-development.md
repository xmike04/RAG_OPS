# Local development

## Prerequisites

- Docker Engine or Docker Desktop with Compose v2
- GNU Make
- `curl`
- Python 3.12 for running backend tools outside containers
- Node.js 22 and npm for running the frontend outside containers

The supported end-to-end path is Docker Compose. Host Python and Node are useful
for shorter edit/test cycles but are not required for the default demo.

## Start the stack

```bash
cp .env.example .env
make up
make migrate
make seed
curl --fail http://localhost:8000/ready
```

The default configuration uses deterministic local embedding, reranking, and
generation providers. Leave production-provider variables unset unless you are
specifically testing that integration.

### Learned local retrieval models

The optional ML image installs Sentence Transformers for 384-dimensional
`all-MiniLM-L6-v2` embeddings and `ms-marco-MiniLM-L-6-v2` cross-encoder
reranking. Model weights are downloaded by the provider on first use, so this
profile needs outbound access to the model registry and a persistent model cache
in a long-running deployment.

```bash
RAGOPS_INSTALL_ML=true \
RAGOPS_EMBEDDING_PROVIDER=sentence-transformers \
RAGOPS_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
RAGOPS_RERANKER_PROVIDER=sentence-transformers \
RAGOPS_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2 \
make up
```

For a host development environment, install the same optional dependency with
`cd backend && uv sync --frozen --extra dev --extra ml`. Keep the local providers
for unit tests; evaluate learned models against a versioned relevance set before
promoting them.

Expected local services:

| Service | Default address | Purpose |
| --- | --- | --- |
| Web console | `http://localhost:3000` | Query and operations UI |
| API | `http://localhost:8000` | FastAPI application |
| API docs | `http://localhost:8000/docs` | OpenAPI browser |
| Prometheus (optional) | `http://localhost:9090` | Metrics query UI |
| Grafana (optional) | `http://localhost:3001` | Operational dashboards |

Treat the Compose file and `.env.example` as the source of truth if a port is
overridden.

Prometheus and Grafana are not part of the default profile. Start them when
working on telemetry or dashboards:

```bash
make up-observability
```

## Common development loops

Repository-wide commands:

```bash
make lint
make typecheck
make test
make build
make eval
```

Run the backend test suite or frontend test/build targets directly when changing
only one component; see each component's manifest for the exact tool invocation.
Run `make smoke` after API, persistence, worker, proxy, or Compose changes.

For a stricter read-only contract check against a running API, including OpenAPI
paths and request-ID propagation:

```bash
python tests/smoke_api.py --base-url http://localhost:8000
```

To inspect the stack:

```bash
docker compose ps
docker compose logs --tail=200 api worker
curl --fail http://localhost:8000/metrics
```

To stop it without removing data:

```bash
make down
```

Use the repository's explicit reset target, if present, only when losing local
database and queue state is acceptable.

## Configuration hygiene

- Keep `.env` local and commit only safe examples.
- Use separate database credentials for non-local environments.
- Do not put provider keys in Compose files, test fixtures, shell history, or
  frontend variables.
- Any `VITE_` variable is compiled into browser assets and must be public.
- Keep deterministic providers as the test default; production integrations
  should be opt-in.

## Troubleshooting

**`/health` passes but `/ready` fails.** The API process is alive but PostgreSQL
or Redis is unavailable, migrating, or misconfigured. Check `docker compose ps`,
then API and dependency logs. Do not route normal traffic until readiness passes.

**A submitted document is absent from search.** Poll its ingestion job. Check the
worker is running and inspect the safe error category. Acceptance is asynchronous
and does not mean chunks are committed.

**Database errors mention a missing vector type or relation.** Run migrations
after PostgreSQL is healthy. Confirm the image includes pgvector.

**The frontend cannot reach the API.** Check its configured public API base URL,
browser CORS errors, and API readiness. Remember that container-local
`localhost` differs from host `localhost`.

**Evaluation passes while live search looks weak.** The checked-in reference run
tests evaluator math, not backend quality. Export a fresh system run and evaluate
it according to [`evaluation.md`](evaluation.md).
