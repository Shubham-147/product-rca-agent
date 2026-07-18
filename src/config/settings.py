"""Validated application settings with lazy, cached initialization."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Configuration shared by all three RCA systems.

    Instantiating this class only validates scalar values and paths. It does not
    open a database or initialize retrieval/model clients.
    """

    model_config = SettingsConfigDict(
        env_prefix="RCA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    source_duckdb_path: Path = Path("data/events.duckdb")
    runtime_duckdb_path: Path = Path("runtime/events.duckdb")
    chroma_persist_path: Path = Path("runtime/chroma")

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    llm_model: str = Field(
        default="gpt-4.1-mini",
        validation_alias=AliasChoices("RCA_LLM_MODEL", "OPENAI_MODEL"),
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "RCA_OPENAI_API_KEY"),
        repr=False,
    )

    bm25_candidate_count: int = Field(default=30, ge=1)
    dense_candidate_count: int = Field(default=30, ge=1)
    rerank_candidate_count: int = Field(default=20, ge=1)
    retrieval_top_k: int = Field(default=8, ge=1)
    rrf_constant: int = Field(default=60, ge=1)
    index_batch_size: int = Field(default=64, ge=1)
    max_chunks_per_parent: int = Field(default=2, ge=1)

    sql_result_row_limit: int = Field(default=200, ge=1)
    minimum_segment_size: int = Field(default=50, ge=1)
    system_b_max_tool_calls: int = Field(default=15, ge=1, le=15)
    system_b_max_retrieval_calls: int = Field(default=4, ge=0, le=4)
    system_b_max_analytical_calls: int = Field(default=10, ge=0, le=10)
    system_c_max_revisions: int = Field(default=2, ge=0, le=2)
    # Three candidates with up to two revisions each require as many as 60
    # guarded executions including intake, ranking, and reporting.
    system_c_max_node_executions: int = Field(default=60, ge=1)
    tool_timeout_seconds: float = Field(default=30, gt=0)
    node_timeout_seconds: float = Field(default=60, gt=0)
    max_hypotheses: int = Field(default=5, ge=1)
    max_prompt_chunks: int = Field(default=12, ge=1)
    max_chunk_characters: int = Field(default=6000, ge=100)
    query_timeout_seconds: float = Field(default=30.0, gt=0)
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    api_cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )

    @model_validator(mode="after")
    def validate_retrieval_counts(self) -> "AppSettings":
        if not self.api_cors_origins or any(origin == "*" for origin in self.api_cors_origins):
            raise ValueError("api_cors_origins must contain explicit origins, not '*'")
        if self.retrieval_top_k > self.rerank_candidate_count:
            raise ValueError("retrieval_top_k cannot exceed rerank_candidate_count")
        if self.rerank_candidate_count > (
            self.bm25_candidate_count + self.dense_candidate_count
        ):
            raise ValueError(
                "rerank_candidate_count cannot exceed the combined candidate count"
            )
        if self.system_b_max_retrieval_calls > self.system_b_max_tool_calls:
            raise ValueError(
                "system_b_max_retrieval_calls cannot exceed system_b_max_tool_calls"
            )
        if self.system_b_max_analytical_calls > self.system_b_max_tool_calls:
            raise ValueError("system_b_max_analytical_calls cannot exceed total tool calls")
        return self

    @property
    def logging_level(self) -> int:
        """Return the stdlib logging value without configuring logging."""
        return logging._nameToLevel[self.log_level]


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Build settings on first use and reuse them for the process lifetime."""
    return AppSettings()


def clear_settings_cache() -> None:
    """Clear cached settings, primarily for tests and controlled reconfiguration."""
    get_settings.cache_clear()
