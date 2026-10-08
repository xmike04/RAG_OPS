"""Unversioned liveness, readiness, and metrics endpoints."""

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text
from starlette.responses import JSONResponse, Response

from ragops.observability import metrics_response

router = APIRouter(tags=["platform"])


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {
        "status": "ok",
        "service": request.app.state.settings.app_name,
        "environment": request.app.state.settings.environment,
    }


async def _database_ready(request: Request) -> None:
    async with request.app.state.session_factory() as session:
        await session.execute(text("SELECT 1"))


async def _redis_ready(request: Request) -> None:
    result: Any = await request.app.state.redis.ping()
    if result is not True:
        raise RuntimeError("Redis ping did not return success")


@router.get("/ready", response_model=None)
async def readiness(request: Request) -> JSONResponse:
    timeout = request.app.state.settings.readiness_timeout_seconds
    checks: dict[str, str] = {}
    for name, check in (("database", _database_ready), ("redis", _redis_ready)):
        try:
            await asyncio.wait_for(check(request), timeout=timeout)
            checks[name] = "ok"
        except Exception:
            checks[name] = "unavailable"
    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return metrics_response()
