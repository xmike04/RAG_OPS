"""SciFact ingestion and actual /v1/search evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from benchmarks.retrieval.src.retrieval_benchmark.dataset import load_documents, load_queries, load_qrels
from benchmarks.service.core import aggregate, paired_comparison, score_response, validate_runtime, verify_manifest

ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


class HTTPClient:
    """Only local/tunnel targets; credentials and response error bodies are never retained."""

    def __init__(self, base_url: str, *, timeout: float = 30.0):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("benchmark target must be a loopback HTTP origin")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if os.environ.get("RAGOPS_API_KEY"):
            headers["X-API-Key"] = os.environ["RAGOPS_API_KEY"]
        body = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"HTTP_{error.code}") from None
        if not isinstance(result, dict):
            raise ValueError("API response must be an object")
        return result


def ingest_documents(client, documents: list[dict], workspace_id: str, *, timeout: float = 900,
                     on_submission=None) -> dict[str, str]:
    listing = "/v1/documents?" + urlencode({"workspace_id": workspace_id, "limit": 200})
    if client.request("GET", listing)["total"] != 0:
        raise ValueError("benchmark requires a new empty workspace")
    mapping, jobs = {}, []
    for document in documents:
        original = str(document["_id"])
        payload = {
            "workspace_id": workspace_id, "title": document["title"] or original,
            "content": "\n\n".join(part for part in (document["title"].strip(), document["text"].strip()) if part),
            "source_uri": f"urn:scifact:{original}",
            "metadata": {"scifact_doc_id": original, "benchmark_dataset": "BEIR SciFact", "content_format": "text"},
        }
        accepted = client.request("POST", "/v1/documents", payload)
        document_id, job_id = accepted["document"]["id"], accepted["ingestion_job_id"]
        if document_id in mapping or original in mapping.values():
            raise ValueError("duplicate document identity during ingestion")
        mapping[document_id] = original
        jobs.append(job_id)
        if on_submission:
            on_submission({"document_id": document_id, "scifact_doc_id": original, "job_id": job_id})
    deadline = time.monotonic() + timeout
    for job_id in jobs:
        while True:
            job = client.request("GET", f"/v1/ingestions/{job_id}?" + urlencode({"workspace_id": workspace_id}))
            if job["status"] == "completed":
                break
            if job["status"] == "failed":
                raise ValueError("ingestion failed; inspect the local job without publishing its raw error")
            if time.monotonic() >= deadline:
                raise TimeoutError("ingestion did not complete before its deadline")
            time.sleep(.25)
    found = {}
    offset = 0
    while True:
        page = client.request("GET", listing + "&" + urlencode({"offset": offset}))
        if page["total"] != len(documents):
            raise ValueError("workspace corpus count changed during ingestion")
        for item in page["items"]:
            if item["status"] != "completed":
                raise ValueError("document is not completed (possibly duplicate); corpus semantics would differ")
            if item["id"] in found:
                raise ValueError("duplicate document in paginated corpus listing")
            found[item["id"]] = item["metadata"]["scifact_doc_id"]
        offset += len(page["items"])
        if offset >= page["total"]:
            break
        if not page["items"]:
            raise ValueError("incomplete paginated corpus listing")
    if found != mapping:
        raise ValueError("stored corpus identities differ from submissions")
    return mapping


def evaluate_queries(client, queries: list[dict], qrels: dict, document_map: dict,
                     workspace_id: str, *, top_k: int, rerank: bool, on_result=None) -> list[dict]:
    records = []
    for query in queries:
        started = time.perf_counter()
        try:
            response = client.request("POST", "/v1/search", {
                "workspace_id": workspace_id, "query": query["text"], "top_k": top_k, "rerank": rerank,
            })
            elapsed = (time.perf_counter() - started) * 1000
            record = score_response(query["_id"], response, qrels[query["_id"]], document_map, elapsed_ms=elapsed)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
            record = {"query_id": query["_id"], "error": type(error).__name__,
                      "elapsed_ms": (time.perf_counter() - started) * 1000}
        records.append(record)
        if on_result:
            on_result(record)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["ingest", "evaluate"])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "benchmarks/datasets/scifact/v1")
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("protocol.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, help="post-ingestion capture from the actual API container")
    parser.add_argument("--split", choices=["train", "test"], default="train")
    parser.add_argument("--final-test", action="store_true", help="explicitly evaluate the held-out test split; never tune on it")
    parser.add_argument("--baseline", type=Path, help="compatible prior evaluation.json for paired query analysis")
    args = parser.parse_args()
    if args.split == "test" and not args.final_test:
        parser.error("held-out evaluation requires --final-test after configuration is frozen")
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    hashes = verify_manifest(args.dataset_dir, protocol["dataset_manifest_sha256"])
    required = {"corpus.jsonl", "queries.jsonl", "qrels/train.tsv", "qrels/test.tsv", "metadata.json"}
    if hashes.keys() != required:
        raise ValueError("protocol requires every canonical SciFact input file")
    metadata = json.loads((args.dataset_dir / "metadata.json").read_text())
    documents = [{"_id": doc.doc_id, "title": doc.title, "text": doc.text}
                 for doc in load_documents(args.dataset_dir / "corpus.jsonl")]
    if len(documents) != metadata["records"]["corpus"]:
        raise ValueError("corpus count differs from the dataset metadata")
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    client = HTTPClient(args.base_url)
    if args.mode == "ingest":
        args.output_dir.mkdir(parents=True, exist_ok=False)
        workspace = str(uuid.uuid4())
        progress = args.output_dir / "ingestion-submissions.jsonl"
        with progress.open("x", encoding="utf-8") as stream:
            def submitted(row):
                stream.write(json.dumps(row, allow_nan=False) + "\n")
                stream.flush()
            mapping = ingest_documents(client, documents, workspace, on_submission=submitted)
        write_json(args.output_dir / "ingest.json", {
            "workspace_id": workspace, "document_map": mapping,
            "dataset_fingerprint": fingerprint, "dataset_hashes": hashes,
            "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        })
        print(json.dumps({"workspace_id": workspace, "documents": len(mapping), "status": "ingested"}))
        return 0
    if args.runtime is None:
        parser.error("evaluation requires --runtime captured after ingestion")
    ingested = json.loads((args.output_dir / "ingest.json").read_text())
    if (ingested["dataset_fingerprint"] != fingerprint
            or ingested["protocol_sha256"] != hashlib.sha256(protocol_bytes).hexdigest()):
        raise ValueError("dataset or protocol changed after ingestion")
    runtime = json.loads(args.runtime.read_text())
    validate_runtime(runtime, request_top_k=protocol["request_top_k"])
    corpus = runtime["corpus"]
    if (corpus["workspace_id"] != ingested["workspace_id"] or corpus["documents"] != len(documents)
            or corpus["indexed_documents"] != len(documents) or corpus["chunks"] < len(documents)):
        raise ValueError("runtime corpus or indexed document coverage differs from the canonical corpus")
    if any(runtime["settings"][key] != value for key, value in protocol["settings"].items()):
        raise ValueError("runtime settings differ from the frozen protocol")
    qrels = load_qrels(args.dataset_dir / "qrels" / f"{args.split}.tsv")
    all_queries = {query.query_id: query.text for query in load_queries(args.dataset_dir / "queries.jsonl")}
    if set(qrels) - all_queries.keys():
        raise ValueError("qrels reference missing queries")
    if {doc for rels in qrels.values() for doc in rels} - set(ingested["document_map"].values()):
        raise ValueError("qrels reference missing documents")
    expected = metadata["records"][f"{args.split}_queries_with_qrels"]
    if len(qrels) != expected:
        raise ValueError("evaluated query count differs from canonical metadata")
    queries = [{"_id": key, "text": all_queries[key]} for key in sorted(qrels)]
    output = args.output_dir / args.split
    output.mkdir(exist_ok=False)
    with (output / "per_query.jsonl").open("x", encoding="utf-8") as stream:
        def retained(row):
            stream.write(json.dumps(row, allow_nan=False) + "\n")
            stream.flush()
        records = evaluate_queries(client, queries, qrels, ingested["document_map"],
                                   ingested["workspace_id"], top_k=protocol["request_top_k"],
                                   rerank=protocol["rerank"], on_result=retained)
    summary = aggregate(records, [query["_id"] for query in queries])
    report = {
        "schema_version": 1, "boundary": "HTTP /v1/search; no generation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_fingerprint": fingerprint, "dataset_hashes": hashes, "split": args.split,
        "protocol": protocol, "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "runtime": runtime, "client": {"python": platform.python_version(), "platform": platform.platform()},
        "summary": summary, "per_query": records,
        "limitations": ["At most 100 returned chunks; Recall@100 is computed over the deduplicated returned window.",
                        "First-request and warm timings are mixed; this is not a cold-start or concurrent load study.",
                        "Cost, CPU/RSS samples, and answer quality are not measured by this evaluation."],
    }
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        report["paired_analysis"] = {
            metric: paired_comparison(report, baseline, metric, seed=protocol["seed"])
            for metric in ("recall@10", "ndcg@10")
        }
    write_json(output / "evaluation.json", report)
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0 if summary["complete_without_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
