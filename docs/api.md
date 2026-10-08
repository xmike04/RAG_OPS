# API usage

## Conventions

Application JSON endpoints are rooted at `/v1`. Health and metrics endpoints are
root-level. Examples assume `http://localhost:8000` and the seeded workspace:

```text
00000000-0000-0000-0000-000000000001
```

Workspace identity is an explicit request-body or query parameter in the current
development API. This is scoping, not authentication. Production deployments
must ignore untrusted client scope and bind workspace identity to an
authenticated principal at a trusted boundary.

Responses carry `X-Request-ID`. Clients may send the header themselves using a
safe opaque value and should include it in support reports. JSON timestamps are
UTC ISO 8601 values. Public resource IDs are UUIDs.

When `RAGOPS_API_KEY` is configured, every `/v1` request must also send
`X-API-Key`. Health, readiness, metrics, and OpenAPI remain outside that API-key
dependency. A shared API key is suitable for a protected integration boundary,
not user identity or workspace authorization.

## Health and readiness

```bash
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/ready
curl --fail http://localhost:8000/metrics
```

Liveness means the process can respond. Readiness includes required database and
queue dependencies and is the correct signal for traffic routing.

## Submit and inspect a document

```bash
curl --fail-with-body http://localhost:8000/v1/documents \
  -H 'Content-Type: application/json' \
  -d '{
    "workspace_id": "00000000-0000-0000-0000-000000000001",
    "title": "RRF notes",
    "source_uri": "local://rrf-notes",
    "metadata": {"format": "text/markdown"},
    "content": "# Fusion\nRRF adds 1 / (k + rank) for each ranked list."
  }'
```

The accepted response contains document and ingestion-job identifiers. Poll the
job until it reaches a terminal state:

```bash
curl --fail-with-body \
  'http://localhost:8000/v1/ingestions/JOB_ID?workspace_id=00000000-0000-0000-0000-000000000001'
```

Treat `succeeded` and `failed` as terminal. Use bounded exponential backoff and a
client timeout; do not poll in a tight loop.

## Search

```bash
curl --fail-with-body http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: example-search-001' \
  -d '{
    "workspace_id":"00000000-0000-0000-0000-000000000001",
    "query":"How does RRF work?",
    "top_k":5,
    "rerank":true
  }'
```

Search results identify their document and chunk and expose enough rank metadata
to explain retrieval. Component scores are meaningful within their own stage;
do not compare a raw lexical score directly with vector similarity.

## Generate a grounded answer

```bash
curl --fail-with-body http://localhost:8000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{
    "workspace_id":"00000000-0000-0000-0000-000000000001",
    "query":"Why use reciprocal-rank fusion?",
    "top_k":5
  }'
```

The response contains an answer, cited source chunks, and a trace identifier.
Citations are identifiers, not proof of entailment; consumers should render the
supporting excerpt and keep a path back to the source document.

## Operations and traces

```bash
curl --fail-with-body \
  'http://localhost:8000/v1/traces?workspace_id=00000000-0000-0000-0000-000000000001&limit=20'

curl --fail-with-body \
  'http://localhost:8000/v1/ops/summary?workspace_id=00000000-0000-0000-0000-000000000001'
```

Trace payloads expose stage timing, model/provider metadata, the user query, and
the generated answer. They do not duplicate full retrieved documents. Restrict
trace access and apply retention appropriate to potentially sensitive text.

## Errors and retries

Clients should handle these classes distinctly:

| Status | Meaning | Client behavior |
| --- | --- | --- |
| `400` / `422` | Invalid request | Correct the request; do not retry unchanged |
| `404` | Resource absent in workspace | Verify ID and workspace |
| `409` | State or idempotency conflict | Re-read resource state |
| `429` | Capacity or rate limit | Retry after the indicated delay with jitter |
| `500` | Unhandled server failure | Record request ID; retry only if operation is safe |
| `503` | Dependency unavailable/not ready | Back off and retry after readiness recovers |

Do not assume a timed-out state-changing request failed. Look up the returned
resource or use an idempotency mechanism when the endpoint supports one. The
running service's `/openapi.json` is authoritative for exact request and response
fields.
