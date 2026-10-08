"""FastAPI application factory and ASGI entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ragops.api.router import api_router
from ragops.api.routes.platform import router as platform_router
from ragops.config import Settings, get_settings
from ragops.db.session import create_database_engine, create_session_factory
from ragops.logging import configure_logging, get_logger
from ragops.observability import metrics_middleware
from ragops.security import request_context_middleware
from ragops.services.query import build_generator


def create_ingestion_worker() -> tuple[object, object]:
    """Build the Redis worker dependencies used by ``python -m ragops.worker.main``."""

    from ragops.ingestion.pipeline import IngestionPipeline
    from ragops.providers import HashEmbeddingProvider
    from ragops.services.ingest import SQLAlchemyIngestionRepository

    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    redis_client = redis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url, decode_responses=True
    )
    pipeline = IngestionPipeline(
        SQLAlchemyIngestionRepository(session_factory),
        HashEmbeddingProvider(dimensions=settings.embedding_dimensions),
        max_content_bytes=settings.max_document_bytes,
    )
    return redis_client, pipeline


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    configure_logging(
        runtime_settings.log_level, json_logs=runtime_settings.environment != "development"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from ragops.services.ingest import configure_ingestion_queue
        from ragops.worker.queue import RedisJobQueue

        engine = create_database_engine(runtime_settings)
        redis_client = redis.from_url(  # type: ignore[no-untyped-call]
            runtime_settings.redis_url, decode_responses=True
        )
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.redis = redis_client
        app.state.ingestion_queue = RedisJobQueue(redis_client)
        configure_ingestion_queue(app.state.ingestion_queue)
        app.state.generator = build_generator(runtime_settings)
        get_logger(__name__).info(
            "application_started",
            environment=runtime_settings.environment,
            generation_provider=runtime_settings.generation_provider,
        )
        try:
            yield
        finally:
            configure_ingestion_queue(None)
            await redis_client.aclose()
            await engine.dispose()

    app = FastAPI(
        title=runtime_settings.app_name,
        version="0.1.0",
        description="Observable multi-workspace retrieval-augmented generation API.",
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.cors_origins,
        allow_credentials="*" not in runtime_settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(metrics_middleware)
    app.middleware("http")(request_context_middleware)
    app.include_router(platform_router)
    app.include_router(api_router)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        get_logger(__name__).exception(
            "unhandled_request_error",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    return app


app = create_app()
