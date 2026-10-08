# Retrieval benchmarking and release evidence

This guide defines how RAGOps produces a reviewable retrieval benchmark. It is
separate from the checked-in evaluator fixture and from HTTP load testing.

## Evidence classes

Keep these labels on every result:

| Evidence | What ran | What it supports |
| --- | --- | --- |
| Evaluator fixture | `evals/runs/reference.jsonl` through `evals/evaluate.py` | Metric calculation, input validation, and deterministic CI behavior |
| Real-model retrieval benchmark | A versioned corpus and queries through named embedding/reranking models | Comparative retrieval quality and in-process stage latency on the recorded machine |
| Live API load test | Concurrent HTTP traffic through the deployed stack | End-to-end latency, throughput, and errors for that environment |

Fixture scores and fixture latency are not product performance. A real-model
result is publishable only when its raw run, configuration, environment, and
checksums are retained together.

## Dataset provenance

The initial real-model suite uses SciFact. The benchmark manifest must resolve,
not merely name:

- upstream project and canonical source URL;
- dataset configuration, split, and immutable revision or snapshot date;
- license and any redistribution restrictions;
- corpus, query, and relevance-label counts read from that snapshot;
- SHA-256 checksums of normalized corpus, queries, and labels;
- normalization, exclusions, deduplication, and ID mapping performed locally.

SciFact is a scientific-claim retrieval dataset, so it represents short English
claims over research abstracts. It does not represent RAGOps operational
documents, long-form enterprise content, multilingual search, access-control
filters, or conversational follow-ups. Do not generalize its aggregate score to
those workloads.

The checked-in [dataset manifest](../benchmarks/retrieval/dataset_manifest.json)
pins the upstream SciFact revision and prepared-file checksums. Dataset and model
license notes are in [ATTRIBUTION.md](../benchmarks/retrieval/ATTRIBUTION.md).

## Reproduce a real-model run

Install the benchmark's own locked environment, prepare the verified dataset,
then run the benchmark:

```bash
cd benchmarks/retrieval
uv sync --frozen
uv run --frozen ragops-retrieval-prepare
uv run --frozen ragops-retrieval-benchmark \
  --hardware-note '<machine/CPU/RAM>'
```

The runner derives `run-id` from the dataset, benchmark configuration, and
recorded environment, then writes `results/scifact/<run-id>`. It refuses to mix
an incompatible configuration into that directory and resumes matching partial
results. Execute from a quiet machine after model weights are available;
setup/download time is excluded from query latency and recorded separately.

The collector writes:

```text
benchmarks/retrieval/results/scifact/<run-id>/
├── run_config.json
├── per_query.jsonl
├── summary.json
└── report.md
```

- `run_config.json` contains resolved dataset/model revisions, retrieval
  settings, seed, software versions, device/dtype, and host details.
- `per_query.jsonl` retains relevance labels, ranked IDs/scores, per-method
  metrics, and stage/total latency for audit and paired comparison.
- `summary.json` contains corpus/query counts, aggregate Recall/MRR/nDCG@10,
  latency p50/p95 by method, and artifact checksums.
- `report.md` is a rendering of the machine-readable artifacts, not an
  independent source of numbers.

Score a compatible exported run with the repository evaluator when a second
calculation is useful:

```bash
python evals/evaluate.py \
  --queries evals/datasets/queries.jsonl \
  --corpus evals/datasets/corpus.jsonl \
  --run artifacts/backend-run.jsonl \
  --k 1,3,5,10 \
  --output artifacts/backend-metrics.json
```

That command applies only when IDs and JSONL fields follow the evaluator
contract. It does not convert SciFact artifacts automatically.

## Configuration that must be captured

Record these fields before interpreting a comparison:

- exact git revision and dirty-worktree state;
- Python, PyTorch, Sentence Transformers, database, and pgvector versions;
- CPU model/count, RAM, GPU model/driver/runtime if used, device, and dtype;
- embedding provider, exact model ID and immutable revision, dimension,
  normalization, similarity function, and batch size;
- lexical tokenizer/configuration and BM25 or full-text parameters;
- lexical/vector candidate depths, RRF constant, tie-breaking, and final `top_k`;
- reranker model/revision, shortlist depth, and batch size;
- warmup count, excluded setup phases, random seed, and concurrency;
- dataset manifest and artifact SHA-256s.

Comparisons are valid only when dataset labels and measurement semantics match.
If hardware or model revisions differ, describe the comparison as directional,
not controlled.

## Results placeholder

Until a retained run exists, this document makes no real-model quality or
latency claim. Root release preparation replaces the nulls below from one
reviewed `summary.json`; no values should be typed from memory.

```json
{
  "status": "pending_measurement",
  "artifact": "benchmarks/retrieval/results/scifact/<run-id>/summary.json",
  "run_id": null,
  "git_revision": null,
  "dataset_revision": null,
  "model_revisions": null,
  "hardware_fingerprint": null,
  "measured_results": null
}
```

## Release interpretation

Review aggregate and per-query results. Report failures/timeouts in the
denominator and inspect query slices; do not accept an average improvement that
hides a material regression in exact identifiers, paraphrases, or multi-evidence
queries. Use a held-out set for the release claim if the configuration was tuned
on the same dataset.

Real-model benchmark latency is useful for relative model selection on the
recorded host. It is not an API service-level objective: it excludes network,
serialization, queueing, database contention, and concurrent tenants. Pair it
with [`load-testing.md`](load-testing.md) before making a production capacity
decision. The lexical faithfulness proxy remains regression evidence, not proof
that generated claims are entailed.
