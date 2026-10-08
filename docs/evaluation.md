# Evaluation methodology

## What is measured

The offline harness joins a versioned corpus, labeled query set, and saved system
run by stable IDs. It never needs a database, API, external model, or secret.

| Metric | Definition | Main limitation |
| --- | --- | --- |
| Recall@k | Relevant chunks in the first k results / all labeled relevant chunks | Missing labels make results look worse or better |
| MRR | Mean reciprocal rank of the first relevant chunk in the full saved list | Ignores additional relevant results |
| nDCG@k | Binary discounted cumulative gain normalized by the ideal list | Binary labels do not capture degree of usefulness |
| Citation coverage | Claims with one or more citations / all answer claims | A present citation may still be wrong |
| Citation validity | Citations resolving to a retrieved corpus chunk / all citations | Valid IDs do not establish support |
| Faithfulness proxy | Per-claim fraction of non-stopword claim tokens present in valid cited chunks | Lexical overlap cannot prove entailment and penalizes paraphrase |
| Latency | Count and nearest-rank p50/p95/max of saved end-to-end milliseconds | Fixture latency is meaningful only if exported from a real run |

Metrics are macro-averaged by query, so a query with many relevance labels does
not dominate Recall or nDCG. The proxy gives uncited claims zero support.

## Dataset and annotation

The bundled dataset is small and transparent. It exercises exact terms,
paraphrases, multi-evidence questions, security, storage, and operations. It is
for harness regression, not a representative product benchmark.

For a real baseline:

1. Sample questions from the intended workload without copying sensitive text
   into the repository.
2. Define the corpus snapshot and chunking version first.
3. Have reviewers label every chunk that independently or jointly answers each
   query; adjudicate disagreements.
4. Tag query slices such as identifier, paraphrase, temporal, multi-evidence,
   negative/unanswerable, language, and access-control scope.
5. Freeze a test split. Use a separate development split for tuning.
6. Record dataset provenance, annotator guidance, exclusions, and known gaps.

Unanswerable queries need a separate abstention metric and should not be encoded
as a fake relevant chunk.

## Run protocol

Record all inputs that can change ranking or latency:

- git revision and UTC timestamp;
- corpus/query dataset checksums and chunking version;
- embedding/reranking provider and model revisions;
- lexical/vector candidate depths, RRF constant, rerank depth, final `top_k`;
- database/index state and warm/cold-cache policy;
- host/container resources and concurrency;
- failures, retries, and timeouts.

Run the full query set through the same API path users exercise. Preserve ordered
chunk IDs, final scores, claim citations, and end-to-end latency as JSONL. Do not
silently drop timeouts or failed queries; represent and report them separately,
then decide whether the quality evaluator should fail the incomplete run.

Evaluate with:

```bash
python evals/evaluate.py \
  --queries evals/datasets/queries.jsonl \
  --corpus evals/datasets/corpus.jsonl \
  --run artifacts/backend-run.jsonl \
  --k 1,3,5,10 \
  --output artifacts/backend-metrics.json
```

Inspect per-query results and slices before accepting an aggregate improvement.
A statistically sound comparison on a larger set should use paired resampling or
bootstrap confidence intervals; this small harness intentionally reports the
observable sample without implying population significance.

## Results status

### Measured: evaluator reference fixture

The following values are produced by the checked-in static run on the bundled
eight-query fixture (verified with the command above). They test calculations;
the latency values are synthetic fixture fields and have no performance meaning.

| Metric | Fixture value |
| --- | ---: |
| Recall@1 | 0.5625 |
| Recall@3 / Recall@5 | 1.0000 |
| MRR | 0.8125 |
| nDCG@3 / nDCG@5 | 0.8516 |
| Citation coverage | 0.8889 |
| Citation validity | 1.0000 |
| Faithfulness proxy | 0.6189 |

### Not yet measured: live application baseline

No quality, latency, throughput, or cost result for the running backend is
claimed in this repository. A release baseline should be added only with the run
artifact and complete protocol metadata. Until then, targets are expectations to
validate, not results:

- retrieval changes should not regress agreed Recall/nDCG floors;
- citation coverage and validity should remain explicit quality gates;
- latency budgets should be defined from the intended deployment and workload;
- per-slice regressions should block a release even if one aggregate improves.

## Interpretation

Use Recall@k to diagnose candidate generation, nDCG/MRR to diagnose ordering, and
citation measures only after relevant context is present. A high citation proxy
does not prove truth. Human review or a separately validated entailment judge is
required for material decisions. Never mix development-set tuning results with a
held-out test claim.
