"""Collect a sanitized snapshot inside the API container; no model inference."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


def public_settings(settings) -> dict:
    keys = ("environment", "embedding_provider", "embedding_model", "embedding_dimensions",
            "reranker_provider", "reranker_model", "generation_provider", "generation_model",
            "retrieval_rrf_k", "retrieval_candidate_limit", "max_document_bytes")
    return {key: getattr(settings, key) for key in keys}


async def capture(workspace_id: str, source_revision: str) -> dict:
    # Kept inside the runtime path so scoring tests do not need backend dependencies.
    import ragops
    from sqlalchemy import text
    from ragops.config import get_settings
    from ragops.db.session import create_database_engine
    from ragops.main import create_ingestion_worker
    from ragops.services.search import build_search_service

    if not re.fullmatch(r"[a-f0-9]{40}", source_revision):
        raise ValueError("source revision must be the full Git commit SHA")
    workspace_id = str(UUID(workspace_id))
    settings = get_settings()
    search = build_search_service(settings)
    redis_client, pipeline = create_ingestion_worker()
    engine = create_database_engine(settings)
    try:
        async with engine.connect() as connection:
            async def scalar(statement, parameters=None):
                return (await connection.execute(text(statement), parameters or {})).scalar_one()

            params = {"workspace": workspace_id}
            documents = await scalar("SELECT count(*) FROM documents WHERE workspace_id = CAST(:workspace AS uuid)", params)
            chunks = await scalar("SELECT count(*) FROM chunks WHERE workspace_id = CAST(:workspace AS uuid)", params)
            indexed = await scalar("SELECT count(DISTINCT document_id) FROM chunks WHERE workspace_id = CAST(:workspace AS uuid)", params)
            indexes = (await connection.execute(text(
                "SELECT tablename, indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename IN ('chunks', 'documents') ORDER BY indexname"
            ))).mappings().all()
            version = await scalar("SELECT version()")
            vector_version = await scalar("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            table_bytes = await scalar("SELECT pg_total_relation_size('chunks')")
        source_root = Path(ragops.__file__).parent
        source_hashes = {str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in sorted(source_root.rglob('*.py'))}
        def embedding(provider):
            return {"provider": provider.provider_name, "model": provider.model,
                    "dimensions": getattr(provider, "dimensions", settings.embedding_dimensions)}
        return {
            "schema_version": 1, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_revision": source_revision, "revision_attribution": "operator-supplied; loaded source hashes retained",
            "source_files_sha256": source_hashes,
            "source_tree_sha256": hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest(),
            "settings": public_settings(settings), "query_embedding": embedding(search.embedding_provider),
            "ingestion_embedding": embedding(pipeline.embedder),
            "chunking": {**asdict(pipeline.chunker.config), "tokenizer": type(pipeline.chunker.tokenizer).__name__},
            "postgres": {"version": version, "pgvector_version": vector_version,
                         "indexes": [dict(row) for row in indexes], "chunks_table_and_indexes_bytes_global": table_bytes},
            "corpus": {"workspace_id": workspace_id, "documents": documents, "chunks": chunks, "indexed_documents": indexed},
            "machine": {"platform": platform.platform(), "python": platform.python_version(),
                        "logical_cpu_count_visible": os.cpu_count(), "container_resource_limits": None},
            "measurement_limits": "Factory/settings snapshot in this container, not an API-process introspection endpoint; no inference, billing, or CPU/RSS sampling.",
        }
    finally:
        await redis_client.aclose()
        worker_engine = getattr(pipeline.repository.session_factory, 'kw', {}).get('bind')
        if worker_engine is not None:
            await worker_engine.dispose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace-id', required=True)
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(capture(args.workspace_id, args.source_revision)), indent=2, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
