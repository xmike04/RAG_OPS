#!/usr/bin/env python3
"""Run a small, read-only smoke test against a running RAGOps API."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_URL = os.getenv("RAGOPS_API_URL", "http://localhost:8000").rstrip("/")
WORKSPACE_ID = os.getenv(
    "RAGOPS_DEFAULT_WORKSPACE_ID", "00000000-0000-0000-0000-000000000001"
)
API_KEY = os.getenv("RAGOPS_API_KEY")


def fetch(path: str, *, expect_json: bool = True) -> Any:
    headers = {"Accept": "application/json" if expect_json else "text/plain"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    request = urllib.request.Request(f"{API_URL}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"GET {path} returned HTTP {error.code}: {detail}") from error
    return json.loads(payload) if expect_json else payload.decode()


def require_status(payload: Any, accepted: set[str], endpoint: str) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError(f"{endpoint} did not return a JSON object")
    status = str(payload.get("status", "")).lower()
    if status not in accepted:
        raise RuntimeError(f"{endpoint} returned unexpected status {status!r}")


def main() -> int:
    require_status(fetch("/health"), {"ok", "healthy"}, "/health")
    require_status(fetch("/ready"), {"ok", "ready", "healthy"}, "/ready")

    metrics = fetch("/metrics", expect_json=False)
    for metric in ("ragops_http_requests_total", "ragops_http_request_duration_seconds"):
        if metric not in metrics:
            raise RuntimeError(f"/metrics did not expose {metric}")

    query = urllib.parse.urlencode({"workspace_id": WORKSPACE_ID, "limit": 1, "offset": 0})
    documents = fetch(f"/v1/documents?{query}")
    if not isinstance(documents, (dict, list)):
        raise RuntimeError("/v1/documents did not return a JSON collection")

    print("smoke checks passed: health, readiness, metrics, and document listing")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"smoke failed: {error}", file=sys.stderr)
        sys.exit(1)

