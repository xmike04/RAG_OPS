"""Public retrieval API."""

from .bm25 import BM25Document, BM25Index, BM25Result, BM25TermScore
from .context import AssembledContext, Citation, assemble_context
from .fusion import reciprocal_rank_fusion, rerank_shortlist
from .models import RetrievalCandidate, ScoreContribution, SearchHit, SearchResult
from .repository import (
    HybridCandidateRepository,
    PostgreSQLHybridCandidateRepository,
    PostgreSQLRepositoryConfig,
)
from .tokenization import normalize_text, token_count, tokenize

__all__ = [
    "AssembledContext",
    "BM25Document",
    "BM25Index",
    "BM25Result",
    "BM25TermScore",
    "Citation",
    "HybridCandidateRepository",
    "PostgreSQLHybridCandidateRepository",
    "PostgreSQLRepositoryConfig",
    "RetrievalCandidate",
    "ScoreContribution",
    "SearchHit",
    "SearchResult",
    "assemble_context",
    "normalize_text",
    "reciprocal_rank_fusion",
    "rerank_shortlist",
    "token_count",
    "tokenize",
]
