import unittest
from http.client import IncompleteRead
from benchmarks.service import load_matrix

class Client:
    def __init__(self, fail=False, empty=False):
        self.fail, self.empty = fail, empty
        self.calls = 0
    def request(self, method, path, payload=None):
        self.calls += 1
        if self.fail:
            raise IncompleteRead(b"partial", 10)
        hits = [] if self.empty else [{"chunk_id": "c", "document_id": "u",
                                      "metadata": {"scifact_doc_id": "A"}}]
        return {"results": hits, "total": len(hits), "latency_ms": {"total": 1.0},
                "providers": {"embedding_provider": "local", "embedding_model": "feature-hash-384"}}

class LoadMatrixTests(unittest.TestCase):
    def measure(self, client, **kwargs):
        function = getattr(load_matrix, "run_condition", None)
        self.assertTrue(callable(function), "mixed-query load measurement is not implemented")
        return function(client, [{"_id": "q1", "text": "alpha"}, {"_id": "q2", "text": "beta"}],
                        {"q1": {"A": 1}, "q2": {"A": 1}}, {"u": "A"}, "workspace",
                        runtime={"query_embedding": {"provider": "local", "model": "feature-hash-384"}},
                        concurrency=2, requests=6, warmup=2, **kwargs)
    def test_every_mixed_query_request_is_retained_and_counted(self):
        result = self.measure(Client())
        self.assertEqual(result["summary"]["attempted"], 6)
        self.assertEqual(result["summary"]["successful"], 6)
        self.assertEqual([row["query_id"] for row in result["per_request"]],
                         ["q1", "q2", "q1", "q2", "q1", "q2"])
        self.assertEqual(result["summary"]["latency_ms_successful"]["count"], 6)
        self.assertEqual(result["warmup"]["attempted"], 2)
        self.assertGreater(result["summary"]["successful_requests_per_second"], 0)
    def test_protocol_failures_are_counted_without_private_error_text(self):
        result = self.measure(Client(fail=True))
        self.assertEqual(result["summary"]["failed"], 6)
        self.assertEqual(result["summary"]["errors"], {"IncompleteRead": 6})
        self.assertIsNone(result["summary"]["latency_ms_successful"])
        self.assertNotIn("partial", str(result))
    def test_empty_success_envelopes_cannot_create_a_fast_success_claim(self):
        result = self.measure(Client(empty=True))
        self.assertEqual(result["summary"]["failed"], 6)
        self.assertEqual(result["summary"]["errors"], {"EmptySearchResult": 6})
    def test_resource_delta_reports_cpu_and_observed_rss_without_inventing_a_peak(self):
        function = getattr(load_matrix, "resource_delta", None)
        self.assertTrue(callable(function), "resource accounting is not implemented")
        before = {"started_ticks": 10, "cpu_ticks": 100, "rss_bytes": 1000}
        after = {"started_ticks": 10, "cpu_ticks": 150, "rss_bytes": 2000}
        result = function(before, after, elapsed=2.0, ticks_per_second=100)
        self.assertEqual(result["cpu_seconds"], 0.5)
        self.assertEqual(result["mean_cpu_percent_one_core"], 25.0)
        self.assertEqual(result["rss_start_bytes"], 1000)
        self.assertEqual(result["rss_end_bytes"], 2000)
        self.assertNotIn("peak_rss_bytes", result)
        self.assertIsNone(function(None, after, elapsed=2, ticks_per_second=100))
        after["started_ticks"] = 99
        self.assertIsNone(function(before, after, elapsed=2, ticks_per_second=100))
    def test_invalid_counts_are_rejected_before_requests(self):
        function = getattr(load_matrix, "run_condition", None)
        self.assertTrue(callable(function), "mixed-query load measurement is not implemented")
        for concurrency, requests, warmup in [(0, 1, 0), (1, 0, 0), (1, 1, -1)]:
            with self.subTest(concurrency=concurrency, requests=requests), self.assertRaises(ValueError):
                function(Client(), [{"_id": "q1", "text": "alpha"}], {"q1": {"A": 1}},
                         {"u": "A"}, "workspace", runtime=None,
                         concurrency=concurrency, requests=requests, warmup=warmup)


    def test_warmup_failures_keep_sanitized_categories_and_query_ids(self):
        result = self.measure(Client(fail=True))
        self.assertEqual(result["warmup"].get("errors"), {"IncompleteRead": 2})
        self.assertEqual([row["query_id"] for row in result["warmup"].get("records", [])], ["q1", "q2"])

    def test_search_counter_parser_distinguishes_missing_metrics_from_zero_searches(self):
        function = getattr(load_matrix, "parse_search_request_count", None)
        self.assertTrue(callable(function), "first-search counter verification is not implemented")
        family = "# TYPE ragops_http_requests_total counter\n"
        self.assertEqual(function(family), 0)
        self.assertEqual(function(family +
            'ragops_http_requests_total{method="GET",route="/ready",status="200"} 9.0\n' +
            'ragops_http_requests_total{method="POST",route="/v1/search",status="200"} 1.0\n' +
            'ragops_http_requests_total{method="POST",route="/v1/search",status="500"} 1.0\n'), 2)
        with self.assertRaises(ValueError):
            function("# A missing instrument is not a zero measurement\n")

    def cli_observation(self, snapshot_mode):
        import contextlib
        import io
        import json
        import sys
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch

        client = Client()
        before = {"pid": 999, "started_ticks": 10, "cpu_ticks": 100, "rss_bytes": 1000}
        after = {**before, "started_ticks": 11, "cpu_ticks": 150}
        def snapshot(pid):
            if pid is None or snapshot_mode == "unavailable":
                return None
            return before if client.calls == 0 else after
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ingest.json").write_text(json.dumps({
                "dataset_hashes": {"fixture": "hash"}, "workspace_id": "workspace", "document_map": {"u": "A"}}))
            runtime = {"query_embedding": {"provider": "local", "model": "feature-hash-384", "dimensions": 384},
                       "ingestion_embedding": {"provider": "local", "model": "feature-hash-384", "dimensions": 384},
                       "settings": {"retrieval_candidate_limit": 100},
                       "corpus": {"workspace_id": "workspace", "indexed_documents": 1},
                       "source_revision": "a" * 40}
            (root / "runtime.json").write_text(json.dumps(runtime))
            output = root / "observation.json"
            argv = ["load_matrix", "--ingest-dir", str(root), "--runtime", str(root / "runtime.json"),
                    "--output", str(output), "--phase", "first-search-after-api-restart",
                    "--api-pid", "999", "--concurrency", "1", "--requests", "1", "--warmup", "0",
                    "--sample-queries", "1"]
            with patch.object(sys, "argv", argv), patch.object(load_matrix, "HTTPClient", return_value=client), \
                 patch.object(load_matrix, "verify_manifest", return_value={"fixture": "hash"}), \
                 patch.object(load_matrix, "load_qrels", return_value={"q1": {"A": 1}}), \
                 patch.object(load_matrix, "load_queries", return_value=[SimpleNamespace(query_id="q1", text="alpha")]), \
                 patch.object(load_matrix, "process_snapshot", side_effect=snapshot), \
                 patch.object(load_matrix, "read_search_request_count", side_effect=lambda unused: client.calls, create=True), \
                 contextlib.redirect_stdout(io.StringIO()):
                try:
                    code = load_matrix.main()
                except ValueError:
                    code = 1
            result = json.loads(output.read_text()) if output.exists() else None
        return client.calls, code, result

    def test_missing_restart_process_is_rejected_before_consuming_the_search(self):
        calls, code, result = self.cli_observation("unavailable")
        self.assertEqual(calls, 0)
        self.assertEqual(code, 1)
        self.assertIsNotNone(result)
        self.assertEqual(result["observation_status"], "invalid")

    def test_changed_restart_process_retains_an_invalid_observation(self):
        calls, code, result = self.cli_observation("changed")
        self.assertEqual(calls, 1)
        self.assertEqual(code, 1)
        self.assertIsNotNone(result)
        self.assertEqual(result["observation_status"], "invalid")

if __name__ == "__main__":
    unittest.main()
