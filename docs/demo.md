# Demo walkthrough and technical talking points

This walkthrough is designed for a ten-minute technical demo. Use only behavior
you have verified in the current build; do not present the checked-in evaluator
fixture as a live-system benchmark.

## Before the demo

```bash
make up
make migrate
make seed
curl --fail http://localhost:8000/ready
make smoke
make eval
```

Open the console, API documentation, Grafana, and a terminal with API logs. Keep
one known query that produces both lexical and vector candidates.

## Ten-minute path

1. **Problem (one minute).** A chat answer is insufficient in production; teams
   need to know what was retrieved, what it cost, how long each stage took, and
   whether quality changed.
2. **Ingest (one minute).** Submit a Markdown document. Show the returned job ID
   and the transition from pending/running to succeeded. Explain eventual
   consistency and idempotent worker processing.
3. **Retrieve (two minutes).** Search for exact wording, then a paraphrase. Open a
   result's lexical/vector ranks and RRF contributions. Explain why rank fusion
   avoids calibrating incompatible score scales.
4. **Answer (one minute).** Ask a question, render its cited chunks, and explain
   that citation validation restricts references to supplied context.
5. **Operate (two minutes).** Use the trace to separate retrieval, reranking, and
   generation latency. Show bounded Prometheus labels and the readiness endpoint.
6. **Evaluate (two minutes).** Run the offline evaluator. State that the bundled
   run validates metric calculation only; a release result requires a fresh,
   versioned backend run.
7. **Tradeoffs (one minute).** Call out PostgreSQL coupling, deterministic local
   provider limitations, eventual consistency, and lexical faithfulness proxies.

## Useful questions to invite

**Why PostgreSQL and pgvector instead of a separate vector database?** It keeps
metadata, full-text search, vectors, and workspace filtering in one transactional
system. That simplifies the reference deployment while accepting a scaling and
coupling tradeoff.

**Why RRF?** Lexical rank and vector similarity have incompatible raw scales. RRF
uses positions, behaves predictably, and makes each contribution inspectable.

**What happens when a provider fails?** Configuration chooses deterministic or
production providers and validates them at startup. Runtime policy should make
fail-open versus fail-closed explicit; readiness covers core persistence, not a
costly provider call on every probe.

**How do you know answers are grounded?** The service restricts citations to
retrieved chunks and the evaluator measures coverage plus a lexical evidence
proxy. That is useful regression protection, not proof of entailment; human
review or an independently validated judge is needed for higher assurance.

**How is tenant isolation enforced?** Workspace predicates belong in every data
query. The demo's request field is only local scoping; production needs authenticated
identity bound to workspace authorization at the API edge.

## Resume-ready talking points

Adapt these to work you personally implemented and can explain:

- Built a FastAPI and React RAG reference platform with asynchronous ingestion,
  PostgreSQL full-text search, pgvector similarity, and Redis-backed work queues.
- Implemented inspectable hybrid ranking with reciprocal-rank fusion and a
  pluggable reranker, preserving per-stage scores and timings for diagnosis.
- Designed deterministic local embedding/generation providers so CI, onboarding,
  and product demos run without external model keys.
- Added retrieval-quality gates covering Recall@k, MRR, nDCG, citation coverage,
  a transparent faithfulness proxy, and latency percentiles.
- Instrumented health, readiness, structured request IDs, query traces, and
  Prometheus metrics while keeping high-cardinality and document data out of
  metric labels.

Avoid unsupported scale, latency, quality, reliability, or cost numbers. Replace
placeholders with results from a retained command output, versioned dataset, and
known configuration.
