from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from benchmarks.service import core


def response(hits: list[dict]) -> dict:
    return {
        "results": hits,
        "total": len(hits),
        "latency_ms": {"embedding": 2.0, "lexical_retrieval": 3.0, "total": 8.0},
        "providers": {"embedding_provider": "local", "embedding_model": "deterministic-hash-v1"},
    }


def hit(chunk: str, document: str, original: str) -> dict:
    return {
        "chunk_id": chunk, "document_id": document,
        "metadata": {"scifact_doc_id": original},
    }


class ServiceScoringTests(unittest.TestCase):
    def require(self, name: str):
        function = getattr(core, name, None)
        self.assertTrue(callable(function), f"serving-path behavior {name} is not implemented")
        return function

    def test_chunks_from_one_document_do_not_inflate_recall_or_consume_document_ranks(self):
        score = self.require("score_response")
        result = score(
            "q1", response([hit("c1", "u1", "A"), hit("c2", "u1", "A"), hit("c3", "u2", "B")]),
            {"A": 1, "B": 1}, {"u1": "A", "u2": "B"}, elapsed_ms=12.0,
        )
        self.assertEqual(result["ranked_document_ids"], ["A", "B"])
        self.assertEqual(result["metrics"]["recall@10"], 1.0)
        self.assertEqual(result["metrics"]["ndcg@10"], 1.0)
        self.assertEqual(result["returned_chunks"], 3)
        self.assertEqual(len(result["chunk_to_document"]), 3)

    def test_relevant_document_at_second_rank_has_half_reciprocal_rank(self):
        score = self.require("score_response")
        result = score("q", response([hit("c1", "u1", "A"), hit("c2", "u2", "B")]),
                       {"B": 1, "C": 1}, {"u1": "A", "u2": "B"}, elapsed_ms=9.0)
        self.assertEqual(result["metrics"]["mrr@10"], 0.5)
        self.assertEqual(result["metrics"]["recall@100"], 0.5)
        self.assertAlmostEqual(result["metrics"]["ndcg@10"], 0.38685280723454163)

    def test_missing_or_conflicting_document_attribution_rejects_the_response(self):
        score = self.require("score_response")
        for hits in ([hit("c1", "unknown", "A")], [hit("c1", "u1", "WRONG")]):
            with self.subTest(hits=hits), self.assertRaises(ValueError):
                score("q", response(hits), {"A": 1}, {"u1": "A"}, elapsed_ms=1.0)

    def test_duplicate_chunk_ids_and_nonfinite_timing_are_rejected(self):
        score = self.require("score_response")
        with self.assertRaises(ValueError):
            score("q", response([hit("c1", "u1", "A"), hit("c1", "u1", "A")]),
                  {"A": 1}, {"u1": "A"}, elapsed_ms=1.0)
        invalid = response([])
        invalid["latency_ms"]["total"] = float("nan")
        with self.assertRaises(ValueError):
            score("q", invalid, {"A": 1}, {}, elapsed_ms=1.0)

    def test_failed_queries_remain_in_the_quality_denominator(self):
        aggregate = self.require("aggregate")
        score = self.require("score_response")
        good = score("q1", response([hit("c", "u", "A")]), {"A": 1}, {"u": "A"}, elapsed_ms=10.0)
        failed = {"query_id": "q2", "error": "TimeoutError", "elapsed_ms": 20.0}
        result = aggregate([good, failed], ["q1", "q2"])
        self.assertEqual(result["quality_all_queries"]["recall@10"], 0.5)
        self.assertEqual(result["failed_queries"], 1)
        self.assertEqual(result["http_latency_ms_successful"]["p95"], 10.0)
        self.assertFalse(result["complete_without_errors"])

    def test_missing_duplicate_queries_and_provider_drift_cannot_produce_an_aggregate(self):
        aggregate = self.require("aggregate")
        score = self.require("score_response")
        good = score("q1", response([]), {"A": 1}, {}, elapsed_ms=1.0)
        for rows in ([], [good, good]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                aggregate(rows, ["q1"])
        other = score("q2", response([]), {"A": 1}, {}, elapsed_ms=1.0)
        other["providers"]["embedding_model"] = "changed"
        with self.assertRaises(ValueError):
            aggregate([good, other], ["q1", "q2"])

    def test_runtime_preflight_rejects_mixed_embedding_spaces_and_insufficient_depth(self):
        validate = self.require("validate_runtime")
        runtime = {
            "settings": {"embedding_provider": "sentence-transformers", "embedding_model": "MiniLM",
                         "embedding_dimensions": 384, "retrieval_candidate_limit": 100},
            "query_embedding": {"provider": "sentence-transformers", "model": "MiniLM", "dimensions": 384},
            "ingestion_embedding": {"provider": "local", "model": "deterministic-hash-v1", "dimensions": 384},
        }
        with self.assertRaisesRegex(ValueError, "embedding"):
            validate(runtime, request_top_k=100)
        runtime["settings"].update(embedding_provider="local", embedding_model="deterministic-hash-v1",
                                   retrieval_candidate_limit=40)
        runtime["query_embedding"].update(provider="local", model="deterministic-hash-v1")
        with self.assertRaisesRegex(ValueError, "candidate"):
            validate(runtime, request_top_k=100)
        runtime["settings"]["retrieval_candidate_limit"] = 100
        validate(runtime, request_top_k=100)

    def test_dataset_checksum_failure_prevents_using_corrupted_evidence(self):
        verify = self.require("verify_manifest")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "corpus.jsonl").write_text("original\n")
            digest = hashlib.sha256(b"original\n").hexdigest()
            manifest = f"{digest}  corpus.jsonl\n"
            (root / "manifest.sha256").write_text(manifest)
            expected = hashlib.sha256(manifest.encode()).hexdigest()
            self.assertEqual(verify(root, expected)["corpus.jsonl"], digest)
            (root / "corpus.jsonl").write_text("changed\n")
            with self.assertRaises(ValueError):
                verify(root, expected)

    def test_manifest_cannot_escape_the_dataset_directory(self):
        verify = self.require("verify_manifest")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = "0" * 64 + "  ../private.txt\n"
            (root / "manifest.sha256").write_text(manifest)
            with self.assertRaises(ValueError):
                verify(root, hashlib.sha256(manifest.encode()).hexdigest())

    def test_paired_analysis_aligns_query_ids_and_reports_a_reproducible_interval(self):
        compare = self.require("paired_comparison")
        baseline = {"dataset_fingerprint": "same", "split": "test", "per_query": [
            {"query_id": "q1", "metrics": {"recall@10": 0.0}},
            {"query_id": "q2", "metrics": {"recall@10": 0.5}}]}
        current = {"dataset_fingerprint": "same", "split": "test", "per_query": [
            {"query_id": "q2", "metrics": {"recall@10": 1.0}},
            {"query_id": "q1", "metrics": {"recall@10": 0.5}}]}
        result = compare(current, baseline, "recall@10", samples=100, seed=0)
        self.assertEqual(result["mean_delta"], 0.5)
        self.assertEqual(result["bootstrap_95_percent_interval"], [0.5, 0.5])
        self.assertEqual(result["per_query_delta"], {"q1": 0.5, "q2": 0.5})
        baseline["dataset_fingerprint"] = "different"
        with self.assertRaises(ValueError):
            compare(current, baseline, "recall@10", samples=100, seed=0)


    def test_provider_validation_checks_requested_reranking_metadata(self):
        validate = self.require("validate_response_providers")
        runtime = {"query_embedding": {"provider": "local", "model": "feature-hash-384"},
                   "reranking": {"provider": "local", "model": "lexical-overlap-v1"}}
        actual = {"embedding_provider": "local", "embedding_model": "feature-hash-384",
                  "rerank_provider": "local", "rerank_model": "lexical-overlap-v1"}
        validate(actual, runtime, rerank=True)
        with self.assertRaises(ValueError):
            validate(actual, runtime, rerank=False)
        actual["rerank_model"] = "different-model"
        with self.assertRaises(ValueError):
            validate(actual, runtime, rerank=True)


if __name__ == "__main__":
    unittest.main()
