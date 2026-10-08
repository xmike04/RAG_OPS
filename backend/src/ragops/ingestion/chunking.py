"""Deterministic token-aware overlapping chunk construction."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


class Tokenizer(Protocol):
    """Tokenizer returning character spans for each model token."""

    def token_spans(self, text: str) -> Sequence[tuple[int, int]]: ...


class RegexTokenizer:
    """Dependency-free approximation suitable for local/demo providers."""

    _pattern = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        return [(match.start(), match.end()) for match in self._pattern.finditer(text)]


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    max_tokens: int = 384
    overlap_tokens: int = 64

    def __post_init__(self) -> None:
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError("overlap_tokens must be non-negative and less than max_tokens")


@dataclass(frozen=True, slots=True)
class Chunk:
    position: int
    content: str
    token_count: int
    char_start: int
    char_end: int
    content_sha256: str
    metadata: dict[str, object] = field(default_factory=dict)


_MARKDOWN_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


class TokenAwareChunker:
    def __init__(
        self,
        config: ChunkingConfig = ChunkingConfig(),
        tokenizer: Tokenizer | None = None,
    ) -> None:
        self.config = config
        self.tokenizer = tokenizer or RegexTokenizer()

    def chunk(self, text: str, *, markdown: bool = False) -> list[Chunk]:
        spans = list(self.tokenizer.token_spans(text))
        if not spans:
            return []
        self._validate_spans(text, spans)
        headings = self._headings(text) if markdown else []
        stride = self.config.max_tokens - self.config.overlap_tokens
        chunks: list[Chunk] = []
        token_start = 0
        while token_start < len(spans):
            token_end = min(token_start + self.config.max_tokens, len(spans))
            char_start = spans[token_start][0]
            char_end = spans[token_end - 1][1]
            content = text[char_start:char_end]
            metadata: dict[str, object] = {}
            heading = self._heading_at(headings, char_start)
            if heading is not None:
                metadata["heading"] = heading[1]
                metadata["heading_level"] = heading[2]
            chunks.append(
                Chunk(
                    position=len(chunks),
                    content=content,
                    token_count=token_end - token_start,
                    char_start=char_start,
                    char_end=char_end,
                    content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    metadata=metadata,
                )
            )
            if token_end == len(spans):
                break
            token_start += stride
        return chunks

    @staticmethod
    def _validate_spans(text: str, spans: Sequence[tuple[int, int]]) -> None:
        previous_end = 0
        for start, end in spans:
            if start < previous_end or end <= start or end > len(text):
                raise ValueError("tokenizer returned invalid or overlapping character spans")
            previous_end = end

    @staticmethod
    def _headings(text: str) -> list[tuple[int, str, int]]:
        return [
            (match.start(), match.group(2).strip(), len(match.group(1)))
            for match in _MARKDOWN_HEADING.finditer(text)
        ]

    @staticmethod
    def _heading_at(
        headings: Sequence[tuple[int, str, int]], char_start: int
    ) -> tuple[int, str, int] | None:
        active = None
        for heading in headings:
            if heading[0] > char_start:
                break
            active = heading
        return active
