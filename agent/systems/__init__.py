"""RCA systems — each a `run(task) -> RunResult` over the shared foundation."""

from .base import RunResult, System, load_task
from .system_b import SystemB, build_agent

__all__ = ["System", "RunResult", "load_task", "SystemB", "build_agent"]
