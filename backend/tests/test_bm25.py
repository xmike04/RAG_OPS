from __future__ import annotations

from math import log

import pytest

from ragops.retrieval import BM25Document, BM25Index


def test_okapi_scores_match_hand_calculation() -> None:
    # Token lengths are 3, 2, and 4, so avgdl=3. Every query term occurs in
    # two of three documents: idf = log(1 + 1.5/2.5) = log(1.6).
    index = BM25Index(
        [
            BM25Document("d1", "cat cat dog"),
            BM25Document("d2", "cat mouse"),
            BM25Document("d3", "dog mouse mouse mouse"),
        ],
        k1=1.5,
        b=0.75,
    )

    results = index.search("cat dog")

    assert index.average_document_length == 3.0
    assert index.document_frequencies == {"cat": 2, "dog": 2, "mouse": 2}
    assert [result.document_id for result in results] == ["d1", "d2", "d3"]
    assert [result.score for result in results] == pytest.approx(
        [1.1414373853110724, 0.5529454461714537, 0.4086988080397701]
    )
    assert [result.rank for result in results] == [1, 2, 3]

    d1_terms = results[0].term_scores
    assert [(term.term, term.term_frequency) for term in d1_terms] == [("cat", 2), ("dog", 1)]
    assert d1_terms[0].inverse_document_frequency == pytest.approx(log(1.6))
    assert d1_terms[0].saturation == pytest.approx(10 / 7)
    assert d1_terms[1].saturation == pytest.approx(1.0)


def test_document_frequency_counts_documents_not_occurrences() -> None:
    index = BM25Index.from_mapping(
        {
            "many": "common common common rare",
            "one": "common",
            "also-one": "common",
        }
    )

    assert index.document_frequencies == {"common": 3, "rare": 1}
    assert index.inverse_document_frequency("rare") == pytest.approx(log(1 + 2.5 / 1.5))
    assert index.inverse_document_frequency("common") == pytest.approx(log(1 + 0.5 / 3.5))
    assert index.inverse_document_frequency("missing") == 0.0


def test_query_frequency_multiplies_term_contribution() -> None:
    index = BM25Index.from_mapping({"doc": "alpha beta"})

    once = index.search("alpha")[0]
    twice = index.search("alpha alpha")[0]

    assert twice.score == pytest.approx(2 * once.score)
    assert twice.term_scores[0].query_frequency == 2


def test_existing_tokenizer_makes_unicode_and_punctuation_deterministic() -> None:
    index = BM25Index.from_mapping({"accent": "CAFÉ, don't!", "plain": "cafe dont"})

    results = index.search("café DON'T")

    assert [result.document_id for result in results] == ["accent"]
    assert [term.term for term in results[0].term_scores] == ["café", "don't"]


def test_equal_scores_use_document_id_tie_break_regardless_of_input_order() -> None:
    index = BM25Index(
        [
            BM25Document("z-last", "same tokens"),
            BM25Document("a-first", "same tokens"),
        ]
    )

    assert [result.document_id for result in index.search("same")] == ["a-first", "z-last"]


def test_zero_score_empty_query_and_limits() -> None:
    index = BM25Index.from_mapping({"b": "", "a": "unrelated"})

    assert index.search("") == ()
    assert [result.document_id for result in index.search("missing", include_zero_scores=True)] == [
        "a",
        "b",
    ]
    assert index.search("missing", include_zero_scores=True, limit=0) == ()
    with pytest.raises(ValueError, match="limit"):
        index.search("query", limit=-1)


def test_empty_corpus_and_parameter_validation() -> None:
    empty = BM25Index([])
    assert empty.document_count == 0
    assert empty.average_document_length == 0.0
    assert empty.search("anything") == ()

    with pytest.raises(ValueError, match="duplicate"):
        BM25Index([BM25Document("same", "one"), BM25Document("same", "two")])
    with pytest.raises(ValueError, match="document_id"):
        BM25Document("", "text")
    for invalid_k1 in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="k1"):
            BM25Index([], k1=invalid_k1)
    for invalid_b in (-0.1, 1.1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="b"):
            BM25Index([], b=invalid_b)


def test_term_lookup_rejects_ambiguous_input() -> None:
    index = BM25Index.from_mapping({"doc": "one two"})

    with pytest.raises(ValueError, match="exactly one"):
        index.inverse_document_frequency("one two")
    with pytest.raises(ValueError, match="exactly one"):
        index.inverse_document_frequency("---")
