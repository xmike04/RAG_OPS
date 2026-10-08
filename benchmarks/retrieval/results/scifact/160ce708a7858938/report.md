# SciFact retrieval benchmark

Run ID: `160ce708a7858938`  
Corpus: 5183 documents; 300 test queries.

| Method | Recall@10 | MRR@10 | nDCG@10 | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| bm25 | 0.7740 | 0.6186 | 0.6519 | 24.18 | 42.78 |
| vector | 0.7833 | 0.6047 | 0.6451 | 14.51 | 27.60 |
| rrf | 0.8059 | 0.6472 | 0.6816 | 40.43 | 67.97 |
| rerank | 0.5523 | 0.1757 | 0.2596 | 1479.88 | 1747.43 |

Latency is per query on CPU. BM25/vector are standalone; RRF includes both candidate retrievers and fusion; rerank includes retrieval, fusion, and cross-encoder scoring. Model loading, corpus indexing/embedding, and warmup are excluded.
