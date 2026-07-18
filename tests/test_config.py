from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import AppSettings, clear_settings_cache, get_settings


@pytest.fixture(autouse=True)
def clear_cached_settings() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RCA_SOURCE_DUCKDB_PATH", "input/source.duckdb")
    monkeypatch.setenv("RCA_RUNTIME_DUCKDB_PATH", "work/runtime.duckdb")
    monkeypatch.setenv("RCA_CHROMA_PERSIST_PATH", "work/chroma")
    monkeypatch.setenv("RCA_LLM_MODEL", "test-model")
    monkeypatch.setenv("RCA_RETRIEVAL_TOP_K", "5")
    monkeypatch.setenv("RCA_RERANK_CANDIDATE_COUNT", "10")
    monkeypatch.setenv("RCA_SYSTEM_B_MAX_TOOL_CALLS", "9")
    monkeypatch.setenv("RCA_SYSTEM_B_MAX_RETRIEVAL_CALLS", "3")
    monkeypatch.setenv("RCA_SYSTEM_B_MAX_ANALYTICAL_CALLS", "8")
    monkeypatch.setenv("RCA_QUERY_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("RCA_LOG_LEVEL", "DEBUG")

    settings = get_settings()

    assert settings.source_duckdb_path == Path("input/source.duckdb")
    assert settings.runtime_duckdb_path == Path("work/runtime.duckdb")
    assert settings.chroma_persist_path == Path("work/chroma")
    assert settings.llm_model == "test-model"
    assert settings.retrieval_top_k == 5
    assert settings.system_b_max_tool_calls == 9
    assert settings.system_b_max_retrieval_calls == 3
    assert settings.query_timeout_seconds == 12.5
    assert settings.log_level == "DEBUG"


def test_settings_are_lazily_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RCA_LLM_MODEL", "first-model")
    first = get_settings()
    monkeypatch.setenv("RCA_LLM_MODEL", "second-model")

    assert get_settings() is first
    assert get_settings().llm_model == "first-model"

    clear_settings_cache()
    assert get_settings().llm_model == "second-model"


def test_imports_do_not_initialize_external_resources() -> None:
    code = """
import sys
import src.config
import src.observability
import src.schemas
for name in ('duckdb', 'chromadb', 'sentence_transformers', 'openai'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_invalid_retrieval_counts_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AppSettings(retrieval_top_k=21, rerank_candidate_count=20)
