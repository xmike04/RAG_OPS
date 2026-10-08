"""OpenAI-compatible providers using plain httpx and caller-owned config."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from .base import GenerationResult, ProviderError


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 30.0
    extra_headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        if not self.model:
            raise ValueError("model must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def endpoint(self, resource: str) -> str:
        return f"{self.base_url.rstrip('/')}/{resource.lstrip('/')}"

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update(self.extra_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class _OpenAICompatibleProvider:
    provider_name = "openai-compatible"

    def __init__(self, config: OpenAICompatibleConfig, *, client: Any | None = None) -> None:
        self.config = config
        self.model = config.model
        self._client = client

    async def _post(self, resource: str, payload: Mapping[str, object]) -> Mapping[str, Any]:
        client = self._client
        owns_client = client is None
        if client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - packaging failure
                raise ProviderError("httpx is required for OpenAI-compatible providers") from exc
            client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
        try:
            response = await client.post(
                self.config.endpoint(resource),
                headers=self.config.headers(),
                json=dict(payload),
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, Mapping):
                raise TypeError("response JSON is not an object")
            return data
        except ProviderError:
            raise
        except Exception as exc:
            # Avoid including a response body, prompt, or credential in errors.
            raise ProviderError(
                f"{self.provider_name} request to {resource!r} failed ({type(exc).__name__})"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


class OpenAICompatibleEmbeddingProvider(_OpenAICompatibleProvider):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        data = await self._post("embeddings", {"model": self.model, "input": list(texts)})
        try:
            items = sorted(data["data"], key=lambda item: int(item["index"]))
            if [int(item["index"]) for item in items] != list(range(len(texts))):
                raise ValueError("embedding indexes do not match the request")
            vectors = [[float(value) for value in item["embedding"]] for item in items]
            dimensions = {len(vector) for vector in vectors}
            if dimensions == {0} or len(dimensions) != 1:
                raise ValueError("embedding dimensions are inconsistent")
            if any(not isfinite(value) for vector in vectors for value in vector):
                raise ValueError("embedding contains a non-finite value")
            return vectors
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("invalid embedding response schema") from exc


class OpenAICompatibleGenerationProvider(_OpenAICompatibleProvider):
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> GenerationResult:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            if max_tokens < 1:
                raise ValueError("max_tokens must be positive")
            payload["max_tokens"] = max_tokens
        data = await self._post("chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content is not a string")
            usage = data.get("usage") or {}
            return GenerationResult(
                text=content,
                provider=self.provider_name,
                model=str(data.get("model") or self.model),
                input_tokens=_optional_int(usage.get("prompt_tokens")),
                output_tokens=_optional_int(usage.get("completion_tokens")),
                response_id=str(data["id"]) if data.get("id") is not None else None,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("invalid generation response schema") from exc


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("token count is not numeric")
    return int(value)
