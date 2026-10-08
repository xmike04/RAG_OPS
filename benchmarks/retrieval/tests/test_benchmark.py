from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from retrieval_benchmark.benchmark import (
    _model_artifact,
    _percentile,
    _read_completed,
    _run_query,
    stable_ranking,
    tokenize,
)
from retrieval_benchmark.dataset import Dataset, Document, Query


def test_stable_ranking_breaks_score_ties_by_document_id() -> None:
    ranking = stable_ranking(np.asarray([0.5, 0.7, 0.7]), ["z", "b", "a"], 3)
    assert ranking == [("a", 0.7), ("b", 0.7), ("z", 0.5)]


def test_tokenizer_is_casefolded_and_unicode_aware() -> None:
    assert tokenize("CAFÉ-based Evidence") == ["café", "based", "evidence"]


def test_percentile_uses_linear_interpolation() -> None:
    assert _percentile([1, 2, 3, 4], 0.5) == 2.5
    assert _percentile([1, 2, 3, 4], 0.95) == pytest.approx(3.85)


def test_resume_reader_rejects_results_from_other_configuration(tmp_path: Path) -> None:
    path = tmp_path / "per_query.jsonl"
    path.write_text(json.dumps({"run_id": "other", "query_id": "q1"}) + "\n")
    with pytest.raises(ValueError, match="different run"):
        _read_completed(path, "expected")


def test_local_model_artifact_records_exact_file_hashes(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"weights")
    artifact = _model_artifact(str(model), "ignored-for-local")
    assert artifact["kind"] == "local-directory"
    assert artifact["file_count"] == 2
    assert len(artifact["tree_sha256"]) == 64
    assert set(artifact["files_sha256"]) == {"config.json", "model.safetensors"}


class FakeBm25:
    def get_scores(self, tokens: list[str]) -> np.ndarray:
        assert tokens == ["alpha"]
        return np.asarray([1.0, 0.0])


class FakeEmbedder:
    def encode(self, texts: list[str], **kwargs: object) -> np.ndarray:
        assert texts == ["alpha"]
        return np.asarray([[1.0, 0.0]], dtype=np.float32)


class FakeReranker:
    def predict(self, pairs: list[tuple[str, str]], **kwargs: object) -> np.ndarray:
        assert len(pairs) == 2
        return np.asarray([2.0, -1.0])


def test_query_pipeline_emits_all_real_method_contracts() -> None:
    dataset = Dataset(
        documents=(
            Document("d1", "Alpha", "evidence"),
            Document("d2", "Beta", "noise"),
        ),
        queries=(Query("q1", "alpha"),),
        qrels={"q1": {"d1": 1}},
        fingerprint="fingerprint",
    )
    record = _run_query(
        query_id="q1",
        query_text="alpha",
        relevant=dataset.qrels["q1"],
        dataset=dataset,
        bm25=FakeBm25(),
        embedder=FakeEmbedder(),
        reranker=FakeReranker(),
        corpus_embeddings=np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        config={
            "candidate_depth": 2,
            "metric_cutoff": 1,
            "rrf_k": 60,
            "rerank_depth": 2,
            "rerank_batch_size": 2,
        },
        run_id="run",
    )
    assert set(record["metrics"]) == {"bm25", "vector", "rrf", "rerank"}
    assert record["metrics"]["rerank"]["recall@1"] == 1.0
    assert record["rankings"]["rerank"][0]["doc_id"] == "d1"
    assert record["end_to_end_latency_ms"]["rerank"] >= record["stage_latency_ms"]["rerank"]
