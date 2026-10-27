from __future__ import annotations

import unittest

from benchmarks.service import run


class FixtureClient:
    def __init__(self, *, populated=False, duplicate=False, search_error=False):
        self.populated = populated
        self.duplicate = duplicate
        self.search_error = search_error
        self.documents = []

    def request(self, method, path, payload=None):
        if method == "POST" and path == "/v1/documents":
            self.documents.append(payload)
            return {"document": {"id": f"u{len(self.documents)}"},
                    "ingestion_job_id": f"j{len(self.documents)}"}
        if method == "GET" and path.startswith("/v1/ingestions/"):
            return {"status": "completed", "attempts": 1, "error": None}
        if method == "GET" and path.startswith("/v1/documents?"):
            if not self.documents:
                return {"total": int(self.populated), "items": [], "limit": 200, "offset": 0}
            return {"total": len(self.documents), "items": [
                {"id": f"u{i}", "status": "duplicate" if self.duplicate else "completed",
                 "metadata": item["metadata"]}
                for i, item in enumerate(self.documents, 1)
            ], "limit": 200, "offset": 0}
        if method == "POST" and path == "/v1/search":
            if self.search_error:
                raise TimeoutError("server details must not enter the public result")
            return {"results": [{"chunk_id": "c1", "document_id": "u1",
                                 "metadata": {"scifact_doc_id": "A"}}], "total": 1,
                    "latency_ms": {"total": 2.0}, "providers": {"embedding_provider": "local"}}
        raise AssertionError(f"unexpected request {method} {path}")


class ServiceRunnerTests(unittest.TestCase):
    def require(self, name):
        function = getattr(run, name, None)
        self.assertTrue(callable(function), f"service runner behavior {name} is not implemented")
        return function

    def test_ingestion_retains_source_ids_and_waits_for_completed_documents(self):
        ingest = self.require("ingest_documents")
        client = FixtureClient()
        mapping = ingest(client, [{"_id": "A", "title": "Title", "text": "Abstract"}], "workspace", timeout=1)
        self.assertEqual(mapping, {"u1": "A"})
        self.assertEqual(client.documents[0]["content"], "Title\n\nAbstract")
        self.assertEqual(client.documents[0]["metadata"]["scifact_doc_id"], "A")

    def test_ingestion_refuses_a_populated_workspace_without_submitting_documents(self):
        ingest = self.require("ingest_documents")
        client = FixtureClient(populated=True)
        with self.assertRaises(ValueError):
            ingest(client, [{"_id": "A", "title": "Title", "text": "Abstract"}], "workspace", timeout=1)
        self.assertEqual(client.documents, [])

    def test_backend_content_deduplication_cannot_silently_remove_qrel_documents(self):
        ingest = self.require("ingest_documents")
        with self.assertRaisesRegex(ValueError, "duplicate|completed"):
            ingest(FixtureClient(duplicate=True), [{"_id": "A", "title": "T", "text": "X"}], "workspace", timeout=1)

    def test_http_failure_is_retained_as_a_failed_query_and_not_a_relevance_success(self):
        evaluate = self.require("evaluate_queries")
        rows = evaluate(FixtureClient(search_error=True), [{"_id": "q", "text": "query"}],
                        {"q": {"A": 1}}, {"u1": "A"}, "workspace", top_k=100, rerank=False)
        self.assertEqual(rows[0]["query_id"], "q")
        self.assertEqual(rows[0]["error"], "TimeoutError")
        self.assertNotIn("server details", str(rows))

    def test_evaluation_scores_the_actual_response_after_document_mapping(self):
        evaluate = self.require("evaluate_queries")
        rows = evaluate(FixtureClient(), [{"_id": "q", "text": "query"}],
                        {"q": {"A": 1}}, {"u1": "A"}, "workspace", top_k=100, rerank=False)
        self.assertEqual(rows[0]["metrics"]["recall@10"], 1.0)
        self.assertEqual(rows[0]["ranked_document_ids"], ["A"])


    def test_consistently_changed_response_provider_cannot_validate_against_a_stale_snapshot(self):
        evaluate = self.require("evaluate_queries")
        runtime = {
            "query_embedding": {"provider": "sentence-transformers", "model": "MiniLM"},
            "reranking": {"provider": "local", "model": "lexical-overlap-v1"},
        }
        queries = [{"_id": "q1", "text": "query"}, {"_id": "q2", "text": "query"}]
        try:
            rows = evaluate(FixtureClient(), queries, {"q1": {"A": 1}, "q2": {"A": 1}},
                            {"u1": "A"}, "workspace", top_k=100, rerank=False, runtime=runtime)
        except TypeError:
            self.fail("evaluation does not accept and enforce captured runtime provider metadata")
        self.assertEqual([row["error"] for row in rows], ["ProviderMismatchError", "ProviderMismatchError"])

    def test_truncated_response_is_counted_and_later_queries_still_run(self):
        from http.client import IncompleteRead

        class TruncatedOnceClient(FixtureClient):
            def __init__(self):
                super().__init__()
                self.first = True

            def request(self, method, path, payload=None):
                if path == "/v1/search" and self.first:
                    self.first = False
                    raise IncompleteRead(b'{"results":', 100)
                return super().request(method, path, payload)

        evaluate = self.require("evaluate_queries")
        try:
            rows = evaluate(TruncatedOnceClient(), [{"_id": "q1", "text": "query"}, {"_id": "q2", "text": "query"}],
                            {"q1": {"A": 1}, "q2": {"A": 1}}, {"u1": "A"}, "workspace",
                            top_k=100, rerank=False)
        except IncompleteRead:
            self.fail("a truncated HTTP response escaped instead of becoming a failed-query record")
        self.assertEqual(rows[0]["error"], "IncompleteRead")
        self.assertEqual(rows[1]["metrics"]["recall@10"], 1.0)


if __name__ == "__main__":
    unittest.main()
