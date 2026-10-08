# Retrieval evaluation

This directory contains a deterministic, dependency-free evaluator. It scores a
saved run; it does not invoke the API or a model provider.

```bash
python evals/evaluate.py \
  --queries evals/datasets/queries.jsonl \
  --corpus evals/datasets/corpus.jsonl \
  --run evals/runs/reference.jsonl \
  --k 1,3,5
```

The checked-in reference run is deliberately imperfect so metric regressions are
visible. It is a fixture for testing evaluator math, not a backend benchmark.

## Input contracts

Each corpus JSONL row contains:

```json
{"chunk_id":"chunk-a","document_id":"doc-a","title":"Optional","text":"Evidence text"}
```

Each query row contains at least one binary relevance label:

```json
{"query_id":"q-a","query":"Question?","relevant_chunk_ids":["chunk-a"],"tags":["optional"]}
```

Each run row contains an ordered result list and non-negative end-to-end latency:

```json
{
  "query_id": "q-a",
  "latency_ms": 12.4,
  "results": [{"chunk_id": "chunk-a", "score": 0.9}],
  "answer": {
    "claims": [
      {"text": "A supported claim.", "citations": ["chunk-a"]}
    ]
  }
}
```

`score` is retained for diagnostics but does not enter rank-based metrics. The
answer is optional. Citation IDs that are absent from retrieved results count as
invalid and provide no evidence to the faithfulness proxy.

The query and run files must contain the same unique query IDs. Relevant and
result chunks must exist in the corpus. Invalid artifacts fail with exit code 2.

## Quality gates

Repeat `--fail-below` to enforce numeric floors:

```bash
python evals/evaluate.py \
  --queries evals/datasets/queries.jsonl \
  --corpus evals/datasets/corpus.jsonl \
  --run path/to/candidate.jsonl \
  --fail-below retrieval.recall@5=0.85 \
  --fail-below citations.coverage=0.90
```

The command exits 1 for a missed floor, 2 for invalid input, and 0 otherwise.
Use `--output artifacts/evaluation.json` to retain the report. Release thresholds
belong with measured baseline evidence, not this evaluator fixture.

See [`docs/evaluation.md`](../docs/evaluation.md) for metric definitions,
annotation guidance, and the live-backend protocol.
