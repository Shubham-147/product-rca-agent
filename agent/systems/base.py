"""The System contract — every architecture (A, B, C) is one `run(task) -> RunResult`.

Keeps the integration surface identical across systems so the eval harness scores them
apples-to-apples (design decision D5). `RunResult` carries the scored artefact (the
`Hypothesis` list) plus the run's cost/latency counters — first-class metrics, not
afterthoughts (tenet #6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..contracts import AgentHypothesis, Hypothesis


@dataclass
class RunResult:
    system: str
    instance_id: str
    hypotheses: list[Hypothesis]                       # bridged, scorer-ready
    agent_output: list[AgentHypothesis] = field(default_factory=list)  # DSL form
    n_requests: int = 0
    n_tool_calls: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    trace: object = None                               # RunTrace — the ReAct loop record
    error: str | None = None                           # set if the run failed/aborted


class System(Protocol):
    name: str

    def run(self, task_path: str | Path) -> RunResult: ...


def load_task(task_path: str | Path) -> dict:
    return json.loads(Path(task_path).read_text())
