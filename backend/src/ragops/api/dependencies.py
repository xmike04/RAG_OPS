"""FastAPI service dependencies with app-scoped provider instances."""

from typing import Any

from fastapi import Request

from ragops.services.query import QueryService


def get_search_service(request: Request) -> Any:
    service = getattr(request.app.state, "search_service", None)
    if service is None:
        from ragops.services.search import build_search_service

        service = build_search_service(request.app.state.settings)
        request.app.state.search_service = service
    return service


def get_query_service(request: Request) -> QueryService:
    service = getattr(request.app.state, "query_service", None)
    if service is None:
        service = QueryService(get_search_service(request), request.app.state.generator)
        request.app.state.query_service = service
    return service
