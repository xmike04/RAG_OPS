# Two-minute demo video script

This script shows working behavior without turning fixture data into a benchmark
claim. Record against a fresh seeded stack and use one continuous capture where
possible.

A captioned, silent two-minute visual walkthrough is retained at
[`assets/ragops-two-minute-walkthrough.mp4`](assets/ragops-two-minute-walkthrough.mp4).
Use this script to record the narrated edition.

## Preflight

```bash
make up
make migrate
make seed
make smoke
make eval
```

Open the console, one query trace, and the terminal. Hide `.env`, credentials,
document contents that are not demo data, and unrelated browser tabs. Confirm
the displayed benchmark artifacts belong to the current revision.

Measured-result cues are sourced from artifacts, never improvised. Leave null
values unspoken:

```json
{
  "retrieval_summary": "benchmarks/retrieval/results/scifact/<run-id>/summary.json",
  "load_summary": "benchmarks/load/results/<run-id>/summary.json",
  "retrieval_metric_to_say": null,
  "load_metric_to_say": null
}
```

## Shot list and narration

### 0:00–0:15 — The problem

**Screen:** Console overview, then the architecture diagram.

**Narration:** “RAGOps is a production-style retrieval-augmented generation
reference platform. The goal is not just to return an answer; it is to expose
what was retrieved, why it ranked, how long each stage took, and whether quality
changes across releases.”

### 0:15–0:35 — Asynchronous ingestion

**Screen:** Submit the seeded Markdown document and show its job moving to a
terminal successful state.

**Narration:** “Document submission creates a durable ingestion job. A worker
normalizes, chunks, embeds, and transactionally publishes the searchable chunks.
The API remains responsive, while the job status makes eventual consistency and
failures explicit.”

### 0:35–1:00 — Inspectable hybrid retrieval

**Screen:** Search for “How does reciprocal-rank fusion combine results?” Open a
result row showing lexical/vector ranks, RRF contribution, and rerank score.

**Narration:** “Search runs lexical and vector candidate generation, combines
their rank positions with reciprocal-rank fusion, and optionally reranks a
bounded shortlist. The response preserves component scores and timings, so a
ranking decision can be inspected instead of treated as a black box.”

### 1:00–1:20 — Grounded answer and trace

**Screen:** Run the grounded query, expand its citations, then open the trace.

**Narration:** “Answer generation is constrained to retrieved context and returns
stable chunk citations. The trace separates retrieval and generation latency,
records provider metadata and token usage, and carries the request ID used to
correlate logs.”

### 1:20–1:40 — Evaluation honesty

**Screen:** Run `make eval`; keep the terminal label “evaluator fixture” visible.

**Narration:** “This offline run is deliberately a deterministic evaluator
fixture. It verifies Recall, MRR, nDCG, citation, and latency calculations, but it
is not a claim about live model quality or service performance.”

### 1:40–1:55 — Measured evidence

**Screen:** Show the retained real-model `summary.json` and live-load
`environment.json`/`summary.json` side by side. If either is absent, show the
pending-measurement status instead of a number.

**Narration:** “Release evidence is separate: real-model retrieval results are
tied to dataset and model revisions, while HTTP load results are tied to a
recorded workload and machine. Raw per-query and per-request artifacts make both
runs reproducible.”

### 1:55–2:00 — Close

**Screen:** Return to the console with citations and stage timings visible.

**Narration:** “That separation—answer, evidence, operations, and evaluation—is
the core of RAGOps.”

## Recording rules

- Do not call evaluator-fixture latency an application measurement.
- Do not display a learned-model or load number without its retained summary and
  environment/provenance artifact.
- Do not compare runs with different data, hardware, or model revisions as if
  only the code changed.
- Do not expose API keys, headers, private source text, or query-trace data from
  a non-demo workspace.
- Keep the video under two minutes by trimming transitions, not caveats.
