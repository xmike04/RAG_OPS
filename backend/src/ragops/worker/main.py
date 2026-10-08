"""Executable Redis ingestion worker: ``python -m ragops.worker.main``."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import os
from collections.abc import Callable
from typing import Any, cast

from ragops.ingestion.pipeline import IngestionPipeline
from ragops.worker.queue import RedisJobQueue
from ragops.worker.runner import RedisWorker

logger = logging.getLogger(__name__)


def _load_factory(path: str) -> Callable[[], Any]:
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("RAGOPS_WORKER_FACTORY must use 'module:callable' syntax")
    factory = getattr(importlib.import_module(module_name), attribute)
    if not callable(factory):
        raise TypeError(f"worker factory {path!r} is not callable")
    return cast("Callable[[], Any]", factory)


async def async_main() -> None:
    """Build dependencies from an application factory and run until cancelled.

    The factory keeps the worker decoupled from concrete provider selection. It
    must return either a ready ``RedisWorker`` or ``(redis_client, pipeline)``.
    """

    factory_path = os.getenv("RAGOPS_WORKER_FACTORY", "ragops.main:create_ingestion_worker")
    result = _load_factory(factory_path)()
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, RedisWorker):
        worker = result
    elif (
        isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], IngestionPipeline)
    ):
        redis_client, pipeline = result
        worker = RedisWorker(RedisJobQueue(redis_client), pipeline.process)
    else:
        raise TypeError(
            "worker factory must return RedisWorker or (redis_client, IngestionPipeline)"
        )
    await worker.run()


def main() -> None:
    logging.basicConfig(level=os.getenv("RAGOPS_LOG_LEVEL", "INFO"))
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
