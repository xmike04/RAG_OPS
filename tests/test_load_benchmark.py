from __future__ import annotations

import argparse
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar

from benchmarks.load.run import (
    RequestSample,
    RunResult,
    SearchRequester,
    build_report,
    latency_summary,
    percentile,
    run_request_count,
    summarize,
    write_artifacts,
)


class LoadBenchmarkUnitTests(unittest.TestCase):
    def test_nearest_rank_percentiles_and_empty_summary(self) -> None:
        values = [5.0, 1.0, 4.0, 2.0, 3.0]
        self.assertEqual(percentile(values, 0.50), 3.0)
        self.assertEqual(percentile(values, 0.95), 5.0)
        self.assertEqual(
            latency_summary([]),
            {"min": None, "p50": None, "p95": None, "p99": None, "max": None},
        )

    def test_request_count_is_exact_and_concurrency_is_bounded(self) -> None:
        lock = threading.Lock()
        active = 0
        maximum_active = 0

        def request(request_id: int) -> RequestSample:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.005)
            with lock:
                active -= 1
            return RequestSample(request_id, True, 200, 1.0)

        result = run_request_count(20, 4, request)

        self.assertEqual([sample.request_id for sample in result.samples], list(range(20)))
        self.assertGreater(maximum_active, 1)
        self.assertLessEqual(maximum_active, 4)

    def test_summary_counts_failures_and_success_latencies(self) -> None:
        result = RunResult(
            (
                RequestSample(0, True, 200, 10.0),
                RequestSample(1, False, 503, 20.0, "http_503"),
                RequestSample(2, True, 200, 30.0),
            ),
            1.5,
        )

        summary = summarize(result)

        self.assertEqual(summary["completed_requests"], 3)
        self.assertEqual(summary["successful_requests"], 2)
        self.assertEqual(summary["failed_requests"], 1)
        self.assertEqual(summary["latency_ms_successful_requests"]["max"], 30.0)
        self.assertEqual(summary["status_codes"], {"200": 2, "503": 1})
        self.assertEqual(summary["errors"], {"http_503": 1})

    def test_artifacts_are_stable_ordered_and_do_not_contain_api_key(self) -> None:
        args = argparse.Namespace(
            base_url="http://localhost:8000",
            workspace_id="workspace",
            query="query",
            top_k=5,
            rerank=True,
            concurrency=2,
            warmup=0,
            timeout=10.0,
            duration=None,
            requests=2,
            hardware_note="test machine",
        )
        measured = RunResult(
            (
                RequestSample(1, True, 200, 2.0),
                RequestSample(0, True, 200, 1.0),
            ),
            0.5,
        )
        report = build_report(
            repository=Path("/does/not/exist"),
            args=args,
            warmup=RunResult((), 0.0),
            measured=measured,
            api_key_configured=True,
        )

        with TemporaryDirectory() as directory:
            output = Path(directory)
            write_artifacts(output, report, measured.samples)
            environment = json.loads((output / "environment.json").read_text())
            lines = (output / "requests.jsonl").read_text().splitlines()
            serialized = "".join(path.read_text() for path in output.iterdir())

        self.assertEqual(environment["environment"]["hardware_note"], "test machine")
        self.assertIn("git_sha", environment["environment"])
        self.assertEqual([json.loads(line)["request_id"] for line in lines], [0, 1])
        self.assertNotIn("secret-api-key", serialized)


class _SearchHandler(BaseHTTPRequestHandler):
    payloads: ClassVar[list[dict[str, Any]]] = []
    payload_lock: ClassVar[threading.Lock] = threading.Lock()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        with self.payload_lock:
            self.payloads.append(payload)
        body = b'{"results":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class LoadBenchmarkHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        _SearchHandler.payloads = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _SearchHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_search_requester_sends_read_only_workload(self) -> None:
        requester = SearchRequester(
            base_url=f"http://127.0.0.1:{self.server.server_port}",
            workspace_id="workspace-id",
            query="metrics",
            top_k=3,
            rerank=False,
            timeout_seconds=2,
            api_key=None,
        )

        result = run_request_count(6, 3, requester)

        self.assertTrue(all(sample.success for sample in result.samples))
        self.assertEqual(len(_SearchHandler.payloads), 6)
        self.assertTrue(
            all(
                payload
                == {
                    "workspace_id": "workspace-id",
                    "query": "metrics",
                    "top_k": 3,
                    "rerank": False,
                }
                for payload in _SearchHandler.payloads
            )
        )


if __name__ == "__main__":
    unittest.main()

