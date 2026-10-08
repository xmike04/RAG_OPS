"""Credential-free smoke checks for a running RAGOps API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class Response:
    status: int
    headers: Any
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def request(base_url: str, path: str, headers: dict[str, str]) -> Response:
    req = urllib.request.Request(base_url.rstrip("/") + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as result:
            return Response(result.status, result.headers, result.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.headers, exc.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--workspace-id", default="00000000-0000-0000-0000-000000000001"
    )
    args = parser.parse_args()
    headers = {
        "Accept": "application/json",
        "X-Request-ID": "ragops-smoke-check",
    }
    failures: list[str] = []

    for path in ("/health", "/ready"):
        response = request(args.base_url, path, headers)
        if response.status != 200:
            failures.append(f"GET {path}: expected 200, got {response.status}")
            continue
        try:
            payload = response.json()
        except (UnicodeDecodeError, json.JSONDecodeError):
            failures.append(f"GET {path}: response is not JSON")
            continue
        if not isinstance(payload, dict):
            failures.append(f"GET {path}: expected a JSON object")
        if not response.headers.get("X-Request-ID"):
            failures.append(f"GET {path}: missing X-Request-ID response header")

    metrics = request(args.base_url, "/metrics", headers)
    if metrics.status != 200:
        failures.append(f"GET /metrics: expected 200, got {metrics.status}")
    elif b"# HELP" not in metrics.body and b"# TYPE" not in metrics.body:
        failures.append("GET /metrics: response is not Prometheus exposition")

    openapi = request(args.base_url, "/openapi.json", headers)
    if openapi.status != 200:
        failures.append(f"GET /openapi.json: expected 200, got {openapi.status}")
    else:
        try:
            paths = openapi.json().get("paths", {})
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            paths = {}
        required = {
            "/health",
            "/ready",
            "/v1/documents",
            "/v1/ingestions/{job_id}",
            "/v1/search",
            "/v1/query",
            "/v1/traces",
            "/v1/ops/summary",
        }
        missing = sorted(required - set(paths))
        if missing:
            failures.append(f"OpenAPI is missing required paths: {', '.join(missing)}")

    query_string = urllib.parse.urlencode(
        {"workspace_id": args.workspace_id, "limit": 1, "offset": 0}
    )
    documents = request(args.base_url, f"/v1/documents?{query_string}", headers)
    if documents.status != 200:
        failures.append(
            f"GET /v1/documents: expected 200, got {documents.status}"
        )
    else:
        try:
            collection = documents.json()
        except (UnicodeDecodeError, json.JSONDecodeError):
            collection = None
        if not isinstance(collection, dict) or not isinstance(
            collection.get("items"), list
        ):
            failures.append("GET /v1/documents: expected an object with an items list")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"PASS API smoke checks at {args.base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
