"""Independently check retained serving evidence against source IDs and official qrels."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import unittest
from pathlib import Path

from benchmarks.retrieval.src.retrieval_benchmark.dataset import load_documents, load_qrels
from benchmarks.service.core import verify_manifest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "benchmarks/service/results/scifact/2026-10-26-local-40380993127"
DATASET = ROOT / "benchmarks/datasets/scifact/v1"


class RetainedServingEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = json.loads((EVIDENCE / "environment.json").read_text())
        cls.raw = {}
        for name, expected in cls.environment["files_uncompressed_sha256"].items():
            raw = gzip.decompress((EVIDENCE / (name + ".gz")).read_bytes())
            if hashlib.sha256(raw).hexdigest() != expected:
                raise AssertionError(f"retained evidence checksum mismatch: {name}")
            cls.raw[name] = raw
        cls.ingest = json.loads(cls.raw["ingest.json"])
        cls.runtime = json.loads(cls.raw["runtime.json"])
        cls.metadata = json.loads((DATASET / "metadata.json").read_text())
        cls.reports = {split: json.loads(cls.raw[f"{split}/evaluation.json"]) for split in ("train", "test")}

    def test_retained_runtime_and_ingested_corpus_match_the_canonical_input(self):
        documents = {doc.doc_id for doc in load_documents(DATASET / "corpus.jsonl")}
        mapping = self.ingest["document_map"]
        self.assertEqual(set(mapping.values()), documents)
        self.assertEqual(len(mapping), len(documents))
        self.assertEqual(len(documents), self.metadata["records"]["corpus"])
        self.assertEqual(self.runtime["corpus"]["documents"], len(documents))
        self.assertEqual(self.runtime["corpus"]["indexed_documents"], len(documents))
        self.assertGreaterEqual(self.runtime["corpus"]["chunks"], len(documents))
        self.assertFalse(self.environment["tracked_source_dirty"])
        self.assertEqual(self.runtime["source_revision"], self.environment["source_revision"])
        print("RETAINED_RUNTIME " + json.dumps({
            "source": self.environment["source_revision"], "corpus": self.runtime["corpus"],
            "query_embedding": self.runtime["query_embedding"], "chunking": self.runtime["chunking"],
            "postgres": self.runtime["postgres"], "logical_cpu_count_visible": self.environment["logical_cpu_count_visible"],
        }, sort_keys=True))

    def test_each_query_score_and_summary_recompute_from_official_qrels(self):
        mapping = self.ingest["document_map"]
        for split, report in self.reports.items():
            with self.subTest(split=split):
                hashes = verify_manifest(DATASET, report["protocol"]["dataset_manifest_sha256"])
                self.assertEqual(hashes, report["dataset_hashes"])
                self.assertEqual(report["dataset_fingerprint"], self.ingest["dataset_fingerprint"])
                qrels = load_qrels(DATASET / "qrels" / f"{split}.tsv")
                rows = [json.loads(line) for line in self.raw[f"{split}/per_query.jsonl"].splitlines()]
                self.assertEqual(rows, report["per_query"])
                self.assertEqual({row["query_id"] for row in rows}, set(qrels))
                self.assertEqual(len(rows), len(qrels))
                self.assertEqual(len(rows), self.metadata["records"][f"{split}_queries_with_qrels"])
                totals = {"recall@10": 0.0, "recall@100": 0.0, "mrr@10": 0.0, "ndcg@10": 0.0}
                failures = 0
                for row in rows:
                    if row.get("error"):
                        failures += 1
                        continue
                    ranking = []
                    for chunk in row["chunk_to_document"]:
                        original = mapping[chunk["document_id"]]
                        self.assertEqual(original, chunk["scifact_doc_id"])
                        if original not in ranking:
                            ranking.append(original)
                    self.assertEqual(ranking, row["ranked_document_ids"])
                    self.assertEqual(row["returned_chunks"], len(row["chunk_to_document"]))
                    self.assertLessEqual(row["returned_chunks"], report["protocol"]["request_top_k"])
                    rels = {doc: score for doc, score in qrels[row["query_id"]].items() if score > 0}
                    first = next((i for i, doc in enumerate(ranking[:10], 1) if doc in rels), None)
                    dcg = sum((2 ** rels.get(doc, 0) - 1) / math.log2(i + 1) for i, doc in enumerate(ranking[:10], 1))
                    ideal = sum((2 ** score - 1) / math.log2(i + 1) for i, score in enumerate(sorted(rels.values(), reverse=True)[:10], 1))
                    derived = {
                        "recall@10": sum(doc in rels for doc in ranking[:10]) / len(rels),
                        "recall@100": sum(doc in rels for doc in ranking[:100]) / len(rels),
                        "mrr@10": 0.0 if first is None else 1.0 / first,
                        "ndcg@10": dcg / ideal,
                    }
                    for metric, value in derived.items():
                        self.assertAlmostEqual(row["metrics"][metric], value, places=12)
                        totals[metric] += value
                    self.assertEqual(row["providers"]["embedding_provider"], self.runtime["query_embedding"]["provider"])
                    self.assertEqual(row["providers"]["embedding_model"], self.runtime["query_embedding"]["model"])
                self.assertEqual(report["summary"]["failed_queries"], failures)
                self.assertEqual(report["summary"]["successful_queries"], len(rows) - failures)
                for metric, total in totals.items():
                    self.assertAlmostEqual(report["summary"]["quality_all_queries"][metric], total / len(rows), places=12)
                print("RETAINED_SUMMARY " + json.dumps({"split": split, "summary": report["summary"]}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
