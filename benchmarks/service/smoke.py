"""Exercise real HTTP/database/worker wiring with a tiny public-text fixture."""

import time
import uuid
import json

from benchmarks.service.core import aggregate
from benchmarks.service.load_matrix import read_search_request_count
from benchmarks.service.run import HTTPClient, evaluate_queries, ingest_documents


def main() -> None:
    client = HTTPClient("http://127.0.0.1:8010", timeout=5)
    deadline = time.monotonic() + 45
    while True:
        try:
            client.request("GET", "/ready")
            break
        except (OSError, RuntimeError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.25)
    documents = [
        {"_id": "fixture-rrf", "title": "Reciprocal rank fusion", "text": "Reciprocal rank fusion combines ranked lexical and vector search results."},
        {"_id": "fixture-queue", "title": "Ingestion queue", "text": "Redis queues asynchronous document ingestion jobs for the worker."},
    ]
    queries = [{"_id": "q1", "text": "reciprocal rank fusion"}, {"_id": "q2", "text": "Redis ingestion queue"}]
    workspace = str(uuid.uuid4())
    mapping = ingest_documents(client, documents, workspace, timeout=30)
    search_count_before = read_search_request_count(client)
    records = evaluate_queries(client, queries, {"q1": {"fixture-rrf": 1}, "q2": {"fixture-queue": 1}},
                               mapping, workspace, top_k=10, rerank=False)
    if read_search_request_count(client) - search_count_before != len(queries):
        raise RuntimeError("real HTTP search-request counter does not match accepted requests")
    result = aggregate(records, ["q1", "q2"])
    if not result["complete_without_errors"] or result["quality_all_queries"]["recall@10"] != 1:
        raise RuntimeError("real serving-path fixture failed; inspect CI service logs")
    print(json.dumps({"evidence_class": "two-document integration fixture, not a SciFact performance result", "summary": result}, indent=2))


if __name__ == "__main__":
    main()
