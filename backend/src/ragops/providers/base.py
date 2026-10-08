"""Typed, async provider contracts used throughout RAGOps."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from typing import Protocol, runtime_checkable


class ProviderError(RuntimeError):
    """A sanitized provider failure safe to expose to service error handling."""


@dataclass(frozen=True, slots=True)
class RerankScore:
    index: int
    score: float

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("index must be non-negative")
        if not isfinite(self.score) or not 0.0 <= self.score <= 1.0:
            raise ValueError("rerank score must be finite and normalized to [0, 1]")


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class EmbeddingProvider(Protocol):
    provider_name: str
    model: str

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class RerankingProvider(Protocol):
    provider_name: str
    model: str

    async def rerank(self, query: str, documents: Sequence[str]) -> list[RerankScore]: ...


@runtime_checkable
class GenerationProvider(Protocol):
    provider_name: str
    model: str

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> GenerationResult: ...
