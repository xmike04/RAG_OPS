"""Validated runtime configuration for the RAGOps service."""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from ``RAGOPS_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="RAGOPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "RAGOps"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    api_key: SecretStr | None = None
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    database_url: str = "postgresql+asyncpg://ragops:ragops@localhost:5432/ragops"
    database_echo: bool = False
    database_pool_size: int = Field(default=10, ge=1, le=100)
    redis_url: str = "redis://localhost:6379/0"
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    embedding_provider: Literal["local", "sentence-transformers"] = "local"
    embedding_model: str = "deterministic-hash-v1"
    embedding_dimensions: int = Field(default=384, ge=8, le=4096)
    reranker_provider: Literal["local", "sentence-transformers"] = "local"
    reranker_model: str = "deterministic-overlap-v1"
    generation_provider: Literal["local", "openai-compatible"] = "local"
    generation_model: str = "extractive-local-v1"
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: SecretStr | None = None

    default_workspace_id: str = "00000000-0000-0000-0000-000000000001"
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    retrieval_candidate_limit: int = Field(default=40, ge=1, le=500)
    max_document_bytes: int = Field(default=2_000_000, ge=1_024)

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("openai_compatible_base_url")
    @classmethod
    def require_url_for_remote_generation(cls, value: str | None, info: object) -> str | None:
        # Cross-field provider validation is deliberately performed by provider factories,
        # keeping local/demo settings importable without any external credential.
        return value.rstrip("/") if value else value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-in-practice settings instance per process."""

    return Settings()
