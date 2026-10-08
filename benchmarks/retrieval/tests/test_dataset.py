from __future__ import annotations

import json
from pathlib import Path

import pytest

from retrieval_benchmark.dataset import load_dataset


def _write_dataset(root: Path) -> None:
    root.mkdir()
    (root / "qrels").mkdir()
    corpus = [
        {"_id": "d1", "title": "Alpha", "text": "first document"},
        {"_id": "d2", "title": "Beta", "text": "second document"},
    ]
    queries = [
        {"_id": "q-test", "text": "alpha"},
        {"_id": "q-train", "text": "not evaluated"},
    ]
    (root / "corpus.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in corpus), encoding="utf-8"
    )
    (root / "queries.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in queries), encoding="utf-8"
    )
    (root / "qrels/test.tsv").write_text(
        "query-id\tcorpus-id\tscore\nq-test\td1\t1\n", encoding="utf-8"
    )


def test_load_dataset_filters_queries_to_test_qrels(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    _write_dataset(dataset_root)
    dataset = load_dataset(dataset_root)
    assert [document.doc_id for document in dataset.documents] == ["d1", "d2"]
    assert [query.query_id for query in dataset.queries] == ["q-test"]
    assert dataset.documents[0].searchable_text == "Alpha first document"
    assert len(dataset.fingerprint) == 64


def test_load_dataset_rejects_qrel_for_missing_document(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    _write_dataset(dataset_root)
    (dataset_root / "qrels/test.tsv").write_text(
        "query-id\tcorpus-id\tscore\nq-test\tmissing\t1\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing corpus"):
        load_dataset(dataset_root)
