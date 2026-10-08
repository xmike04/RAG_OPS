# BEIR SciFact dataset

`v1/` contains the complete SciFact corpus and standard BEIR test evaluation
inputs. It is intentionally checked in because the normalized dataset is small
enough for this repository (about 8.3 MB).

## Contents

- `v1/corpus.jsonl`: 5,183 scientific abstracts.
- `v1/queries.jsonl`: all 1,109 BEIR SciFact queries. The split membership is
  defined by the query IDs referenced by each qrels file.
- `v1/qrels/train.tsv`: 919 relevance judgments for 809 training queries.
- `v1/qrels/test.tsv`: 339 relevance judgments for 300 test queries.
- `v1/metadata.json`: pinned source and normalization metadata.
- `v1/manifest.sha256`: SHA-256 digests for every versioned artifact.

## Provenance

The benchmark distribution is BEIR SciFact:

- Official archive: <https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip>
- Published archive size: `2,816,079` bytes
- Published archive MD5: `5f7d1de60b170fc8027bb7898e2efca1`
- BEIR catalog revision used to verify URL, size, checksum, format, and counts:
  `beir-cellar/beir@ef83d29307061c65d04b035b4f4e7c18bd8374af`
- Original SciFact project and license statement:
  `allenai/scifact@68b98a56d93e0f9da0d2aab4e6c3294699a0f72e`

The managed build environment blocked the official BEIR host during initial
materialization. The checked-in standard-layout files were therefore materialized
from the public mirror
`Omar-Khattab-01/Vector-Space-Model-Based-Information-Retrieval-System-for-the-SciFact-Dataset@f8367e8d7c25d09c608bae11bf2ea111c06e029f`,
then validated against BEIR/ir_datasets counts, identifiers, schemas, and sentinel
records before deterministic normalization. `prepare.py` remains the canonical
way to reproduce them from the checksum-verified official archive.

## Reproduce and verify

From this directory:

```bash
python prepare.py --output /tmp/scifact-v1
cd /tmp/scifact-v1
sha256sum --check manifest.sha256
```

For an existing official archive, use `--archive /path/to/scifact.zip`. For an
already extracted standard BEIR tree, use `--source-dir /path/to/scifact`.

Normalization is deterministic: strings are NFC-normalized, newlines become LF,
JSON is compact UTF-8 with fixed field order, records/qrels are numerically sorted
by identifier, and every output ends with a newline. No document or query text is
invented, summarized, or paraphrased.

See [LICENSES.md](LICENSES.md) for attribution and redistribution terms.
