"""Acceptance tests for shared real and fake LLM clients."""

import os
from unittest import mock

import pytest

from src.config import get_settings
from src.retrieval.bm25 import BM25Retriever
from src.retrieval.dense import DenseRetriever
from src.retrieval.embeddings import FakeEmbeddingClient
from src.retrieval.hybrid import HybridRetriever
from src.retrieval.reranker import FakeReranker
from src.systems.llm_client import FakeLLMClient, OpenAIClient


def test_openai_client_fails_clearly_without_api_key() -> None:
    get_settings.cache_clear()
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
            OpenAIClient()
    get_settings.cache_clear()


def test_current_pipeline_runs_end_to_end_with_fake_llm() -> None:
    resolver = HybridRetriever(
        BM25Retriever(),
        DenseRetriever(FakeEmbeddingClient()),
        FakeReranker(),
    )
    hits = resolver.resolve_event("checkout start", k=3)
    prompt = "Resolve checkout start using: " + ", ".join(
        hit.event_name for hit in hits
    )
    fake = FakeLLMClient({prompt: "checkout_start is the canonical event."})

    answer = fake.complete(prompt, temperature=0)

    assert hits[0].event_name == "checkout_start"
    assert answer == "checkout_start is the canonical event."
    assert fake.prompts == [prompt]

