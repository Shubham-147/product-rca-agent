"""Run trace — a readable record of the agent's ReAct loop (keyless observability).

Until the Phoenix Cloud spine is wired (needs the API key), this gives immediate
visibility into *how the agent loops*: every reasoning step, tool call + arguments,
the observation it got back, and the final hypotheses. Built from the pydantic-ai
message history (`result.all_messages()`), rendered to markdown per run.

This is also the shape the UI's SSE trace protocol will consume later, so instrumenting
once here pays off twice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.messages import (
    ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart,
)


@dataclass
class TraceStep:
    kind: str            # "think" | "tool_call" | "tool_result"
    tool: str | None = None
    detail: str = ""     # reasoning text, call args (json), or result summary


@dataclass
class RunTrace:
    system: str
    instance_id: str
    model: str
    steps: list[TraceStep] = field(default_factory=list)

    @property
    def n_tool_calls(self) -> int:
        return sum(s.kind == "tool_call" for s in self.steps)


def _summarize(content) -> str:
    """Compact a tool result (often a big pydantic model / dict) for the trace."""
    try:
        if hasattr(content, "model_dump"):
            content = content.model_dump()
        s = json.dumps(content, default=str)
    except Exception:
        s = str(content)
    return s if len(s) <= 600 else s[:600] + f" …(+{len(s) - 600} chars)"


def extract_trace(system: str, instance_id: str, model: str, messages) -> RunTrace:
    tr = RunTrace(system=system, instance_id=instance_id, model=model)
    for m in messages:
        for p in getattr(m, "parts", []):
            if isinstance(p, ToolCallPart):
                args = p.args if isinstance(p.args, str) else json.dumps(p.args, default=str)
                tr.steps.append(TraceStep("tool_call", p.tool_name, args))
            elif isinstance(p, ToolReturnPart):
                tr.steps.append(TraceStep("tool_result", p.tool_name, _summarize(p.content)))
            elif isinstance(p, TextPart) and p.content.strip():
                tr.steps.append(TraceStep("think", None, p.content.strip()))
    return tr


_GLYPH = {"think": "💭", "tool_call": "🔧", "tool_result": "↳ "}


def render_md(tr: RunTrace, hypotheses=None, score: dict | None = None) -> str:
    lines = [f"# Trace — System {tr.system} · {tr.instance_id} · {tr.model}",
             f"\n**{tr.n_tool_calls} tool calls**\n", "---\n"]
    for i, s in enumerate(tr.steps, 1):
        if s.kind == "tool_call":
            lines.append(f"**{i}. 🔧 {s.tool}**  `{s.detail}`")
        elif s.kind == "tool_result":
            lines.append(f"   ↳ _{s.tool}_ → {s.detail}")
        else:
            lines.append(f"**{i}. 💭** {s.detail}")
    if hypotheses is not None:
        lines.append("\n---\n## Hypotheses emitted")
        for h in hypotheses:
            lines.append(f"- **{h.mechanism_type}** · cohort `{h.affected_cohort}` · conf {h.confidence}")
    if score:
        lines.append(f"\n## Score\n```\n{json.dumps(score, indent=1, default=str)}\n```")
    return "\n".join(lines) + "\n"


def write_trace(tr: RunTrace, out_dir: Path, hypotheses=None, score: dict | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"system_{tr.system}_{tr.instance_id}.md"
    path.write_text(render_md(tr, hypotheses, score))
    return path
