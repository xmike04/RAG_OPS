"""Deterministic document ingestion primitives.

The package intentionally contains no database or provider imports.  Application
code supplies those dependencies through the protocols in :mod:`pipeline`.
"""

from .chunking import Chunk, ChunkingConfig, TokenAwareChunker
from .metadata import MetadataLimits, MetadataValidationError, validate_metadata
from .normalization import (
    ContentFormat,
    ContentValidationError,
    NormalizedDocument,
    normalize_document,
)
from .pipeline import (
    EmbeddingProvider,
    IngestionPipeline,
    IngestionRepository,
    IngestionWorkItem,
    ProcessingOutcome,
)
from .state import JobStatus, RetryPolicy, validate_transition

__all__ = [
    "Chunk",
    "ChunkingConfig",
    "ContentFormat",
    "ContentValidationError",
    "EmbeddingProvider",
    "IngestionPipeline",
    "IngestionRepository",
    "IngestionWorkItem",
    "JobStatus",
    "MetadataLimits",
    "MetadataValidationError",
    "NormalizedDocument",
    "ProcessingOutcome",
    "RetryPolicy",
    "TokenAwareChunker",
    "normalize_document",
    "validate_metadata",
    "validate_transition",
]
