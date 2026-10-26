# SciFact serving-path baseline — October 26, 2026

This run ingested **5,183 canonical SciFact documents into 5,887 chunks** and
exercised the actual FastAPI, PostgreSQL, pgvector, and worker path. It used
matching deterministic hash embeddings, PostgreSQL cover-density lexical ranking,
RRF k=60, and no reranking or generation.

[Collection run](https://github.com/xmike04/RAG_OPS/actions/runs/40380993127) ·
[Artifact and qrel validation](https://github.com/xmike04/RAG_OPS/actions/runs/40382526181) ·
[Measured source](https://github.com/xmike04/RAG_OPS/commit/6a07b41aadbb326eee7c9031a15923246103c2f7)

## Retrieval quality

| Split | Queries | Recall@10 | Recall@100 | MRR@10 | nDCG@10 | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Train | 809 | 0.4428 | 0.6376 | 0.3254 | 0.3486 | 0 |
| Held-out test | 300 | 0.4097 | 0.6211 | 0.2881 | 0.3134 | 0 |

Chunk hits are mapped to original SciFact IDs, then deduplicated by first document
occurrence before scoring. The request returns at most **100 chunks**, which
produced 90–100 unique documents on test queries (median 98). Recall@100 therefore
describes that returned document window, not an unrestricted 100-document search.
All query IDs and scores were independently recomputed against the official
qrels in the artifact-validation CI check. Both final train and test outputs are
retained; no parameter tuning followed held-out observation.

## Serial HTTP latency

| Split | Successful requests | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: |
| Train | 809 | 21.90 ms | 25.01 ms | 37.11 ms |
| Held-out test | 300 | 20.70 ms | 23.76 ms | 41.40 ms |

The held-out run followed the train run in the same API/database processes.
These are serial request measurements, with HTTP/JSON overhead included.
They do not characterize load capacity or host/database cold starts.
Server stage timings are retained separately; latency percentiles are not additive.

## Recorded conditions

- Query and document vectors: `feature-hash-384`, 384 dimensions.
- Chunking: `RegexTokenizer`, max 384 tokens, overlap 64.
- Each source may supply 100 candidates; request `top_k=100`, `rerank=false`.
- Four visible logical CPUs, Python 3.12.15, PostgreSQL 16.15, pgvector 0.8.7.
- Captured chunks table and indexes: 48,128,000 bytes globally.
- Loaded source hashes, package versions, lockfile hash, actual index definitions,
  dataset hashes, application/source-document mappings, and per-query rows are retained.

The earlier **0.8059 Recall@10** belongs to the separate offline Okapi BM25/MiniLM
experiment. It is not this service's quality. The configurations differ in lexical
ranking, embeddings, chunking, and candidate windows; this comparison does not
identify a single cause for the gap. The worker's learned-provider configuration
mismatch remains a separately documented limitation.

Generation, grounded-answer quality, mixed-query concurrency/cold-state workloads,
process CPU/RSS, provider billing, effective query plans, and database runtime
override parameters were not measured. No production SLO or dollar cost is claimed.

## Inspect and reproduce

`summary.json` contains unrounded metrics. Each `.gz` file preserves the exact
original harness output; `environment.json` hashes its uncompressed bytes.
For example, from this directory:

```bash
python3 -c "import gzip,json; print(json.dumps(json.load(gzip.open('test/evaluation.json.gz'))['summary'], indent=2))"
```

Follow the [frozen harness protocol](https://github.com/xmike04/RAG_OPS/blob/6a07b41aadbb326eee7c9031a15923246103c2f7/benchmarks/service/README.md).
The manual evidence workflow keeps this source/configuration reproducible.
Workflow artifacts expire; retain reviewed public outputs before citing a future run.
[SciFact dataset licenses](https://github.com/xmike04/RAG_OPS/blob/6a07b41aadbb326eee7c9031a15923246103c2f7/benchmarks/datasets/scifact/LICENSES.md) apply.
