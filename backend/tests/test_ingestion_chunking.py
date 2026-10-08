from ragops.ingestion.chunking import ChunkingConfig, TokenAwareChunker


def test_chunks_are_token_bounded_overlapping_and_deterministic() -> None:
    chunker = TokenAwareChunker(ChunkingConfig(max_tokens=5, overlap_tokens=2))
    text = "one two three four five six seven eight nine"

    first = chunker.chunk(text)
    second = chunker.chunk(text)

    assert first == second
    assert [chunk.content for chunk in first] == [
        "one two three four five",
        "four five six seven eight",
        "seven eight nine",
    ]
    assert [chunk.token_count for chunk in first] == [5, 5, 3]
    assert [chunk.position for chunk in first] == [0, 1, 2]
    assert all(len(chunk.content_sha256) == 64 for chunk in first)


def test_markdown_chunks_record_nearest_heading() -> None:
    chunker = TokenAwareChunker(ChunkingConfig(max_tokens=4, overlap_tokens=1))
    chunks = chunker.chunk("# First\na b c d\n## Second\ne f g h", markdown=True)

    assert chunks[0].metadata == {"heading": "First", "heading_level": 1}
    assert chunks[-1].metadata == {"heading": "Second", "heading_level": 2}


def test_empty_text_has_no_chunks() -> None:
    assert TokenAwareChunker().chunk(" \n\t") == []
