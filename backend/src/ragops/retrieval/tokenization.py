"""Small deterministic tokenizer used by credential-free local providers."""

from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)?", flags=re.UNICODE)


def normalize_text(text: str) -> str:
    """Normalize compatibility characters and case without losing Unicode."""

    return unicodedata.normalize("NFKC", text).casefold()


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(normalize_text(text)))


def token_count(text: str) -> int:
    return len(tokenize(text))
