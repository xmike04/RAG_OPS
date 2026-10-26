# Frozen SciFact HTTP serving evidence

Measured source is identified in environment.json. Each .gz file contains the exact original harness output; the manifest hashes the uncompressed bytes. Input data and attribution retain the SciFact licenses in benchmarks/datasets/scifact/LICENSES.md. Train and held-out results are separate; no parameter tuning followed test observation. These are deterministic-provider serving measurements, not the offline BM25/MiniLM experiment or production SLOs.
