"""Candidate repository protocol and a PostgreSQL/pgvector implementation."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from math import isfinite
from typing import Any, Protocol, runtime_checkable

from .models import RetrievalCandidate


@runtime_checkable
class HybridCandidateRepository(Protocol):
    async def lexical_candidates(
        self, session: object, *, workspace_id: object, query: str, limit: int
    ) -> Sequence[RetrievalCandidate]: ...

    async def vector_candidates(
        self,
        session: object,
        *,
        workspace_id: object,
        embedding: Sequence[float],
        limit: int,
    ) -> Sequence[RetrievalCandidate]: ...


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str) -> str:
    parts = value.split(".")
    if not parts or any(not _IDENTIFIER.fullmatch(part) for part in parts):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return ".".join(f'"{part}"' for part in parts)


@dataclass(frozen=True, slots=True)
class PostgreSQLRepositoryConfig:
    table: str = "chunks"
    id_column: str = "id"
    document_id_column: str = "document_id"
    workspace_id_column: str = "workspace_id"
    text_column: str = "content"
    tsvector_column: str = "content_tsv"
    metadata_column: str = "metadata"
    embedding_column: str = "embedding"
    text_search_language: str = "english"


class PostgreSQLHybridCandidateRepository:
    """Hybrid candidate queries with no dependency on application ORM models."""

    def __init__(self, config: PostgreSQLRepositoryConfig | None = None) -> None:
        self.config = config or PostgreSQLRepositoryConfig()
        for value in (
            self.config.table,
            self.config.id_column,
            self.config.document_id_column,
            self.config.workspace_id_column,
            self.config.text_column,
            self.config.tsvector_column,
            self.config.metadata_column,
            self.config.embedding_column,
        ):
            _identifier(value)

    async def lexical_candidates(
        self, session: object, *, workspace_id: object, query: str, limit: int
    ) -> Sequence[RetrievalCandidate]:
        if limit < 1:
            return []
        text = _sqlalchemy_text()
        c = self.config
        table, cid, did, wid, body, tsvector, metadata = map(
            _identifier,
            (
                c.table,
                c.id_column,
                c.document_id_column,
                c.workspace_id_column,
                c.text_column,
                c.tsvector_column,
                c.metadata_column,
            ),
        )
        statement = text(
            f"""
            WITH q AS (SELECT plainto_tsquery(CAST(:language AS regconfig), :query) value)
            SELECT {cid} AS chunk_id, {did} AS document_id, {body} AS content,
                   {metadata} AS metadata,
                   ts_rank_cd({tsvector}, q.value) AS score
            FROM {table}, q
            WHERE {wid} = :workspace_id
              AND {tsvector} @@ q.value
            ORDER BY score DESC, {cid} ASC
            LIMIT :limit
            """
        )
        result = await _execute(
            session,
            statement,
            {
                "language": c.text_search_language,
                "query": query,
                "workspace_id": workspace_id,
                "limit": limit,
            },
        )
        return _rows_to_candidates(result)

    async def vector_candidates(
        self,
        session: object,
        *,
        workspace_id: object,
        embedding: Sequence[float],
        limit: int,
    ) -> Sequence[RetrievalCandidate]:
        if limit < 1:
            return []
        if not embedding or any(not isfinite(float(value)) for value in embedding):
            raise ValueError("embedding must contain finite values")
        text = _sqlalchemy_text()
        c = self.config
        table, cid, did, wid, body, metadata, vector = map(
            _identifier,
            (
                c.table,
                c.id_column,
                c.document_id_column,
                c.workspace_id_column,
                c.text_column,
                c.metadata_column,
                c.embedding_column,
            ),
        )
        statement = text(
            f"""
            SELECT {cid} AS chunk_id, {did} AS document_id, {body} AS content,
                   {metadata} AS metadata,
                   1 - ({vector} <=> CAST(:embedding AS vector)) AS score
            FROM {table}
            WHERE {wid} = :workspace_id AND {vector} IS NOT NULL
            ORDER BY {vector} <=> CAST(:embedding AS vector), {cid} ASC
            LIMIT :limit
            """
        )
        serialized = "[" + ",".join(format(float(value), ".12g") for value in embedding) + "]"
        result = await _execute(
            session,
            statement,
            {"embedding": serialized, "workspace_id": workspace_id, "limit": limit},
        )
        return _rows_to_candidates(result)


def _sqlalchemy_text() -> Any:
    try:
        sqlalchemy = import_module("sqlalchemy")
    except ImportError as exc:  # pragma: no cover - exercised in minimal installs
        raise RuntimeError("SQLAlchemy is required for PostgreSQL retrieval") from exc
    return sqlalchemy.text


async def _execute(session: object, statement: object, parameters: dict[str, object]) -> Any:
    execute = getattr(session, "execute", None)
    if execute is None:
        raise TypeError("session must provide an async execute method")
    return await execute(statement, parameters)


def _rows_to_candidates(result: Any) -> list[RetrievalCandidate]:
    mappings = result.mappings()
    rows = mappings.all()
    return [
        RetrievalCandidate(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]) if row["document_id"] is not None else None,
            text=str(row["content"]),
            metadata=row["metadata"] or {},
            raw_score=float(row["score"]),
        )
        for row in rows
    ]
