# Controlled mixed-query serving load — October 26, 2026

The real FastAPI/PostgreSQL/Redis service indexed **5,183 SciFact documents into
5,887 chunks**. This study measures matching local hash providers, a varied
training-query workload, three concurrency levels, and process-first-search
observations. It does not call a hosted model or generate answers.

[Collection run](https://github.com/xmike04/RAG_OPS/actions/runs/40389341425) ·
[Measured application and harness source](https://github.com/xmike04/RAG_OPS/commit/fa5b6fae567d3863eb26af68bd908fc4c8c8f383) ·
[Harness methodology](https://github.com/xmike04/RAG_OPS/blob/fa5b6fae567d3863eb26af68bd908fc4c8c8f383/benchmarks/service/LOAD_MATRIX.md)

## Warm mixed-query conditions

Thirty training-query IDs were sampled with seed 0 and issued round-robin,
ten times each. The same query order was used at concurrency 1, 4, then 8.
Each condition had 30 separate warmups, with no warmup failures. Each measured
condition completed all 300 requests with nonempty search responses and matching
provider metadata.

| Concurrency | Measured requests | Failures | p50 ms | p95 ms | p99 ms | Successful requests/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 300 | 0 | 51.46 | 54.73 | 92.68 | 18.98 |
| 4 | 300 | 0 | 97.61 | 137.22 | 150.81 | 39.34 |
| 8 | 300 | 0 | 163.42 | 252.24 | 317.69 | 47.13 |

This single run illustrates a throughput/latency trade-off. Concurrency 8
completed about 2.48 times as many requests per second as concurrency 1, while
its p95 rose from 54.73 ms to 252.24 ms. Conditions were not randomized and there
was one collection per condition; this is descriptive evidence, not a statistically
established concurrency effect or production sizing recommendation.

These are closed-loop worker threads. Request latency includes the HTTP/JSON
operation and excludes waiting in the client's executor queue. Throughput uses
the complete measured request window. Each request uses urllib without an
explicit connection pool. There is no open-loop arrival-rate/capacity or SLO claim.
Stage timings are retained separately and their percentiles are not additive.

## Process-first-search observations

Every row had an observed available API PID before the request, a zero search
counter, continuous PID/start ticks through the measurement, and a counter of one
afterward. The five API identities were distinct.

| Seed | Process state | One observed HTTP request, ms | Search counter |
| --- | --- | ---: | --- |
| 0 | Initial API after ingestion | 84.75 | 0 → 1 |
| 1 | Restarted API | 123.65 | 0 → 1 |
| 2 | Restarted API | 125.10 | 0 → 1 |
| 3 | Restarted API | 120.22 | 0 → 1 |
| 4 | Restarted API | 122.14 | 0 → 1 |

Seed 0's API had already served ingestion. The other four observations followed
API process restarts. Readiness was established before each search; PostgreSQL,
Redis, and OS caches were retained. These are five individual observations with
different seeded training queries, not host/database cold starts, a paired
cold-penalty estimate, or enough samples for a credible cold-tail percentile.

The initial collection
[40387499975](https://github.com/xmike04/RAG_OPS/actions/runs/40387499975) was rejected:
the old parser expected the prefixed route label, while locked FastAPI 0.143
emits `route="/search"`. A direct integration test reproduced the mismatch;
the corrected parser is also checked against real HTTP requests. The rejected
raw collection remains in the adjacent `2026-10-26-invalid-40387499975` directory.
It was not silently relabeled as valid or selected for faster timings.

## Process resources

CPU is the process tick delta over each measured request window. Percent CPU
uses one core as 100%. RSS is observed at two endpoints, includes potentially
shared pages, and is not a peak-memory measurement.

| Concurrency | API CPU seconds | API mean CPU, one core | API RSS MiB, start → end | Worker CPU seconds | Worker RSS MiB, start → end |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.77 | 17.53% | 94.14 → 94.14 | 0.00 | 89.02 → 89.02 |
| 4 | 3.03 | 39.73% | 94.14 → 94.14 | 0.00 | 89.02 → 89.02 |
| 8 | 3.76 | 59.07% | 94.14 → 95.02 | 0.00 | 89.02 → 89.02 |

The worker was idle after ingestion; its zero observed CPU ticks in these short
search windows do not describe ingestion cost. These API/worker measurements
exclude PostgreSQL, Redis, the load generator, and other host work. Stable RSS
endpoints do not prove absence of leaks or establish a memory limit.

The captured chunks table **and all its indexes together** occupied
47,177,728 bytes globally at snapshot time. This is not isolated index size or
per-request memory. Actual GIN/HNSW index definitions are retained; their existence
does not prove an individual request's query plan.

## Frozen conditions and scope

- Source: `fa5b6fae567d3863eb26af68bd908fc4c8c8f383`, tracked source clean.
- Harness file SHA-256: `1bcd79312744e6ea0045f2d252309d9fd2cf049cacb0b80f05cb8980f2fd6183`.
- Query/document embeddings: `feature-hash-384`, 384 dimensions; no learned inference.
- Chunking: RegexTokenizer, max 384 tokens, overlap 64.
- PostgreSQL cover-density lexical ranking plus pgvector, sequential queries,
  RRF k=60, candidate cap 100 per source, returned top 100 chunks, rerank false.
- Four visible logical CPUs on Linux 6.17.0-1022-azure; Python 3.12.15,
  PostgreSQL 16.15, pgvector 0.8.7, FastAPI 0.143.0, Starlette 1.7.0.
- Host-visible `/proc/meminfo` is retained. CPU/memory cgroup limits were unavailable;
  no exclusive CPU allocation or container memory ceiling is inferred.
- All conditions used training queries. The held-out quality evaluation was not rerun.

The separate serving quality report and the historical repeated-query HTTP run
use different workloads/conditions. Timing differences between them are not a
measured regression or improvement. No parameter tuning followed this collection.

Provider billing, total infrastructure cost, cost per answer, generation quality
or latency, ingestion retry/failure rates, peak RSS, database/Redis CPU, effective
query plans, and production reliability were not measured. Missing metrics are
not zero. Observing zero errors here is not a future failure-rate guarantee.

## Inspect and reproduce

`summary.json` contains unrounded metrics. Each `.gz` preserves an original output;
`environment.json` records package/lock information and SHA-256 of every
uncompressed file. The raw conditions retain all request outcomes, warmup errors,
query IDs, timestamps, configuration/runtime snapshots, and process samples.
The repository artifact checks recompute counts, latency percentiles, CPU deltas,
and first-search validity from those raw outputs.

The checked-in manual-only `.github/workflows/load-evidence.yml` pins the measured
source and builds a fresh corpus. It runs without live provider credentials.
Future workflow artifacts expire after 30 days and must be retained before citing
them. The temporary branch artifact publisher has been removed.
[SciFact attribution and licenses](https://github.com/xmike04/RAG_OPS/blob/fa5b6fae567d3863eb26af68bd908fc4c8c8f383/benchmarks/datasets/scifact/LICENSES.md)
apply.
