"""Guarded DuckDB access shared by all Product RCA systems."""

from .manager import DuckDBManager, clear_duckdb_manager, get_duckdb_manager
from .models import QueryResult

__all__ = ["DuckDBManager", "QueryResult", "clear_duckdb_manager", "get_duckdb_manager"]
