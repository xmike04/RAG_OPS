"""Verify retained load observations without asserting a performance target."""
from __future__ import annotations

import gzip
import hashlib
import json
import statistics
import unittest
from collections import Counter
from pathlib import Path

from benchmarks.retrieval.src.retrieval_benchmark.dataset import load_qrels

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "benchmarks/service/results/load/2026-10-26-local-40389341425"
SOURCE = "fa5b6fae567d3863eb26af68bd908fc4c8c8f383"


class RetainedLoadEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = json.loads((EVIDENCE / "environment.json").read_text())
        cls.raw = {}
        for name, expected in cls.environment["files_uncompressed_sha256"].items():
            raw = gzip.decompress((EVIDENCE / (name + ".gz")).read_bytes())
            if hashlib.sha256(raw).hexdigest() != expected:
                raise AssertionError(f"retained load checksum mismatch: {name}")
            if name.endswith(".json"):
                cls.raw[name] = json.loads(raw)
        cls.summary = json.loads((EVIDENCE / "summary.json").read_text())

    def test_dataset_and_measurement_provenance_are_retained(self):
        self.assertEqual(self.summary, self.raw["summary.json"])
        self.assertEqual(self.environment["source_revision"], SOURCE)
        self.assertFalse(self.environment["tracked_source_dirty"])
        runtime, ingest = self.raw["runtime.json"], self.raw["ingest.json"]
        self.assertEqual(runtime["source_revision"], SOURCE)
        self.assertEqual(runtime["corpus"]["indexed_documents"], len(ingest["document_map"]))
        self.assertEqual(len(ingest["document_map"]), 5183)
        self.assertEqual(len(set(ingest["document_map"].values())), 5183)
        self.assertEqual(runtime["corpus"]["chunks"], 5887)
        self.assertEqual(runtime["query_embedding"], runtime["ingestion_embedding"])

    def test_warm_counts_latencies_and_resources_recompute_from_raw_rows(self):
        train_ids = set(load_qrels(ROOT / "benchmarks/datasets/scifact/v1/qrels/train.tsv"))
        mixes = []
        for concurrency in (1, 4, 8):
            row = self.raw[f"warm-c{concurrency}.json"]
            self.assertEqual(row["observation_status"], "valid")
            self.assertEqual(row["harness_git_revision"], SOURCE)
            self.assertEqual(row["harness_source_sha256"], hashlib.sha256(
                (ROOT / "benchmarks/service/load_matrix.py").read_bytes()).hexdigest())
            mix = [query["_id"] for query in row["query_mix"]]
            self.assertEqual(len(set(mix)), 30)
            self.assertLessEqual(set(mix), train_ids)
            mixes.append(mix)
            records, summary = row["per_request"], row["summary"]
            self.assertEqual(summary["concurrency"], concurrency)
            self.assertEqual(len(records), 300)
            self.assertEqual([item["request_index"] for item in records], list(range(300)))
            self.assertEqual([item["query_id"] for item in records], mix * 10)
            errors = Counter(item["error"] for item in records if item["error"])
            self.assertEqual(summary["errors"], dict(errors))
            successful = [item for item in records if not item["error"]]
            self.assertEqual(summary["successful"], len(successful))
            self.assertEqual(summary["failed"], sum(errors.values()))
            self.assertEqual(summary["attempted"], len(records))
            self.assertEqual(len(row["warmup"]["records"]), 30)
            self.assertEqual(row["warmup"]["errors"], dict(Counter(
                item["error"] for item in row["warmup"]["records"] if item["error"])))
            self.assertAlmostEqual(summary["successful_requests_per_second"],
                                   len(successful) / summary["elapsed_seconds"], places=10)
            values = [item["elapsed_ms"] for item in successful]
            if values:
                quantiles = statistics.quantiles(values, n=100, method="inclusive")
                for name, index in (("p50", 49), ("p95", 94), ("p99", 98)):
                    self.assertAlmostEqual(summary["latency_ms_successful"][name],
                                           quantiles[index], places=8)
                self.assertTrue(all(item["returned_chunks"] > 0 for item in successful))
            snapshots = row["process_snapshots"]
            for process, resources in row["process_resources"].items():
                before, after = snapshots["before"][process], snapshots["after"][process]
                self.assertEqual(before["pid"], after["pid"])
                self.assertEqual(before["started_ticks"], after["started_ticks"])
                seconds = (after["cpu_ticks"] - before["cpu_ticks"]) / snapshots["clock_ticks_per_second"]
                self.assertAlmostEqual(resources["cpu_seconds"], seconds, places=12)
                self.assertAlmostEqual(resources["mean_cpu_percent_one_core"],
                                       100 * seconds / summary["elapsed_seconds"], places=10)
                self.assertEqual(resources["rss_start_bytes"], before["rss_bytes"])
                self.assertEqual(resources["rss_end_bytes"], after["rss_bytes"])
                self.assertNotIn("peak_rss_bytes", resources)
        self.assertEqual(mixes[0], mixes[1])
        self.assertEqual(mixes[0], mixes[2])

    def test_first_searches_have_distinct_continuous_processes_and_counter_proof(self):
        identities = set()
        for seed in range(5):
            row = self.raw[f"first-{seed}.json"]
            self.assertEqual(row["observation_status"], "valid")
            self.assertEqual(row["summary"]["attempted"], 1)
            self.assertEqual(row["warmup"]["attempted"], 0)
            observation = row["restart_observation"]
            self.assertEqual(observation["search_counter_before"], 0)
            self.assertEqual(observation["search_counter_after"], 1)
            initial = observation["initial_process"]
            identities.add((initial["pid"], initial["started_ticks"]))
            for snapshot in ("before", "after"):
                process = row["process_snapshots"][snapshot]["api"]
                self.assertEqual((process["pid"], process["started_ticks"]),
                                 (initial["pid"], initial["started_ticks"]))
        self.assertEqual(len(identities), 5)


if __name__ == "__main__":
    unittest.main()
