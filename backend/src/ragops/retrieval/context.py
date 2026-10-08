"""Citation-safe assembly of retrieved chunks into a generation context."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .models import SearchHit
from .tokenization import tokenize


@dataclass(frozen=True, slots=True)
class Citation:
    index: int
    chunk_id: str
    document_id: str | None
    title: str | None

    @property
    def marker(self) -> str:
        return f"[{self.index}]"


@dataclass(frozen=True, slots=True)
class AssembledContext:
    text: str
    citations: tuple[Citation, ...]
    used_tokens: int
    truncated: bool


def assemble_context(
    hits: Sequence[SearchHit],
    *,
    max_tokens: int = 2_000,
    max_chunks: int | None = None,
) -> AssembledContext:
    """Build numbered context blocks without emitting citations for omitted text."""

    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    if max_chunks is not None and max_chunks < 1:
        raise ValueError("max_chunks must be positive")

    selected = hits if max_chunks is None else hits[:max_chunks]
    blocks: list[str] = []
    citations: list[Citation] = []
    used = 0
    truncated = len(selected) < len(hits)
    for hit in selected:
        index = len(citations) + 1
        title_value = hit.metadata.get("title")
        title = str(title_value) if title_value is not None else None
        heading = f"[{index}]" + (f" {title}" if title else "")
        heading_tokens = len(tokenize(heading))
        remaining = max_tokens - used - heading_tokens
        if remaining <= 0:
            truncated = True
            break
        content_tokens = tokenize(hit.text)
        if not content_tokens:
            continue
        content = hit.text.strip()
        if len(content_tokens) > remaining:
            # Joining normalized tokens is deterministic and never cuts a Unicode
            # codepoint. Exact original whitespace is not meaningful at this edge.
            content = " ".join(content_tokens[:remaining])
            truncated = True
        block = f"{heading}\n{content}"
        blocks.append(block)
        used += heading_tokens + min(len(content_tokens), remaining)
        citations.append(
            Citation(
                index=index,
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                title=title,
            )
        )
        if len(content_tokens) > remaining:
            break

    return AssembledContext(
        text="\n\n".join(blocks),
        citations=tuple(citations),
        used_tokens=used,
        truncated=truncated,
    )
