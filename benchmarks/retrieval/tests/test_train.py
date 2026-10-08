from __future__ import annotations

import json
from pathlib import Path

import pytest

from retrieval_benchmark.train import load_training_data, mine_training_pairs


def _write_training_dataset(root: Path, *, overlap: bool = False) -> None:
    root.mkdir()
    (root / "qrels").mkdir()
    documents = [
        {"_id": "positive", "title": "Alpha therapy", "text": "effective treatment"},
        {"_id": "hard", "title": "Alpha therapy", "text": "unrelated outcome"},
        {"_id": "easy", "title": "Astronomy", "text": "distant stars"},
        {"_id": "test-positive", "title": "Beta evidence", "text": "held out"},
    ]
    queries = [
        {"_id": "train-query", "text": "alpha therapy"},
        {"_id": "test-query", "text": "beta evidence"},
    ]
    (root / "corpus.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in documents), encoding="utf-8"
    )
    (root / "queries.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in queries), encoding="utf-8"
    )
    (root / "qrels/train.tsv").write_text(
        "query-id\tcorpus-id\tscore\ntrain-query\tpositive\t1\n", encoding="utf-8"
    )
    test_query = "train-query" if overlap else "test-query"
    (root / "qrels/test.tsv").write_text(
        f"query-id\tcorpus-id\tscore\n{test_query}\ttest-positive\t1\n", encoding="utf-8"
    )


def test_training_data_asserts_train_test_query_isolation(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "scifact"
    _write_training_dataset(dataset_dir, overlap=True)
    with pytest.raises(ValueError, match="split isolation failed"):
        load_training_data(dataset_dir)


def test_bm25_mining_uses_only_train_queries_and_excludes_positives(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "scifact"
    _write_training_dataset(dataset_dir)
    data = load_training_data(dataset_dir)
    pairs = mine_training_pairs(data, negatives_per_query=2, seed=17)

    assert len(pairs) == 3
    assert {pair.query_id for pair in pairs} == {"train-query"}
    assert all(pair.query_id not in data.test_query_ids for pair in pairs)
    positives = [pair for pair in pairs if pair.label == 1.0]
    negatives = [pair for pair in pairs if pair.label == 0.0]
    assert [pair.doc_id for pair in positives] == ["positive"]
    assert "positive" not in {pair.doc_id for pair in negatives}
    assert "hard" in {pair.doc_id for pair in negatives}


def test_pair_mining_is_repeatable_for_fixed_seed(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "scifact"
    _write_training_dataset(dataset_dir)
    data = load_training_data(dataset_dir)
    first = mine_training_pairs(data, negatives_per_query=2, seed=123)
    second = mine_training_pairs(data, negatives_per_query=2, seed=123)
    assert first == second
