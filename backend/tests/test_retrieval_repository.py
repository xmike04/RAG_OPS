from __future__ import annotations

import asyncio

import pytest

from ragops.retrieval import (
    PostgreSQLHybridCandidateRepository,
    PostgreSQLRepositoryConfig,
)


class FakeMappings:
    def all(self) -> list[dict[str, object]]:
        return [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "content": "retrieved text",
                "metadata": {"title": "Title"},
                "score": 0.75,
            }
        ]


class FakeResult:
    def mappings(self) -> FakeMappings:
        return FakeMappings()


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, statement: object, parameters: dict[str, object]) -> FakeResult:
        self.calls.append((str(statement), parameters))
        return FakeResult()


def test_postgres_repository_builds_indexed_lexical_query_without_postgres() -> None:
    repository = PostgreSQLHybridCandidateRepository()
    session = FakeSession()
    candidates = asyncio.run(
        repository.lexical_candidates(
            session, workspace_id="workspace", query="hybrid search", limit=20
        )
    )
    sql, parameters = session.calls[0]
    assert '"content_tsv" @@ q.value' in sql
    assert "to_tsvector" not in sql
    assert parameters == {
        "language": "english",
        "query": "hybrid search",
        "workspace_id": "workspace",
        "limit": 20,
    }
    assert candidates[0].metadata == {"title": "Title"}


def test_postgres_repository_serializes_finite_vector() -> None:
    repository = PostgreSQLHybridCandidateRepository()
    session = FakeSession()
    asyncio.run(
        repository.vector_candidates(
            session, workspace_id="workspace", embedding=[0.125, -0.5], limit=5
        )
    )
    sql, parameters = session.calls[0]
    assert '"embedding" <=> CAST(:embedding AS vector)' in sql
    assert parameters["embedding"] == "[0.125,-0.5]"


@pytest.mark.parametrize("bad_table", ["chunks; DROP TABLE chunks", "chunks --", "public.*"])
def test_postgres_repository_rejects_unsafe_identifiers(bad_table: str) -> None:
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        PostgreSQLHybridCandidateRepository(PostgreSQLRepositoryConfig(table=bad_table))


def test_postgres_repository_rejects_non_finite_vectors() -> None:
    with pytest.raises(ValueError, match="finite"):
        asyncio.run(
            PostgreSQLHybridCandidateRepository().vector_candidates(
                FakeSession(), workspace_id="workspace", embedding=[float("nan")], limit=5
            )
        )
