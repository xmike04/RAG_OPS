import unittest
from http.client import IncompleteRead
from benchmarks.service import load_matrix

class Client:
    def __init__(self, fail=False, empty=False):
        self.fail, self.empty = fail, empty
    def request(self, method, path, payload=None):
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

if __name__ == "__main__":
    unittest.main()
