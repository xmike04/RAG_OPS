"""Grounded answer orchestration and durable query tracing."""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any, Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.config import Settings
from ragops.db.models import QueryTrace
from ragops.observability import QUERY_LATENCY
from ragops.schemas.query import Citation, QueryResponse


class SearchServiceProtocol(Protocol):
    async def search(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        query: str,
        top_k: int = 10,
        rerank: bool = True,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class GeneratedText:
    text: str
    prompt_tokens: int
    completion_tokens: int
    provider: str
    model: str


class GeneratorProtocol(Protocol):
    async def generate(self, query: str, hits: list[Any]) -> GeneratedText: ...


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _token_count(text: str) -> int:
    # A deterministic, dependency-light count suitable for local telemetry. Production
    # providers return their tokenizer's usage when available.
    return len(text.split())


class LocalGroundedGenerator:
    """A deterministic extractive generator used by tests and the default demo."""

    provider = "local"

    def __init__(self, model: str = "extractive-local-v1") -> None:
        self.model = model

    async def generate(self, query: str, hits: list[Any]) -> GeneratedText:
        context = [
            str(_value(hit, "content", None) or _value(hit, "text", "")).strip() for hit in hits
        ]
        context = [text for text in context if text]
        if not context:
            answer = "I could not find enough indexed evidence to answer that question."
        else:
            statements = []
            for index, text in enumerate(context[:5], start=1):
                excerpt = " ".join(text.split())
                if len(excerpt) > 320:
                    excerpt = f"{excerpt[:317].rstrip()}..."
                statements.append(f"{excerpt} [{index}]")
            answer = "\n\n".join(statements)
        prompt = f"Question: {query}\n\n" + "\n\n".join(context)
        return GeneratedText(
            text=answer,
            prompt_tokens=_token_count(prompt),
            completion_tokens=_token_count(answer),
            provider=self.provider,
            model=self.model,
        )


class OpenAICompatibleGenerator:
    """Small OpenAI-compatible adapter without coupling to a vendor SDK."""

    provider = "openai-compatible"

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def generate(self, query: str, hits: list[Any]) -> GeneratedText:
        contexts = [str(_value(hit, "content", None) or _value(hit, "text", "")) for hit in hits]
        numbered = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(contexts, 1))
        prompt = (
            "Answer only from the evidence. Cite supporting passages with [n]. "
            "If evidence is insufficient, say so.\n\n"
            f"Question: {query}\n\nEvidence:\n{numbered}"
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage", {})
        return GeneratedText(
            text=str(payload["choices"][0]["message"]["content"]),
            prompt_tokens=int(usage.get("prompt_tokens", _token_count(prompt))),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            provider=self.provider,
            model=self.model,
        )


def build_generator(settings: Settings) -> GeneratorProtocol:
    if settings.generation_provider == "local":
        return LocalGroundedGenerator(settings.generation_model)
    if settings.openai_compatible_base_url is None or settings.openai_compatible_api_key is None:
        raise ValueError(
            "RAGOPS_OPENAI_COMPATIBLE_BASE_URL and RAGOPS_OPENAI_COMPATIBLE_API_KEY "
            "are required for openai-compatible generation"
        )
    return OpenAICompatibleGenerator(
        base_url=settings.openai_compatible_base_url,
        api_key=settings.openai_compatible_api_key.get_secret_value(),
        model=settings.generation_model,
    )


class QueryService:
    def __init__(self, search_service: SearchServiceProtocol, generator: GeneratorProtocol) -> None:
        self.search_service = search_service
        self.generator = generator

    async def query(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        query: str,
        top_k: int,
        rerank: bool,
    ) -> QueryResponse:
        total_started = perf_counter()
        retrieval_started = perf_counter()
        search_result = await self.search_service.search(
            session, workspace_id, query, top_k=top_k, rerank=rerank
        )
        hits = list(_value(search_result, "results", []))
        retrieval_ms = (perf_counter() - retrieval_started) * 1000
        QUERY_LATENCY.labels("retrieval").observe(retrieval_ms / 1000)

        generation_started = perf_counter()
        generated = await self.generator.generate(query, hits)
        generation_ms = (perf_counter() - generation_started) * 1000
        QUERY_LATENCY.labels("generation").observe(generation_ms / 1000)

        citations = [
            Citation(
                index=index,
                chunk_id=_value(hit, "chunk_id"),
                document_id=_value(hit, "document_id"),
                quote=" ".join(
                    str(_value(hit, "content", None) or _value(hit, "text", "")).split()
                )[:320],
            )
            for index, hit in enumerate(hits, start=1)
        ]
        search_timings = (
            _value(search_result, "latency_ms", None)
            or _value(search_result, "timing_ms", None)
            or _value(search_result, "stage_ms", {})
        )
        stage_latency = {str(key): float(value) for key, value in dict(search_timings).items()}
        stage_latency.update(retrieval=retrieval_ms, generation=generation_ms)
        total_ms = (perf_counter() - total_started) * 1000
        stage_latency["total"] = total_ms

        trace = QueryTrace(
            workspace_id=workspace_id,
            query=query,
            answer=generated.text,
            search_type="hybrid-reranked" if rerank else "hybrid",
            top_k=top_k,
            retrieval_count=len(hits),
            total_latency_ms=total_ms,
            stage_latency_ms=stage_latency,
            prompt_tokens=generated.prompt_tokens,
            completion_tokens=generated.completion_tokens,
            estimated_cost_usd=Decimal("0"),
            cache_hit=bool(_value(search_result, "cache_hit", False)),
            provider=generated.provider,
            model=generated.model,
            citations=[citation.model_dump(mode="json") for citation in citations],
        )
        session.add(trace)
        await session.commit()
        await session.refresh(trace)
        return QueryResponse(
            trace_id=trace.id,
            answer=generated.text,
            citations=citations,
            latency_ms=stage_latency,
            prompt_tokens=generated.prompt_tokens,
            completion_tokens=generated.completion_tokens,
            provider=generated.provider,
            model=generated.model,
        )
