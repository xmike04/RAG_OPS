#!/usr/bin/env python3
"""Run a concurrent, read-only load test against ``POST /v1/search``."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_QUERY = "How are RAGOps metrics monitored?"


@dataclass(frozen=True, slots=True)
class RequestSample:
    """One measured request, safe to serialize without response contents."""

    request_id: int
    success: bool
    status_code: int | None
    latency_ms: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    """Measured requests and their wall-clock execution time."""

    samples: tuple[RequestSample, ...]
    elapsed_seconds: float


RequestFunction = Callable[[int], RequestSample]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def percentile(values: Sequence[float], quantile: float) -> float | None:
    """Return a deterministic nearest-rank percentile."""

    if not values:
        return None
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


class SearchRequester:
    """Callable that performs one search without retaining response content."""

    def __init__(
        self,
        *,
        base_url: str,
        workspace_id: str,
        query: str,
        top_k: int,
        rerank: bool,
        timeout_seconds: float,
        api_key: str | None,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/v1/search"
        self.timeout_seconds = timeout_seconds
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if api_key:
            self.headers["X-API-Key"] = api_key
        self.body = json.dumps(
            {
                "workspace_id": workspace_id,
                "query": query,
                "top_k": top_k,
                "rerank": rerank,
            },
            separators=(",", ":"),
        ).encode()

    def __call__(self, request_id: int) -> RequestSample:
        started = time.perf_counter()
        request = urllib.request.Request(
            self.url,
            data=self.body,
            headers=self.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response.read()
                status_code = response.status
            success = 200 <= status_code < 300
            error = None if success else f"http_{status_code}"
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            error = f"http_{exc.code}"
            success = False
            exc.close()
        except urllib.error.URLError as exc:
            status_code = None
            reason = exc.reason
            error = "timeout" if isinstance(reason, TimeoutError) else "url_error"
            success = False
        except TimeoutError:
            status_code = None
            error = "timeout"
            success = False
        except OSError:
            status_code = None
            error = "os_error"
            success = False
        elapsed_ms = (time.perf_counter() - started) * 1_000
        return RequestSample(
            request_id=request_id,
            success=success,
            status_code=status_code,
            latency_ms=round(elapsed_ms, 3),
            error=error,
        )


def run_request_count(
    request_count: int,
    concurrency: int,
    request_function: RequestFunction,
) -> RunResult:
    """Run exactly ``request_count`` requests with bounded concurrency."""

    started = time.perf_counter()
    samples: list[RequestSample] = []
    next_request_id = 0
    futures: set[Future[RequestSample]] = set()
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="ragops-load") as executor:
        while next_request_id < min(request_count, concurrency):
            futures.add(executor.submit(request_function, next_request_id))
            next_request_id += 1
        while futures:
            completed, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                samples.append(future.result())
                if next_request_id < request_count:
                    futures.add(executor.submit(request_function, next_request_id))
                    next_request_id += 1
    elapsed = time.perf_counter() - started
    return RunResult(tuple(sorted(samples, key=lambda sample: sample.request_id)), elapsed)


def run_duration(
    duration_seconds: float,
    concurrency: int,
    request_function: RequestFunction,
) -> RunResult:
    """Start requests for a fixed duration, allowing in-flight requests to finish."""

    started = time.perf_counter()
    deadline = started + duration_seconds
    samples: list[RequestSample] = []
    next_request_id = 0
    futures: set[Future[RequestSample]] = set()
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="ragops-load") as executor:
        for _ in range(concurrency):
            futures.add(executor.submit(request_function, next_request_id))
            next_request_id += 1
        while futures:
            completed, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                samples.append(future.result())
                if time.perf_counter() < deadline:
                    futures.add(executor.submit(request_function, next_request_id))
                    next_request_id += 1
    elapsed = time.perf_counter() - started
    return RunResult(tuple(sorted(samples, key=lambda sample: sample.request_id)), elapsed)


def git_metadata(repository: Path) -> tuple[str | None, bool | None]:
    """Return the full local Git SHA and dirty flag without changing the checkout."""

    try:
        revision = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        return revision, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def latency_summary(samples: Sequence[RequestSample]) -> dict[str, float | None]:
    """Summarize successful request latencies in milliseconds."""

    values = [sample.latency_ms for sample in samples if sample.success]
    if not values:
        return {"min": None, "p50": None, "p95": None, "p99": None, "max": None}
    return {
        "min": min(values),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


def summarize(result: RunResult) -> dict[str, Any]:
    """Create aggregate counters and latency statistics for a measured run."""

    successes = sum(sample.success for sample in result.samples)
    completed = len(result.samples)
    status_codes = Counter(
        str(sample.status_code) for sample in result.samples if sample.status_code is not None
    )
    errors = Counter(sample.error for sample in result.samples if sample.error)
    return {
        "completed_requests": completed,
        "successful_requests": successes,
        "failed_requests": completed - successes,
        "success_rate": round(successes / completed, 6) if completed else 0.0,
        "elapsed_seconds": round(result.elapsed_seconds, 6),
        "throughput_requests_per_second": (
            round(completed / result.elapsed_seconds, 3) if result.elapsed_seconds else 0.0
        ),
        "latency_ms_successful_requests": latency_summary(result.samples),
        "status_codes": dict(sorted(status_codes.items())),
        "errors": dict(sorted(errors.items())),
    }


def build_report(
    *,
    repository: Path,
    args: argparse.Namespace,
    warmup: RunResult,
    measured: RunResult,
    api_key_configured: bool,
) -> dict[str, Any]:
    """Build the self-describing, machine-readable benchmark report."""

    git_sha, git_dirty = git_metadata(repository)
    mode = (
        {"duration_seconds": args.duration}
        if args.duration is not None
        else {"request_count": args.requests}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "ragops-search-http",
        "environment": {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "git_sha": git_sha,
            "git_dirty": git_dirty,
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
            "hardware_note": args.hardware_note,
        },
        "config": {
            "base_url": args.base_url.rstrip("/"),
            "endpoint": "/v1/search",
            "workspace_id": args.workspace_id,
            "query": args.query,
            "top_k": args.top_k,
            "rerank": args.rerank,
            "concurrency": args.concurrency,
            "warmup_requests": args.warmup,
            "timeout_seconds": args.timeout,
            "api_key_configured": api_key_configured,
            **mode,
        },
        "warmup": summarize(warmup),
        "summary": summarize(measured),
    }


def write_artifacts(
    output_dir: Path,
    report: dict[str, Any],
    samples: Sequence[RequestSample],
) -> None:
    """Write stable-order environment, request, and summary artifacts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    environment = {
        "schema_version": report["schema_version"],
        "benchmark": report["benchmark"],
        "environment": report["environment"],
        "config": report["config"],
    }
    (output_dir / "environment.json").write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        json.dumps(asdict(sample), sort_keys=True)
        for sample in sorted(samples, key=lambda sample: sample.request_id)
    ]
    (output_dir / "requests.jsonl").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE_ID)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--top-k", type=positive_int, default=5)
    parser.add_argument("--no-rerank", dest="rerank", action="store_false")
    parser.set_defaults(rerank=True)
    parser.add_argument("--concurrency", type=positive_int, default=8)
    parser.add_argument("--warmup", type=non_negative_int, default=10)
    parser.add_argument("--timeout", type=positive_float, default=10.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--duration", type=positive_float)
    mode.add_argument("--requests", type=positive_int)
    parser.add_argument(
        "--hardware-note",
        default=os.getenv(
            "RAGOPS_BENCHMARK_HARDWARE",
            "not provided; set --hardware-note for publishable results",
        ),
    )
    parser.add_argument(
        "--api-key-env",
        default="RAGOPS_API_KEY",
        help="environment variable containing an optional API key; its value is never recorded",
    )
    parser.add_argument("--output", type=Path, help="write the complete summary JSON to this file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="write environment.json, requests.jsonl, and summary.json to this directory",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.requests is None and args.duration is None:
        args.requests = 100
    if args.output is not None and args.output_dir is not None:
        parser.error("--output and --output-dir are mutually exclusive")

    api_key = os.getenv(args.api_key_env)
    requester = SearchRequester(
        base_url=args.base_url,
        workspace_id=args.workspace_id,
        query=args.query,
        top_k=args.top_k,
        rerank=args.rerank,
        timeout_seconds=args.timeout,
        api_key=api_key,
    )
    warmup = (
        run_request_count(args.warmup, args.concurrency, requester)
        if args.warmup
        else RunResult((), 0.0)
    )
    measured = (
        run_duration(args.duration, args.concurrency, requester)
        if args.duration is not None
        else run_request_count(args.requests, args.concurrency, requester)
    )
    repository = Path(__file__).resolve().parents[2]
    report = build_report(
        repository=repository,
        args=args,
        warmup=warmup,
        measured=measured,
        api_key_configured=bool(api_key),
    )

    if args.output_dir is not None:
        write_artifacts(args.output_dir, report, measured.samples)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    elif args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["summary"]["failed_requests"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

