from __future__ import annotations

from ragops.retrieval import SearchHit, assemble_context, tokenize


def hit(chunk_id: str, text: str, *, title: str | None = None) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        text=text,
        metadata={} if title is None else {"title": title},
        fused_score=0.1,
        final_score=0.1,
        rank=1,
        contributions=(),
    )


def test_context_citations_align_with_included_chunks() -> None:
    context = assemble_context(
        [hit("a", "Alpha body", title="Guide"), hit("b", "Beta body")],
        max_tokens=100,
    )
    assert context.text == "[1] Guide\nAlpha body\n\n[2]\nBeta body"
    assert [citation.chunk_id for citation in context.citations] == ["a", "b"]
    assert [citation.marker for citation in context.citations] == ["[1]", "[2]"]
    assert context.truncated is False


def test_context_token_budget_truncates_without_dangling_citation() -> None:
    context = assemble_context(
        [hit("a", "one two three four"), hit("b", "never included")],
        max_tokens=3,
    )
    assert len(tokenize(context.text)) == 3
    assert [citation.chunk_id for citation in context.citations] == ["a"]
    assert "[2]" not in context.text
    assert context.truncated is True


def test_tokenizer_is_unicode_and_compatibility_normalized() -> None:
    assert tokenize("CAFÉ café \uff21\uff22\uff23 don't") == ("café", "café", "abc", "don't")
