# RAGOps architecture

## Product goal

RAGOps is an observable, multi-workspace RAG platform that makes retrieval
quality and operational cost inspectable. It ingests text and Markdown, chunks
and embeds content, performs lexical and vector candidate generation, fuses the
rankings, reranks the shortlist, and produces grounded answers with citations.

## Runtime topology

```mermaid
flowchart TD
  U[Operator / API client] --> W[React console]
  U --> A[FastAPI API]
  W --> A
  A --> P[(PostgreSQL + pgvector)]
  A --> R[(Redis)]
  A --> L[LLM provider]
  R --> Q[Ingestion worker]
  A --> E[Embedding provider]
  A --> X[Reranking provider]
  Q --> E
  Q --> P
  M[Prometheus] -->|scrape /metrics| A
  G[Grafana] -->|query| M
```

The API is the only public application boundary. PostgreSQL is authoritative for
documents, chunks, jobs, and query traces. Redis carries the transient ingestion
queue; the current search path does not implement a result cache. The worker is horizontally
scalable only when job claim and document finalization remain idempotent.

The checked-in Prometheus configuration scrapes the API's `/metrics` endpoint.
The separate worker process has no metrics HTTP server; collecting its counters
would require a worker exporter or explicit multiprocess configuration.

## Stable API contract

All JSON endpoints live below `/v1` and return a request ID header.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/documents` | Submit a document and create an ingestion job |
| `GET` | `/v1/documents` | List documents in a workspace |
| `GET` | `/v1/ingestions/{job_id}` | Inspect ingestion progress or failure |
| `POST` | `/v1/search` | Run hybrid retrieval and optional reranking |
| `POST` | `/v1/query` | Generate a grounded, cited answer |
| `GET` | `/v1/traces` | Inspect recent query traces and stage timing |
| `GET` | `/v1/ops/summary` | Aggregate latency, tokens, cache, and quality data |
| `GET` | `/health` | Liveness check |
| `GET` | `/ready` | PostgreSQL and Redis readiness check |
| `GET` | `/metrics` | Prometheus exposition endpoint |

## Retrieval contract

Lexical and vector retrievers return ranked candidates with stable chunk IDs and
raw component scores. Reciprocal-rank fusion uses `1 / (k + rank)` and records
the contribution of each retriever. A reranker receives only the fused shortlist
and returns a normalized score plus provider/model metadata. Search responses and
query traces expose stage latency without leaking document contents into logs.

The serving lexical query uses PostgreSQL `plainto_tsquery` and `ts_rank_cd`
cover-density ranking. The standalone SciFact experiment uses
`rank_bm25.BM25Okapi`. They are different retrieval implementations; the
offline BM25/RRF scores are not quality measurements of this PostgreSQL API.
See [PostgreSQL's ranking documentation](https://www.postgresql.org/docs/16/textsearch-controls.html#TEXTSEARCH-RANKING).

## Provider contract

Provider selection is configuration-driven. These are the implementations wired
by `build_search_service` and `build_generator`, rather than every adapter exported
from the providers package:

| Stage | Default, deterministic local path | Optional path |
| --- | --- | --- |
| Embedding | `HashEmbeddingProvider`: hash-based vectors, no learned semantics | `SentenceTransformersEmbeddingProvider`: learned model running in the API/worker process |
| Reranking | `LexicalRerankingProvider`: token-overlap fixture | `SentenceTransformersCrossEncoderProvider`: learned cross-encoder in the API process |
| Generation | `LocalGroundedGenerator`: extracts passages and adds numbered references | `OpenAICompatibleGenerator`: sends the query and retrieved passages to the configured remote endpoint |

Local learned models still require model downloads or pre-provisioned model
artifacts; they do not require a hosted inference API key. Remote generation
requires endpoint credentials and can incur provider charges. The exported
OpenAI-compatible embedding adapter is not selected by the current search factory.

## Request flows

### Ingestion

```mermaid
sequenceDiagram
  participant C as Client
  participant A as API
  participant R as Redis
  participant W as Worker
  participant P as PostgreSQL
  participant E as Embedding provider
  C->>A: POST /v1/documents
  A->>P: create document + pending job
  A->>R: enqueue job ID
  A-->>C: 202 document_id, job_id
  R->>W: claim job
  W->>P: mark running
  W->>E: embed deterministic chunks
  W->>P: transactionally replace chunks, mark succeeded
```

The request accepts content but does not promise immediate searchability. Clients
poll the ingestion resource. A retry may repeat processing, so chunk identity and
final persistence must be deterministic or transactionally replaced.

### Search and answer generation

```mermaid
sequenceDiagram
  participant C as Client
  participant A as API
  participant P as PostgreSQL
  participant E as Embedder
  participant X as Reranker
  participant L as Generator
  C->>A: POST /v1/query
  A->>E: embed query
  E-->>A: query vector
  A->>P: lexical search using ts_rank_cd
  P-->>A: lexical candidates
  A->>P: pgvector similarity search
  P-->>A: vector candidates
  A->>A: reciprocal-rank fusion
  opt rerank enabled and candidates present
    A->>X: fused shortlist
    X-->>A: rerank scores
  end
  A->>L: query + selected chunks
  L-->>A: answer + citations
  A->>P: persist trace metadata
  A-->>C: answer, sources, trace_id
```

`/v1/search` ends after ranking. `/v1/query` continues through generation. Both
flows use the same retrieval stages so the search view can explain the context
chosen for an answer.

Embedding, lexical retrieval, vector retrieval, fusion, and optional reranking
run in that order in `SearchService.search`. The two database operations are
awaited sequentially because they share one SQLAlchemy `AsyncSession`.
[SQLAlchemy requires a separate session per concurrent task](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks);
parallel retrieval would require an explicit session/transaction design change.

## Data ownership and isolation

Every document, chunk, ingestion job, and trace belongs to one workspace.
Workspace filtering is part of each database query, not a post-processing step.
Public IDs are UUIDs and do not encode tenant or database ordering. A future
authorization adapter must derive workspace identity from a principal; the local
demo accepts an explicit workspace identifier in requests and therefore is not an
internet-safe multi-tenant boundary.

Document text is stored in PostgreSQL and sent only to the configured embedding
or generation provider. Logs and metrics contain identifiers, sizes, states,
timings, and provider metadata—not raw document text or generated answers.
Query traces currently retain the user's query and generated answer for operator
inspection; treat the trace store and API as sensitive data surfaces.

## Consistency and failure behavior

| Event | Contract |
| --- | --- |
| API accepts a document | Document and pending job exist before work is queued |
| Queue delivery repeats | Processing is idempotent; one final chunk set is visible |
| Provider call fails | Job records a safe error category and can be retried |
| Redis is unavailable | Readiness fails; accepted work is never reported as complete |
| PostgreSQL is unavailable | Readiness fails and state-changing operations reject |
| Reranker is unavailable | Its exception propagates; no configurable fail-open policy is implemented |
| Generator returns invalid citation markers | Sources are constructed from retrieved hits, but generated `[n]` markers are not parsed or validated; semantic grounding is not established |

The liveness endpoint reports that the process can serve requests. Readiness is
stricter and represents dependencies needed for normal traffic. Neither endpoint
should call an external model provider on every probe.

## Observability model

An inbound `X-Request-ID` is validated and propagated, or a new request ID is
created. Query traces record coarse request metadata and stage timings:
embedding, lexical retrieval, vector retrieval, fusion, reranking, and generation.
Trace records include query/answer text but do not duplicate full retrieved
documents. Metrics use bounded labels such as route, status class, and provider; workspace,
document, query, and request IDs remain in structured logs or trace records to
avoid unbounded Prometheus cardinality.

The system intentionally separates three signals:

- health: whether components can accept work;
- performance: latency, queue depth, error rates, tokens, and cache behavior;
- quality: offline relevance and citation metrics from a versioned evaluation.

Runtime telemetry cannot establish retrieval quality by itself.

`QueryService` currently writes `estimated_cost_usd=0` and defaults `cache_hit`
to false. These are telemetry placeholders, not measured zero-cost inference or
evidence of cache effectiveness. Provider billing, process RSS/CPU, and worker
metrics need separately collected evidence.

## Configuration boundaries

Provider selection and connection details come from environment variables.
Configuration is validated before the process reports ready. Development
defaults use deterministic providers and local services. Production deployments
must provide authentication, TLS termination, secret management, resource
limits, database backup, and an explicit provider data-processing policy.

## Intentional constraints

- Text and Markdown are the initial ingestion formats; binary parsing and OCR are
  outside the core service.
- PostgreSQL full-text search and pgvector favor operational simplicity over
  independently scalable search clusters.
- RRF combines rank positions rather than attempting to calibrate unrelated
  lexical and vector score distributions.
- Query traces retain query/answer text for inspection but avoid full prompt and
  retrieved-document replay; deployments need access control and retention.

See the [retrieval guide](retrieval.md) for ranking details, the
[operations runbook](operations.md) for service diagnosis, and the
[security model](security.md) for production gaps.
