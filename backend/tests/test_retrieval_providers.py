from __future__ import annotations

import asyncio
import math
from typing import Any

import pytest

from ragops.providers import (
    DeterministicGenerationProvider,
    HashEmbeddingProvider,
    LexicalRerankingProvider,
    OpenAICompatibleConfig,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleGenerationProvider,
    ProviderError,
    SentenceTransformersCrossEncoderProvider,
)


def test_hash_embeddings_are_deterministic_normalized_and_semantic() -> None:
    provider = HashEmbeddingProvider(dimensions=32)
    vectors = asyncio.run(provider.embed(["alpha beta", "alpha beta", ""]))
    assert vectors[0] == vectors[1]
    assert math.sqrt(sum(value * value for value in vectors[0])) == pytest.approx(1.0)
    assert vectors[2] == [0.0] * 32


def test_local_reranker_returns_scores_in_input_index_order() -> None:
    provider = LexicalRerankingProvider()
    scores = asyncio.run(provider.rerank("hybrid search", ["unrelated", "hybrid search guide"]))
    assert [score.index for score in scores] == [0, 1]
    assert scores[1].score > scores[0].score


def test_deterministic_generator_respects_limit() -> None:
    result = asyncio.run(DeterministicGenerationProvider().generate("one two three", max_tokens=2))
    assert result.text == "one two"
    assert result.output_tokens == 2


class FakeResponse:
    def __init__(self, payload: dict[str, Any], *, fails: bool = False) -> None:
        self.payload = payload
        self.fails = fails

    def raise_for_status(self) -> None:
        if self.fails:
            raise RuntimeError("secret response body must not leak")

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.response


def config() -> OpenAICompatibleConfig:
    return OpenAICompatibleConfig(
        base_url="https://llm.example.test/v1", model="test-model", api_key="token"
    )


def test_openai_embedding_orders_vectors_by_index() -> None:
    client = FakeClient(
        FakeResponse(
            {"data": [{"index": 1, "embedding": [3, 4]}, {"index": 0, "embedding": [1, 2]}]}
        )
    )
    provider = OpenAICompatibleEmbeddingProvider(config(), client=client)
    vectors = asyncio.run(provider.embed(["first", "second"]))
    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    assert client.calls[0][0] == "https://llm.example.test/v1/embeddings"
    assert client.calls[0][1]["headers"]["Authorization"] == "Bearer token"


def test_openai_generation_parses_usage() -> None:
    client = FakeClient(
        FakeResponse(
            {
                "id": "response-1",
                "model": "actual-model",
                "choices": [{"message": {"content": "Grounded [1]."}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            }
        )
    )
    provider = OpenAICompatibleGenerationProvider(config(), client=client)
    result = asyncio.run(provider.generate("question", system_prompt="cite sources"))
    assert result.text == "Grounded [1]."
    assert result.input_tokens == 7
    assert result.output_tokens == 3
    assert result.response_id == "response-1"


def test_openai_errors_do_not_leak_response_details() -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        config(), client=FakeClient(FakeResponse({}, fails=True))
    )
    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.embed(["sensitive prompt"]))
    assert "secret response body" not in str(caught.value)
    assert "sensitive prompt" not in str(caught.value)


class FakeCrossEncoder:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        assert len(pairs) == 2
        return [-2.0, 2.0]


def test_cross_encoder_normalizes_logits_without_optional_dependency() -> None:
    provider = SentenceTransformersCrossEncoderProvider(model_instance=FakeCrossEncoder())
    scores = asyncio.run(provider.rerank("query", ["first", "second"]))
    assert 0 < scores[0].score < 0.5 < scores[1].score < 1
