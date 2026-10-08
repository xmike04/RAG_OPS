# Real-model retrieval benchmark

This isolated benchmark evaluates the BEIR SciFact test split with four real retrieval
pipelines on CPU:

1. Okapi BM25 (`rank_bm25.BM25Okapi`, `k1=1.5`, `b=0.75`)
2. cosine similarity over normalized `sentence-transformers/all-MiniLM-L6-v2` embeddings
3. reciprocal-rank fusion of BM25 and vector candidates
4. a Sentence Transformers CrossEncoder over the fixed fused shortlist

It reports Recall@10, MRR@10, nDCG@10, and end-to-end per-query p50/p95 latency.
Model/index creation and one warmup call are deliberately excluded from query timing. RRF
latency includes both candidate retrievers; reranking latency includes retrieval and fusion.

## Reproduce

From this directory:

```bash
uv sync --frozen
uv run ragops-retrieval-prepare
uv run ragops-retrieval-benchmark
```

Preparation defaults to the repository's pinned dataset at
`../datasets/scifact/v1`, verifies every file against `dataset_manifest.json`, and copies it
to `.cache/data/scifact`. Outside the full repository, preparation downloads the official
BEIR archive and verifies the extracted files against the same SHA256 manifest. A local
archive or standard BEIR directory can be supplied explicitly:

```bash
uv run ragops-retrieval-prepare --archive /path/to/scifact.zip
uv run ragops-retrieval-prepare --source-dir /path/to/scifact
```

The default benchmark configuration downloads pinned public Hugging Face embedding and
MS MARCO cross-encoder revisions. The retained RAGOps baseline instead uses a locally
trained cross-encoder initialized from all-MiniLM-L6-v2, trained only on SciFact train
qrels with deterministic BM25 hard negatives, then evaluated once on the disjoint test
split. No API token is required for public model access. All execution is forced onto CPU.
To use an already populated cache and prohibit network fallback, add `--offline`.

Both model arguments also accept local SentenceTransformers directories. This supports a
locally fine-tuned CrossEncoder without changing evaluation code:

```bash
uv run ragops-retrieval-benchmark \
  --embedding-model /models/all-MiniLM-L6-v2 \
  --rerank-model /models/scifact-cross-encoder \
  --offline
```

Every local model file is SHA256-hashed into `run_config.json`; the combined model tree
hash is part of the run ID. If training a SciFact-specific reranker, use only the official
train split for fitting/model selection and keep the benchmark test qrels untouched.

### Optional train-only SciFact reranker

Training is a separate explicit command. It reads `qrels/train.tsv`, reads test qrels only to
assert that the query IDs are disjoint, and refuses to start if any split overlap exists. It
mines top unjudged BM25 documents as deterministic hard negatives and never evaluates or
selects on test labels:

```bash
uv run ragops-train-scifact-reranker \
  --base-model /models/all-MiniLM-L6-v2 \
  --output-dir .cache/models/scifact-cross-encoder \
  --negatives-per-query 3 \
  --epochs 1 \
  --batch-size 16 \
  --seed 17
```

The base model must be a local all-MiniLM-L6-v2 directory; training is forced to CPU and
will not download a substitute. The output directory must not already exist. Alongside the
saved CrossEncoder, `training_config.json` records train and test qrel hashes, the base-model
tree hash, mined-pair hash, git/code state, hardware, hyperparameters, counts, split-isolation
assertion, and duration. Evaluate it only in a later, separate command:

```bash
uv run ragops-retrieval-benchmark \
  --rerank-model .cache/models/scifact-cross-encoder \
  --offline
```

Use `--output-dir` to resume an interrupted named run. Without it, the directory is derived
from the canonical configuration hash:

```text
results/scifact/<run-id>/
├── run_config.json   # resolved models, dataset provenance, code/environment/hardware
├── per_query.jsonl   # resumable rankings, metrics, and timings for every query
├── summary.json      # aggregate metrics, p50/p95 latency, artifact checksums
└── report.md         # human-readable result table
```

Corpus embeddings are cached under `.cache/models` and keyed by dataset fingerprint, model
ID, revision, normalization, document order, and dtype. A partial `per_query.jsonl` is
validated against the run ID and resumed without repeating completed queries.

Useful controls include:

```bash
uv run ragops-retrieval-benchmark \
  --candidate-depth 100 \
  --rerank-depth 100 \
  --embedding-batch-size 64 \
  --rerank-batch-size 32 \
  --torch-threads 8 \
  --hardware-note "dedicated 8-vCPU runner"
```

The candidate and rerank depths are fixed across all test queries. Do not compare latency
from different hardware or thread settings without calling out that difference.

## Integrity and attribution

`dataset_manifest.json` records upstream provenance, licenses, byte counts, record counts,
and SHA256 digests. `ATTRIBUTION.md` contains citation and licensing details. Each prepared
dataset receives `dataset_state.json`, and its full provenance plus checksum is embedded in
every run configuration and summary.

The scripts never contain precomputed or fabricated benchmark scores. A report exists only
after all 300 test queries have been evaluated successfully.

## Development checks

```bash
uv sync --extra dev --frozen
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src/retrieval_benchmark
```
