from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evals.evaluate import EvaluationError, evaluate, load_jsonl

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "evals" / "datasets" / "queries.jsonl"
CORPUS = ROOT / "evals" / "datasets" / "corpus.jsonl"
REFERENCE = ROOT / "evals" / "runs" / "reference.jsonl"


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queries = load_jsonl(QUERIES)
        self.corpus = load_jsonl(CORPUS)
        self.run = load_jsonl(REFERENCE)

    def test_reference_metrics_are_deterministic(self) -> None:
        report = evaluate(self.queries, self.corpus, self.run, [1, 3, 5])

        self.assertEqual(report["query_count"], 8)
        self.assertAlmostEqual(report["retrieval"]["recall@1"], 0.5625)
        self.assertAlmostEqual(report["retrieval"]["recall@3"], 1.0)
        self.assertAlmostEqual(report["retrieval"]["mrr"], 0.8125)
        self.assertAlmostEqual(
            report["retrieval"]["ndcg@3"], 0.85156375623282
        )
        self.assertAlmostEqual(report["citations"]["coverage"], 8 / 9)
        self.assertAlmostEqual(report["citations"]["validity"], 1.0)
        self.assertEqual(report["latency_ms"]["p50"], 10.0)
        self.assertEqual(report["latency_ms"]["p95"], 16.0)

    def test_mismatched_query_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(EvaluationError, "run/query mismatch"):
            evaluate(self.queries, self.corpus, self.run[:-1], [3])

    def test_unknown_result_chunk_is_rejected(self) -> None:
        changed = json.loads(json.dumps(self.run))
        changed[0]["results"][0]["chunk_id"] = "does-not-exist"

        with self.assertRaisesRegex(EvaluationError, "unknown result chunks"):
            evaluate(self.queries, self.corpus, changed, [3])

    def test_invalid_citation_counts_as_invalid_and_unsupported(self) -> None:
        changed = json.loads(json.dumps(self.run))
        changed[0]["answer"]["claims"][0]["citations"] = ["does-not-exist"]

        report = evaluate(self.queries, self.corpus, changed, [3])

        self.assertLess(report["citations"]["validity"], 1.0)
        self.assertLess(
            report["citations"]["faithfulness_proxy"],
            evaluate(self.queries, self.corpus, self.run, [3])["citations"][
                "faithfulness_proxy"
            ],
        )

    def test_cli_quality_floor_exit_codes(self) -> None:
        command = [
            sys.executable,
            str(ROOT / "evals" / "evaluate.py"),
            "--queries",
            str(QUERIES),
            "--corpus",
            str(CORPUS),
            "--run",
            str(REFERENCE),
        ]
        passing = subprocess.run(
            [*command, "--fail-below", "retrieval.recall@3=1.0"],
            capture_output=True,
            text=True,
            check=False,
        )
        failing = subprocess.run(
            [*command, "--fail-below", "retrieval.recall@1=0.9"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(passing.returncode, 0, passing.stderr)
        self.assertEqual(failing.returncode, 1)
        self.assertIn("quality gate failed", failing.stderr)

    def test_loader_reports_json_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text('{"ok": true}\nnot-json\n', encoding="utf-8")
            with self.assertRaisesRegex(EvaluationError, r":2: invalid JSON"):
                load_jsonl(path)


if __name__ == "__main__":
    unittest.main()
