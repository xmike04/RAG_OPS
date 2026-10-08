import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from ragops.services.query import LocalGroundedGenerator, QueryService


@dataclass
class FakeHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str


@dataclass
class FakeSearchResult:
    results: list[FakeHit]
    latency_ms: dict[str, float]
    cache_hit: bool = False


class FakeSearchService:
    async def search(self, *_args: Any, **_kwargs: Any) -> FakeSearchResult:
        return FakeSearchResult(
            results=[
                FakeHit(uuid.uuid4(), uuid.uuid4(), "RRF combines independent ranked lists."),
                FakeHit(uuid.uuid4(), uuid.uuid4(), "Reranking scores the fused shortlist."),
            ],
            latency_ms={"lexical": 2.0, "vector": 3.0},
        )


class FakeSession:
    def __init__(self) -> None:
        self.added: Any = None
        self.committed = False

    def add(self, value: Any) -> None:
        self.added = value

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, value: Any) -> None:
        value.id = uuid.uuid4()


@pytest.mark.asyncio
async def test_query_service_returns_citations_and_persists_trace() -> None:
    session = FakeSession()
    service = QueryService(FakeSearchService(), LocalGroundedGenerator())
    workspace_id = uuid.uuid4()

    response = await service.query(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        query="How does retrieval work?",
        top_k=5,
        rerank=True,
    )

    assert response.answer.endswith("[2]")
    assert len(response.citations) == 2
    assert response.citations[0].index == 1
    assert response.prompt_tokens > 0
    assert response.latency_ms["lexical"] == 2.0
    assert session.committed is True
    assert session.added.workspace_id == workspace_id


@pytest.mark.asyncio
async def test_local_generator_refuses_to_invent_without_context() -> None:
    generated = await LocalGroundedGenerator().generate("Unknown?", [])

    assert "could not find enough indexed evidence" in generated.text
