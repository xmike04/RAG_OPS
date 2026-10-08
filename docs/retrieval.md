# Retrieval design

## Pipeline

RAGOps uses the same retrieval path for `/v1/search` and `/v1/query`:

1. Normalize the query and create an embedding.
2. Generate lexical candidates with PostgreSQL full-text search.
3. Generate vector candidates with pgvector similarity.
4. Fuse ranked lists using reciprocal-rank fusion.
5. Optionally rerank the fused shortlist.
6. Select bounded context for generation and return stable chunk citations.

Candidate generation may run concurrently. Each stage records latency and the
trace retains rank contributions so an operator can explain why a chunk won.

## Chunking and identity

Chunks should be large enough to contain a coherent claim and small enough to
avoid burying it. Boundaries prefer headings and paragraphs before falling back
to a token/character window with overlap. Store source offsets or structural
metadata so citations can be rendered in context.

A chunk ID must be stable for unchanged content under the same chunking version.
Changing normalization, window size, overlap, or tokenizer is a retrieval-model
change: version it, re-index documents, and evaluate before rollout.

## Candidate generation

Lexical search is strongest for exact names, identifiers, and rare phrases.
Vector search is strongest when the query and evidence use different wording.
Both queries must apply the workspace predicate in the database operation.

Raw scores are deliberately not mixed. Their scales and distributions differ by
index, query, and provider.

## Reciprocal-rank fusion

For chunk `d` in ranked lists `R`, RAGOps computes:

```text
RRF(d) = sum(1 / (rrf_k + rank_r(d))) for r in R where d appears
```

Ranks are one-based. `rrf_k` dampens the difference between neighboring ranks;
it is unrelated to the response `top_k`. A chunk present in both lists receives
both contributions. Deterministic tie-breaking uses a stable chunk ID after all
ranking keys are exhausted.

RRF avoids score calibration and is robust when one retriever has a different
score range. It loses score magnitude: an overwhelming first-place result and a
barely first-place result contribute equally.

## Reranking and context selection

The reranker only sees a bounded fused shortlist. It returns a normalized score
and provider/model metadata. Context selection applies a separate maximum result
count and content budget; a larger candidate pool does not imply a larger prompt.

The deterministic local reranker makes regression tests repeatable. Treat it as
a contract fixture, not a relevance benchmark for a learned model.

Set `RAGOPS_RERANKER_PROVIDER=sentence-transformers` and
`RAGOPS_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2` to run the optional
cross-encoder implementation. The Compose image must be built with
`RAGOPS_INSTALL_ML=true`; see the local-development guide. The model is loaded
once per API process and inference runs off the event loop so concurrent requests
remain responsive.

## Tuning protocol

Change one dimension at a time where practical:

- chunk size, overlap, and structural splitting;
- lexical/vector candidate depths;
- `rrf_k` and any per-list weighting;
- reranker shortlist size and provider;
- final context count and budget.

Measure Recall@k, MRR, nDCG, citation proxies, and latency on a versioned dataset.
Inspect per-query regressions, especially queries with identifiers, paraphrases,
and multiple valid chunks. Do not pick a configuration from aggregate metrics
alone. Follow [`evaluation.md`](evaluation.md) and record the exact configuration.

## Known limitations

- Binary relevance labels do not express usefulness grades.
- Full-text configuration and language stemming can disadvantage mixed-language
  or code-heavy documents.
- Dense embeddings can retrieve topically similar but non-supporting text.
- Reranking cannot recover a relevant chunk absent from its shortlist.
- Lexical citation proxies cannot establish semantic entailment.
