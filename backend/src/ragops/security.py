"""Optional API-key authentication and request identity middleware."""

import hmac
import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from ragops.config import Settings, get_settings

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    supplied_key: str | None = Security(_api_key_header),
) -> None:
    """Require a constant-time API key match only when an API key is configured."""

    settings: Settings = getattr(request.app.state, "settings", get_settings())
    configured = settings.api_key
    if configured is None:
        return
    expected = configured.get_secret_value()
    if supplied_key is None or not hmac.compare_digest(supplied_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get(REQUEST_ID_HEADER)
    request_id = (
        incoming if incoming and _REQUEST_ID_PATTERN.fullmatch(incoming) else str(uuid.uuid4())
    )
    request.state.request_id = request_id
    clear_contextvars()
    bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        clear_contextvars()
