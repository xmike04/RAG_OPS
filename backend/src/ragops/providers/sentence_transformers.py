"""Optional local sentence-transformers cross-encoder reranker."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from importlib import import_module
from typing import Any

from .base import ProviderError, RerankScore


class SentenceTransformersEmbeddingProvider:
    """Optional in-process sentence-transformers embedding provider."""

    provider_name = "sentence-transformers"

    def __init__(self, model: str, *, model_instance: Any | None = None) -> None:
        if not model:
            raise ValueError("model must not be empty")
        self.model = model
        self._sentence_transformer = model_instance

    def _load(self) -> Any:
        if self._sentence_transformer is None:
            try:
                sentence_transformers = import_module("sentence_transformers")
            except ImportError as exc:
                raise ProviderError(
                    "sentence-transformers is required for this embedding provider"
                ) from exc
            self._sentence_transformer = sentence_transformers.SentenceTransformer(self.model)
        return self._sentence_transformer

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await asyncio.to_thread(self._load)
        encoded = await asyncio.to_thread(
            model.encode,
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=False,
        )
        vectors = [[float(value) for value in vector] for vector in encoded]
        dimensions = {len(vector) for vector in vectors}
        if (
            len(vectors) != len(texts)
            or dimensions == {0}
            or len(dimensions) != 1
            or any(not math.isfinite(value) for vector in vectors for value in vector)
        ):
            raise ProviderError("sentence-transformers returned an invalid embedding batch")
        return vectors


class SentenceTransformersCrossEncoderProvider:
    provider_name = "sentence-transformers"

    def __init__(
        self,
        model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        *,
        model_instance: Any | None = None,
    ) -> None:
        self.model = model
        self._cross_encoder = model_instance

    def _load(self) -> Any:
        if self._cross_encoder is None:
            try:
                sentence_transformers = import_module("sentence_transformers")
            except ImportError as exc:
                raise ProviderError(
                    "sentence-transformers is required for the cross-encoder provider"
                ) from exc
            self._cross_encoder = sentence_transformers.CrossEncoder(self.model)
        return self._cross_encoder

    async def rerank(self, query: str, documents: Sequence[str]) -> list[RerankScore]:
        if not documents:
            return []
        model = await asyncio.to_thread(self._load)
        pairs = [(query, document) for document in documents]
        raw = await asyncio.to_thread(model.predict, pairs)
        values = [float(value) for value in raw]
        already_normalized = all(0.0 <= value <= 1.0 for value in values)
        return [
            RerankScore(
                index=index,
                score=value if already_normalized else _stable_sigmoid(value),
            )
            for index, value in enumerate(values)
        ]


def _stable_sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)
