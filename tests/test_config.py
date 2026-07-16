"""Tests for src.config settings loader."""

import os
from unittest import mock

import pytest

from src.config import Settings, get_settings


def test_settings_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(openai_api_key="")


def test_get_settings_raises_without_key() -> None:
    get_settings.cache_clear()
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
            get_settings()
    get_settings.cache_clear()


def test_get_settings_succeeds_with_key() -> None:
    get_settings.cache_clear()
    with mock.patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "sk-test-dummy-key", "OPENAI_MODEL": "gpt-4o-mini"},
        clear=False,
    ):
        settings = get_settings()
    get_settings.cache_clear()
    assert settings.openai_api_key == "sk-test-dummy-key"
    assert settings.openai_model == "gpt-4o-mini"
