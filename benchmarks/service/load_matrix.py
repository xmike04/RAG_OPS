"""Controlled mixed-query load and process endpoint-resource measurements."""
from __future__ import annotations

import argparse
import hashlib
import math
import re
import subprocess
from datetime import datetime, timezone
from http.client import HTTPException
from urllib.request import Request, urlopen
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from benchmarks.retrieval.src.retrieval_benchmark.dataset import load_queries, load_qrels
from benchmarks.service.core import percentiles, validate_runtime, verify_manifest
from benchmarks.service.run import HTTPClient, evaluate_queries, write_json

ROOT = Path(__file__).resolve().parents[2]


def process_snapshot(pid: int | None) -> dict | None:
    if pid is None:
        return None
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
        return {"pid": pid, "started_ticks": int(fields[19]),
                "cpu_ticks": int(fields[11]) + int(fields[12]),
                "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGESIZE")}
    except (OSError, ValueError, IndexError):
        return None


def resource_delta(before: dict | None, after: dict | None, *, elapsed: float,
                   ticks_per_second: int) -> dict | None:
    if (before is None or after is None or elapsed <= 0 or ticks_per_second <= 0
            or before["started_ticks"] != after["started_ticks"]
            or after["cpu_ticks"] < before["cpu_ticks"]):
        return None
    seconds = (after["cpu_ticks"] - before["cpu_ticks"]) / ticks_per_second
    return {"cpu_seconds": seconds, "mean_cpu_percent_one_core": 100 * seconds / elapsed,
            "rss_start_bytes": before["rss_bytes"], "rss_end_bytes": after["rss_bytes"],
            "process_start_ticks": before["started_ticks"],
            "sampling": "CPU tick delta over the request window; two RSS endpoints, not peak RSS"}


def run_condition(client, queries: list[dict], qrels: dict, document_map: dict,
                  workspace_id: str, *, runtime: dict | None, concurrency: int,
                  requests: int, warmup: int, api_pid: int | None = None,
                  worker_pid: int | None = None) -> dict:
    if concurrency < 1 or requests < 1 or warmup < 0 or not queries:
        raise ValueError("positive concurrency/requests and a nonempty query mix are required")

    def one(index: int) -> dict:
        query = queries[index % len(queries)]
        row = evaluate_queries(client, [query], qrels, document_map, workspace_id,
                               top_k=100, rerank=False, runtime=runtime)[0]
        if not row.get("error") and row["returned_chunks"] == 0:
            row["error"] = "EmptySearchResult"
        return {"request_index": index, "query_id": row["query_id"],
                "elapsed_ms": row["elapsed_ms"], "error": row.get("error"),
                "returned_chunks": row.get("returned_chunks"), "stage_ms": row.get("stage_ms", {})}

    warm_rows = [one(index) for index in range(warmup)]
    before = {"api": process_snapshot(api_pid), "worker": process_snapshot(worker_pid)}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        rows = list(executor.map(one, range(requests)))
    elapsed = time.perf_counter() - started
    after = {"api": process_snapshot(api_pid), "worker": process_snapshot(worker_pid)}
    successful = [row for row in rows if not row["error"]]
    errors = {}
    for row in rows:
        if row["error"]:
            errors[row["error"]] = errors.get(row["error"], 0) + 1
    ticks = os.sysconf("SC_CLK_TCK")
    stages = sorted({key for row in successful for key in row["stage_ms"]})
    warm_errors = {}
    for row in warm_rows:
        if row["error"]:
            warm_errors[row["error"]] = warm_errors.get(row["error"], 0) + 1
    return {
        "warmup": {"attempted": warmup, "failed": sum(bool(row["error"]) for row in warm_rows),
                   "errors": warm_errors, "records": warm_rows},
        "summary": {
            "concurrency": concurrency, "attempted": requests, "successful": len(successful),
            "failed": requests - len(successful), "errors": errors, "elapsed_seconds": elapsed,
            "completed_requests_per_second": requests / elapsed,
            "successful_requests_per_second": len(successful) / elapsed,
            "latency_ms_successful": percentiles([row["elapsed_ms"] for row in successful]),
            "stage_latency_ms_successful": {
                key: percentiles([row["stage_ms"][key] for row in successful if key in row["stage_ms"]])
                for key in stages
            },
        },
        "process_resources": {
            name: resource_delta(before[name], after[name], elapsed=elapsed, ticks_per_second=ticks)
            for name in before
        },
        "process_snapshots": {"before": before, "after": after, "clock_ticks_per_second": ticks},
        "per_request": rows,
        "load_model": "closed-loop worker threads; request latency excludes client executor queue time",
        "connection_policy": "urllib request per operation; no explicit client connection pool",
    }



def parse_search_request_count(metrics: str) -> int:
    if "# TYPE ragops_http_requests_total counter" not in metrics.splitlines():
        raise ValueError("request-counter instrument is missing")
    total = 0
    for labels, raw in re.findall(r"^ragops_http_requests_total\{([^}]*)\}\s+([0-9.eE+-]+)\s*$", metrics, re.MULTILINE):
        if re.search(r'(?:^|,)method="POST"(?:,|$)', labels) and re.search(r'(?:^|,)route="/v1/search"(?:,|$)', labels):
            count = float(raw)
            if not math.isfinite(count) or count < 0 or not count.is_integer():
                raise ValueError("invalid search-request counter")
            total += int(count)
    return total


def read_search_request_count(client) -> int:
    headers = {}
    if os.environ.get("RAGOPS_API_KEY"):
        headers["X-API-Key"] = os.environ["RAGOPS_API_KEY"]
    with urlopen(Request(client.base_url + "/metrics", headers=headers), timeout=client.timeout) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("metrics response exceeds the inspection bound")
    return parse_search_request_count(raw.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ingest-dir", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--sample-queries", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--api-pid", type=int)
    parser.add_argument("--worker-pid", type=int)
    parser.add_argument("--phase", choices=["warm", "first-search-after-api-restart"], default="warm")
    args = parser.parse_args()
    if args.phase != "warm" and (args.concurrency != 1 or args.requests != 1 or args.warmup != 0 or not args.api_pid):
        parser.error("first-search condition needs one request, concurrency 1, no warmup, and an observed API PID")
    if args.output.exists():
        raise FileExistsError("output already exists; retain every measured condition")
    protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
    dataset = ROOT / "benchmarks/datasets/scifact/v1"
    hashes = verify_manifest(dataset, protocol["dataset_manifest_sha256"])
    ingested = json.loads((args.ingest_dir / "ingest.json").read_text())
    if ingested["dataset_hashes"] != hashes:
        raise ValueError("ingested dataset differs from the frozen query mix")
    runtime = json.loads(args.runtime.read_text())
    validate_runtime(runtime, request_top_k=100)
    if (runtime["corpus"]["workspace_id"] != ingested["workspace_id"]
            or runtime["corpus"]["indexed_documents"] != len(ingested["document_map"])):
        raise ValueError("runtime corpus differs from the completed ingestion")
    qrels = load_qrels(dataset / "qrels/train.tsv")
    all_queries = {query.query_id: query.text for query in load_queries(dataset / "queries.jsonl")}
    if not 1 <= args.sample_queries <= len(qrels):
        parser.error("sample query count is outside the training split")
    ids = random.Random(args.seed).sample(sorted(qrels), args.sample_queries)
    queries = [{"_id": query_id, "text": all_queries[query_id]} for query_id in ids]
    client = HTTPClient(args.base_url)
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    context = {
        "measurement_utc": datetime.now(timezone.utc).isoformat(),
        "serving_source_revision": runtime["source_revision"],
        "harness_git_revision": git.stdout.strip() if git.returncode == 0 else None,
        "harness_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    initial_process, initial_count = None, None

    def reject_before(reason):
        result = {"schema_version": 1, "phase": args.phase, "observation_status": "invalid",
                  "invalid_reason": reason, "process_identity_before": initial_process,
                  "search_counter_before": initial_count, "per_request": [],
                  "summary": {"requested": args.requests, "attempted": 0, "successful": 0, "failed": 0},
                  **context}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, result)
        print(json.dumps(result, allow_nan=False))
        return 1

    if args.phase != "warm":
        initial_process = process_snapshot(args.api_pid)
        if initial_process is None:
            return reject_before("APIProcessUnavailableBeforeSearch")
        try:
            initial_count = read_search_request_count(client)
        except (OSError, ValueError, HTTPException):
            return reject_before("SearchCounterUnavailableBeforeSearch")
        if initial_count != 0:
            return reject_before("APIHasAlreadyProcessedSearches")

    result = run_condition(client, queries, qrels, ingested["document_map"],
                           ingested["workspace_id"], runtime=runtime, concurrency=args.concurrency,
                           requests=args.requests, warmup=args.warmup,
                           api_pid=args.api_pid, worker_pid=args.worker_pid)
    result["observation_status"] = "valid"
    if args.phase != "warm":
        snapshots = result["process_snapshots"]
        identities = [snapshots["before"]["api"], snapshots["after"]["api"]]
        if any(item is None or item["pid"] != initial_process["pid"]
               or item["started_ticks"] != initial_process["started_ticks"] for item in identities):
            result["observation_status"] = "invalid"
            result["invalid_reason"] = "APIProcessChangedDuringSearch"
        try:
            final_count = read_search_request_count(client)
        except (OSError, ValueError, HTTPException):
            final_count = None
        result["restart_observation"] = {"initial_process": initial_process,
                                          "search_counter_before": initial_count,
                                          "search_counter_after": final_count}
        if final_count != 1:
            result["observation_status"] = "invalid"
            result["invalid_reason"] = "SearchCounterDoesNotConfirmExactlyOneSearch"

    result.update({
        "schema_version": 1, "phase": args.phase, "query_split": "train", "query_mix": queries,
        "seed": args.seed, "request_top_k_chunks": 100, "rerank": False,
        "dataset_hashes": hashes, **context,
        "runtime": runtime,
        "limitations": [
            "First-search means a restarted API with ready dependencies; database and OS caches are not cleared.",
            "Closed-loop throughput is not an open-loop arrival-rate or production-capacity SLA.",
            "RSS endpoints do not establish peak memory; CPU is a process tick delta with OS tick resolution.",
            "PostgreSQL/Redis CPU and billing are not attributed to individual requests.",
            "The configuration uses deterministic local providers, not learned inference or generation.",
        ],
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps({"phase": args.phase, "summary": result["summary"],
                      "process_resources": result["process_resources"]}, indent=2, allow_nan=False))
    return 0 if (result["observation_status"] == "valid" and result["summary"]["failed"] == 0
                 and result["warmup"]["failed"] == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
