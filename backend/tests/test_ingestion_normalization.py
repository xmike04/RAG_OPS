import pytest

from ragops.ingestion.metadata import MetadataLimits, MetadataValidationError, validate_metadata
from ragops.ingestion.normalization import ContentValidationError, normalize_document


def test_normalization_produces_same_hash_for_equivalent_text() -> None:
    windows = normalize_document("\ufeffCafe\u0301\r\n\r\nHello\r\n", "text/plain")
    unix = normalize_document("Café\n\nHello", "txt")

    assert windows.content == "Café\n\nHello"
    assert windows.content_sha256 == unix.content_sha256
    assert windows.byte_length == len(windows.content.encode())


def test_markdown_normalization_preserves_meaningful_whitespace() -> None:
    document = normalize_document("\n# Heading  \n\n```py\n  x = 1\t\n```\n", "text/markdown")

    assert document.content == "# Heading  \n\n```py\n  x = 1\t\n```"
    assert document.content_format.value == "markdown"


@pytest.mark.parametrize("content", ["", " \n\t", "bad\x00value", "bad\x07value"])
def test_normalization_rejects_empty_or_unsafe_content(content: str) -> None:
    with pytest.raises(ContentValidationError):
        normalize_document(content)


def test_metadata_is_detached_sorted_and_json_safe() -> None:
    source = {"z": [1, True, None], "a": {"label": "ok"}}

    result = validate_metadata(source)

    assert list(result) == ["a", "z"]
    assert result == source
    assert result is not source


@pytest.mark.parametrize(
    "metadata",
    [
        {1: "not a string key", "mixed": True},
        {"nan": float("nan")},
        {"object": object()},
        {"nested": {"too": {"deep": True}}},
    ],
)
def test_metadata_rejects_invalid_values(metadata: dict[object, object]) -> None:
    with pytest.raises(MetadataValidationError):
        validate_metadata(metadata, limits=MetadataLimits(max_depth=2))  # type: ignore[arg-type]
