"""Credential-free deterministic providers for development and tests."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Sequence

from ragops.retrieval.tokenization import token_count, tokenize

from .base import GenerationResult, RerankScore


class HashEmbeddingProvider:
    """Feature-hashed, L2-normalized bag-of-tokens embeddings.

    This is intentionally simple, but unlike pseudo-random test vectors it gives
    similar texts similar vectors and is stable across Python processes.
    """

    provider_name = "local"

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions < 8:
            raise ValueError("dimensions must be at least 8")
        self.dimensions = dimensions
        self.model = f"feature-hash-{dimensions}"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        counts = Counter(tokenize(text))
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            # Sublinear frequency prevents repeated boilerplate dominating.
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        return vector if norm == 0.0 else [value / norm for value in vector]


class LexicalRerankingProvider:
    """Deterministic local reranker based on token and phrase overlap."""

    provider_name = "local"
    model = "lexical-overlap-v1"

    async def rerank(self, query: str, documents: Sequence[str]) -> list[RerankScore]:
        query_tokens = tokenize(query)
        query_set = set(query_tokens)
        results: list[RerankScore] = []
        for index, document in enumerate(documents):
            document_tokens = tokenize(document)
            document_set = set(document_tokens)
            if not query_set or not document_set:
                score = 0.0
            else:
                overlap = len(query_set & document_set)
                cosine_like = overlap / math.sqrt(len(query_set) * len(document_set))
                normalized_query = " ".join(query_tokens)
                normalized_document = " ".join(document_tokens)
                phrase_bonus = 0.15 if normalized_query in normalized_document else 0.0
                score = min(1.0, cosine_like + phrase_bonus)
            results.append(RerankScore(index=index, score=score))
        return results


class DeterministicGenerationProvider:
    """A predictable provider useful for demos and contract tests."""

    provider_name = "local"
    model = "deterministic-extractive-v1"

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> GenerationResult:
        if temperature != 0.0:
            raise ValueError("the deterministic provider only supports temperature=0")
        words = prompt.split()
        if max_tokens is not None:
            if max_tokens < 1:
                raise ValueError("max_tokens must be positive")
            words = words[:max_tokens]
        text = " ".join(words).strip()
        if not text:
            text = "No grounded context was provided."
        return GenerationResult(
            text=text,
            provider=self.provider_name,
            model=self.model,
            input_tokens=token_count(prompt) + token_count(system_prompt or ""),
            output_tokens=token_count(text),
        )
