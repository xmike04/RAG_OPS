#!/usr/bin/env python3
"""Load deterministic, credential-free sample documents through the public API."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_URL = os.getenv("RAGOPS_API_URL", "http://localhost:8000").rstrip("/")
WORKSPACE_ID = os.getenv(
    "RAGOPS_DEFAULT_WORKSPACE_ID", "00000000-0000-0000-0000-000000000001"
)
API_KEY = os.getenv("RAGOPS_API_KEY")

DOCUMENTS = (
    {
        "title": "RAGOps overview",
        "source_uri": "seed://ragops-overview",
        "content": (
            "RAGOps is an observable retrieval-augmented generation platform. "
            "It combines lexical and vector retrieval using reciprocal-rank fusion, "
            "reranks the shortlist, and returns grounded answers with citations."
        ),
        "metadata": {"dataset": "demo", "topic": "platform"},
    },
    {
        "title": "RAGOps operations guide",
        "source_uri": "seed://operations-guide",
        "content": (
            "Operators inspect query traces, stage latency, token usage, cache behavior, "
            "and ingestion status. Prometheus scrapes the API metrics endpoint and Grafana "
            "provides dashboards for HTTP, retrieval, and ingestion signals."
        ),
        "metadata": {"dataset": "demo", "topic": "operations"},
    },
)


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    request = urllib.request.Request(f"{API_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {error.code}: {detail}") from error


def wait_for_ingestion(job_id: str, timeout_seconds: float = 90) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_status = "queued"
    while time.monotonic() < deadline:
        query = urllib.parse.urlencode({"workspace_id": WORKSPACE_ID})
        job = request_json("GET", f"/v1/ingestions/{job_id}?{query}")
        last_status = str(job.get("status", "unknown")).lower()
        if last_status in {"completed", "succeeded", "ready"}:
            return last_status
        if last_status in {"failed", "error", "dead_letter"}:
            raise RuntimeError(f"ingestion job {job_id} ended with status {last_status}")
        time.sleep(1)
    raise TimeoutError(f"ingestion job {job_id} remained {last_status} after {timeout_seconds}s")


def main() -> int:
    created: list[dict[str, str]] = []
    for document in DOCUMENTS:
        payload = {"workspace_id": WORKSPACE_ID, **document}
        submitted = request_json("POST", "/v1/documents", payload)
        document_data = submitted.get("document", submitted)
        document_id = str(document_data.get("id", submitted.get("document_id", "unknown")))
        job_id = str(submitted.get("ingestion_job_id", submitted.get("job_id", "")))
        if not job_id:
            raise RuntimeError(f"document {document_id} response did not include an ingestion job ID")
        status = wait_for_ingestion(job_id)
        created.append({"document_id": document_id, "job_id": job_id, "status": status})

    print(json.dumps({"workspace_id": WORKSPACE_ID, "documents": created}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        print(f"seed failed: {error}", file=sys.stderr)
        sys.exit(1)

