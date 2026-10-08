"""Prometheus instruments and HTTP request metrics middleware."""

from collections.abc import Awaitable, Callable
from time import perf_counter

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

HTTP_REQUESTS = Counter(
    "ragops_http_requests_total",
    "HTTP requests processed by the API.",
    ("method", "route", "status"),
)
HTTP_LATENCY = Histogram(
    "ragops_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ("method", "route"),
)
QUERY_LATENCY = Histogram(
    "ragops_query_stage_duration_seconds",
    "Query pipeline stage latency in seconds.",
    ("stage",),
)
INGESTION_JOBS = Counter(
    "ragops_ingestion_jobs_total",
    "Ingestion jobs created by status.",
    ("status",),
)


async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path == "/metrics":
        return await call_next(request)

    started = perf_counter()
    response: Response | None = None
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, route_path, str(status)).inc()
        HTTP_LATENCY.labels(request.method, route_path).observe(perf_counter() - started)


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
