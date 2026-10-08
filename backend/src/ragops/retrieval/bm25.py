"""Deterministic, dependency-free Okapi BM25 scoring for offline benchmarks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isfinite, log
from types import MappingProxyType

from .tokenization import tokenize


@dataclass(frozen=True, slots=True)
class BM25Document:
    """A uniquely identified document to be indexed by :class:`BM25Index`."""

    document_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.document_id:
            raise ValueError("document_id must not be empty")


@dataclass(frozen=True, slots=True)
class BM25TermScore:
    """One query term's contribution to a document score."""

    term: str
    query_frequency: int
    document_frequency: int
    term_frequency: int
    inverse_document_frequency: float
    saturation: float
    contribution: float


@dataclass(frozen=True, slots=True)
class BM25Result:
    """A ranked BM25 hit with sufficient detail for benchmark inspection."""

    document_id: str
    text: str
    score: float
    rank: int
    document_length: int
    term_scores: tuple[BM25TermScore, ...]


@dataclass(frozen=True, slots=True)
class _IndexedDocument:
    document: BM25Document
    terms: Mapping[str, int]
    length: int


class BM25Index:
    """An immutable in-memory corpus scored with canonical Okapi BM25.

    IDF uses the common positive Robertson-Sparck Jones smoothing::

        log(1 + (N - df + 0.5) / (df + 0.5))

    A query term repeated ``qf`` times contributes ``qf`` times its single-term
    score. Results with identical scores are ordered by ``document_id`` so runs
    are reproducible regardless of corpus input order.
    """

    def __init__(
        self,
        documents: Iterable[BM25Document],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if not isfinite(k1) or k1 <= 0:
            raise ValueError("k1 must be finite and greater than zero")
        if not isfinite(b) or not 0 <= b <= 1:
            raise ValueError("b must be finite and between zero and one")

        indexed: list[_IndexedDocument] = []
        seen_ids: set[str] = set()
        document_frequencies: Counter[str] = Counter()
        total_length = 0
        for document in documents:
            if document.document_id in seen_ids:
                raise ValueError(f"duplicate document_id: {document.document_id!r}")
            seen_ids.add(document.document_id)
            frequencies = Counter(tokenize(document.text))
            length = sum(frequencies.values())
            total_length += length
            document_frequencies.update(frequencies.keys())
            indexed.append(
                _IndexedDocument(
                    document=document,
                    terms=MappingProxyType(dict(frequencies)),
                    length=length,
                )
            )

        self.k1 = float(k1)
        self.b = float(b)
        self._documents = tuple(indexed)
        self.document_count = len(indexed)
        self.average_document_length = (
            total_length / self.document_count if self.document_count else 0.0
        )
        self.document_frequencies: Mapping[str, int] = MappingProxyType(dict(document_frequencies))

    @classmethod
    def from_mapping(
        cls,
        documents: Mapping[str, str],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> BM25Index:
        """Build an index from a convenient ``document_id -> text`` mapping."""

        return cls(
            (BM25Document(document_id, text) for document_id, text in documents.items()),
            k1=k1,
            b=b,
        )

    def inverse_document_frequency(self, term: str) -> float:
        """Return the corpus IDF for a term, or zero when it is absent."""

        normalized = tokenize(term)
        if len(normalized) != 1:
            raise ValueError("term must tokenize to exactly one token")
        document_frequency = self.document_frequencies.get(normalized[0], 0)
        if document_frequency == 0 or self.document_count == 0:
            return 0.0
        return log(
            1 + (self.document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )

    def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        include_zero_scores: bool = False,
    ) -> tuple[BM25Result, ...]:
        """Score and rank the corpus for ``query``.

        By default, documents containing none of the query terms are omitted.
        ``include_zero_scores`` is useful when a benchmark needs a complete,
        deterministically ordered corpus ranking.
        """

        if limit is not None and limit < 0:
            raise ValueError("limit must not be negative")
        query_frequencies = Counter(tokenize(query))
        unranked: list[BM25Result] = []
        for indexed in self._documents:
            term_scores = self._score_terms(indexed, query_frequencies)
            score = sum(term.contribution for term in term_scores)
            if score > 0 or include_zero_scores:
                unranked.append(
                    BM25Result(
                        document_id=indexed.document.document_id,
                        text=indexed.document.text,
                        score=score,
                        rank=0,
                        document_length=indexed.length,
                        term_scores=term_scores,
                    )
                )

        ordered = sorted(unranked, key=lambda result: (-result.score, result.document_id))
        if limit is not None:
            ordered = ordered[:limit]
        return tuple(
            BM25Result(
                document_id=result.document_id,
                text=result.text,
                score=result.score,
                rank=rank,
                document_length=result.document_length,
                term_scores=result.term_scores,
            )
            for rank, result in enumerate(ordered, start=1)
        )

    def _score_terms(
        self,
        document: _IndexedDocument,
        query_frequencies: Mapping[str, int],
    ) -> tuple[BM25TermScore, ...]:
        scored: list[BM25TermScore] = []
        for term, query_frequency in query_frequencies.items():
            term_frequency = document.terms.get(term, 0)
            if term_frequency == 0:
                continue
            document_frequency = self.document_frequencies[term]
            inverse_document_frequency = log(
                1 + (self.document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            length_ratio = (
                document.length / self.average_document_length
                if self.average_document_length
                else 0.0
            )
            normalization = self.k1 * (1 - self.b + self.b * length_ratio)
            saturation = term_frequency * (self.k1 + 1) / (term_frequency + normalization)
            contribution = query_frequency * inverse_document_frequency * saturation
            scored.append(
                BM25TermScore(
                    term=term,
                    query_frequency=query_frequency,
                    document_frequency=document_frequency,
                    term_frequency=term_frequency,
                    inverse_document_frequency=inverse_document_frequency,
                    saturation=saturation,
                    contribution=contribution,
                )
            )
        return tuple(scored)
