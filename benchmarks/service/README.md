# Serving-path evaluation

This harness ingests the canonical SciFact corpus through `POST /v1/documents`,
waits for ingestion, and measures the actual HTTP `/v1/search` path. It is separate
from the offline Okapi BM25 experiment and never calls generation or paid inference.
**No application-level result is claimed merely because the harness tests pass.**

## Preconditions and a discovered blocker

The default worker in `ragops.main.create_ingestion_worker` always constructs
`HashEmbeddingProvider`. Selecting `sentence-transformers` in the API therefore
does not configure the worker to produce matching document embeddings. Preflight
rejects that mismatch. Fix and test provider selection in a separate runtime
change before attempting a learned-model service comparison. The initial frozen
protocol measures the matching deterministic local path only.

The API returns at most 100 **chunks**, not 100 unique documents. Results retain
every chunk-to-source mapping, deduplicate by original document ID, and report
Recall@100 over that returned window. This may contain fewer than 100 documents;
it is not equivalent to a full-corpus document-ranking experiment. The application
defaults to a 40-candidate limit, so the frozen 100-chunk protocol requires an
explicit candidate-limit configuration of 100 before starting the local stack.

## Reproduce

Use a fresh checkout and a local Docker Compose stack. Do not expose it publicly.
Set `RAGOPS_RETRIEVAL_CANDIDATE_LIMIT=100` in the ignored `.env` before building
and starting the stack. Leave embedding and reranker providers `local` and
generation `local`. Run `make up` and `make migrate`; the harness uses its own
empty workspace, so `make seed` is unnecessary.

Run from the repository root:

```bash
python3 -m benchmarks.service.run ingest --output-dir benchmarks/service/results/run-001
```

Retain the printed workspace UUID. Capture settings, actual factory provider
choices, loaded source hashes, chunk configuration, PostgreSQL/pgvector versions,
index definitions, and corpus/chunk counts **inside the API container**:

```bash
docker compose cp benchmarks/service/capture.py api:/tmp/ragops-service-capture.py
docker compose exec -T api python /tmp/ragops-service-capture.py \
  --workspace-id <printed-workspace-uuid> \
  --source-revision <full-source-commit-sha> \
  > benchmarks/service/results/run-001/runtime.json

python3 -m benchmarks.service.run evaluate \
  --output-dir benchmarks/service/results/run-001 \
  --runtime benchmarks/service/results/run-001/runtime.json
```

The default split is **train** (809 queries). Freeze and commit `protocol.json`
before final evaluation. Then run once with `--split test --final-test` for the
300 held-out queries. Do not select settings after observing test results. Keep
every final attempt, including failures. Output directories are never overwritten.

For a paired comparison, pass `--baseline path/to/prior/evaluation.json`. The
dataset fingerprint, split, and query IDs must match. The report includes per-query
differences and a seeded 2,000-sample paired-bootstrap interval for Recall@10 and
nDCG@10. This interval does not correct for multiple comparisons and is not a
blanket significance claim.

## Evidence contract

- `ingestion-submissions.jsonl`: accepted job, application-document, and SciFact IDs.
- `ingest.json`: completed corpus mapping, input checksums, and frozen protocol hash.
- `runtime.json`: sanitized runtime snapshot; no connection strings or keys.
- `<split>/per_query.jsonl`: raw ranked source mappings, metrics, HTTP/stage timings,
  provider metadata, and sanitized failure categories.
- `<split>/evaluation.json`: configuration/provenance, all-query macro quality,
  successful-request latency percentiles, errors, and optional paired analysis.

Failures count as zero relevance in the all-query denominator and make the CLI
exit nonzero. Unknown source mappings, corpus deduplication, incomplete ingestion,
provider drift, and checksum mismatches cannot silently produce a valid baseline.
Latency excludes ingestion, includes a first request and subsequent requests, and
does not characterize concurrency or cold starts. It excludes generation.
Cost and process resource samples remain **not measured**. Runtime source revision
attribution is operator-supplied; loaded source hashes support subsequent checking.
The capture is an equivalent factory snapshot in the container, not a live-process
introspection API. Record the API/worker image IDs with any published run.

The original dataset licenses still apply; see
[SciFact attribution](../datasets/scifact/LICENSES.md).

## Checks

```bash
python3 -m unittest discover -s tests -p 'test_service*.py' -v
make cross-test
```

Scoring/attribution/protocol tests are dependency-free. Full stack ingestion and
capture require PostgreSQL, Redis, and the backend's locked runtime. A passing
mocked client test is not a measured service run.

Every successful evaluation response must match the captured embedding provider/model; enabled reranking must match the captured reranker as well. Consistent but different responses are retained as `ProviderMismatchError` failures, and the run exits nonzero. Truncated HTTP/protocol responses are sanitized failed-query records so later queries still run. Non-exposed settings and image/source correspondence still require the documented operator checks; response metadata alone does not prove those settings.
