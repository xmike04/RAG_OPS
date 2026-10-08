from __future__ import annotations

import pytest

from retrieval_benchmark.metrics import evaluate_ranking, reciprocal_rank_fusion


def test_binary_metrics_at_cutoff() -> None:
    metrics = evaluate_ranking(
        ["noise", "relevant-1", "relevant-2"],
        {"relevant-1": 1, "relevant-2": 1},
    )
    assert metrics.recall == 1.0
    assert metrics.reciprocal_rank == 0.5
    assert metrics.ndcg == pytest.approx(0.6934264036172708)


def test_graded_ndcg_and_cutoff() -> None:
    metrics = evaluate_ranking(["low", "high"], {"high": 3, "low": 1}, cutoff=1)
    assert metrics.recall == 0.5
    assert metrics.reciprocal_rank == 1.0
    assert metrics.ndcg == pytest.approx(1 / 7)


def test_rrf_is_explainable_and_deterministic() -> None:
    ranking, contributions = reciprocal_rank_fusion(
        {"bm25": ["a", "b"], "vector": ["b", "a"]}, k=10
    )
    assert ranking == ["a", "b"]
    assert contributions["a"] == {"bm25": 1 / 11, "vector": 1 / 12}


def test_rrf_deduplicates_each_source() -> None:
    ranking, contributions = reciprocal_rank_fusion({"bm25": ["a", "a", "b"]}, k=10)
    assert ranking == ["a", "b"]
    assert contributions["a"] == {"bm25": 1 / 11}
