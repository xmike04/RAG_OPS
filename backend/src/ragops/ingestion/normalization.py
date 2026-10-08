"""Content validation and canonicalization for text and Markdown documents."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class ContentValidationError(ValueError):
    """Raised when submitted document content cannot be safely ingested."""


class ContentFormat(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"

    @classmethod
    def parse(cls, value: str | ContentFormat) -> ContentFormat:
        if isinstance(value, cls):
            return value
        aliases = {
            "text": cls.TEXT,
            "txt": cls.TEXT,
            "text/plain": cls.TEXT,
            "markdown": cls.MARKDOWN,
            "md": cls.MARKDOWN,
            "text/markdown": cls.MARKDOWN,
        }
        try:
            return aliases[value.strip().lower()]
        except (AttributeError, KeyError) as exc:
            raise ContentValidationError(f"unsupported content format: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    content: str
    content_format: ContentFormat
    content_sha256: str
    byte_length: int


def normalize_document(
    content: str,
    content_format: str | ContentFormat = ContentFormat.TEXT,
    *,
    max_bytes: int = 10 * 1024 * 1024,
) -> NormalizedDocument:
    """Validate and normalize user content into a stable hashable representation.

    Normalization is deliberately conservative: newline encodings, an initial
    Unicode BOM, Unicode composition, and whitespace-only lines are canonicalized,
    while meaningful Markdown whitespace and fenced-code contents are preserved.
    Exactly one missing/present final newline therefore produces the same digest.
    """

    if not isinstance(content, str):
        raise ContentValidationError("content must be a string")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    parsed_format = ContentFormat.parse(content_format)
    if content.startswith("\ufeff"):
        content = content[1:]
    content = unicodedata.normalize("NFC", content)
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # NUL and most C0 control characters are unsafe for PostgreSQL and downstream
    # tokenizers.  Tabs and newlines are meaningful in both supported formats.
    invalid = sorted({ord(char) for char in content if ord(char) < 32 and char not in "\n\t"})
    if invalid:
        rendered = ", ".join(f"U+{value:04X}" for value in invalid)
        raise ContentValidationError(f"content contains unsupported control characters: {rendered}")

    lines = ["" if not line.strip(" \t") else line for line in content.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    normalized = "\n".join(lines)
    if not normalized.strip():
        raise ContentValidationError("content must not be empty")

    try:
        encoded = normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContentValidationError("content contains invalid Unicode") from exc
    if len(encoded) > max_bytes:
        raise ContentValidationError(
            f"content exceeds maximum size of {max_bytes} bytes ({len(encoded)} bytes received)"
        )
    return NormalizedDocument(
        content=normalized,
        content_format=parsed_format,
        content_sha256=hashlib.sha256(encoded).hexdigest(),
        byte_length=len(encoded),
    )
