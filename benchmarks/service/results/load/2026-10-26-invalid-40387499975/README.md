# Rejected first-search collection

Collection [40387499975](https://github.com/xmike04/RAG_OPS/actions/runs/40387499975)
at source 2d40fd13844ff4436f54c53fbfde2320670d5148 failed the first-search counter
invariant. All five restart observations are explicitly invalid: the harness
looked only for the prefixed Prometheus label, while locked FastAPI 0.143 emits
`route="/search"`. A later integration test reproduced the label difference.
No first-search validity or cold-start result is claimed from these files.

The three warm conditions completed 300 measured requests each, but this
directory retains the failed collection for audit rather than supplying the
final matrix headline. Every compressed original is checksummed in
environment.json. Public SciFact attribution is in
benchmarks/datasets/scifact/LICENSES.md. No held-out queries, generation,
learned inference, billing, peak RSS, or production capacity were measured.
