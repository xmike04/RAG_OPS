# Dataset and model attribution

This benchmark uses the **SciFact** dataset introduced by David Wadden, Shanchuan Lin,
Kyle Lo, Lucy Lu Wang, Madeleine van Zuylen, Arman Cohan, and Hannaneh Hajishirzi in
“Fact or Fiction: Verifying Scientific Claims” (EMNLP 2020).

- Paper: <https://aclanthology.org/2020.emnlp-main.609/>
- Authoritative source: <https://github.com/allenai/scifact>, pinned to commit
  `68b98a56d93e0f9da0d2aab4e6c3294699a0f72e`
- BEIR distribution: <https://github.com/beir-cellar/beir>

The BEIR benchmark packaging and evaluation convention are from Nandan Thakur et al.,
“BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval
Models” (NeurIPS Datasets and Benchmarks 2021):
<https://openreview.net/forum?id=wCu6T5xFjeJ>.

SciFact claims and annotations are CC BY 4.0. Corpus abstracts originate from S2ORC and
are ODC-By 1.0. The upstream SciFact code is Apache-2.0. Consult the upstream license
before redistributing data or derivative artifacts. Exact prepared-file SHA256 values
are recorded in `dataset_manifest.json` and verified by the preparation command.

The benchmark downloads these unmodified Hugging Face model repositories at pinned
revisions and does not redistribute their weights:

- `sentence-transformers/all-MiniLM-L6-v2`
- `cross-encoder/ms-marco-MiniLM-L-6-v2`

Review each model card for its training data, limitations, and license before use.

