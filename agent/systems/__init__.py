"""RCA systems — each a `run(task) -> RunResult` over the shared foundation."""

from .base import RunResult, System, load_task
from .system_a import SystemA
from .system_b import SystemB, build_agent
from .system_c import SystemC, build_falsifier, build_graph, build_investigator

__all__ = [
    "System", "RunResult", "load_task", "SystemA", "SystemB", "SystemC",
    "build_agent", "build_investigator", "build_falsifier", "build_graph",
]
