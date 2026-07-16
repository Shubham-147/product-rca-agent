"""Acceptance tests for lexical and dense taxonomy retrieval."""

from src.retrieval.bm25 import BM25Retriever
from src.retrieval.dense import DenseRetriever
from src.retrieval.embeddings import FakeEmbeddingClient


def test_bm25_finds_checkout_canonical_and_abbreviated_alias() -> None:
    names = {hit.event_name for hit in BM25Retriever().search("checkout start", k=6)}
    assert "checkout_start" in names
    assert "chkout_init" in names


def test_dense_finds_semantically_related_event() -> None:
    retriever = DenseRetriever(FakeEmbeddingClient())
    names = {hit.event_name for hit in retriever.search("fatal application termination", k=5)}
    assert "app_crash" in names


def test_dense_only_can_miss_checkout_alias_that_bm25_catches() -> None:
    dense_names = {
        hit.event_name
        for hit in DenseRetriever(FakeEmbeddingClient()).search("checkout start", k=1)
    }
    bm25_names = {
        hit.event_name for hit in BM25Retriever().search("checkout start", k=6)
    }
    assert "chkout_init" not in dense_names
    assert "chkout_init" in bm25_names

