"""Scaffold self-test — drive System B end-to-end with NO API key.

Uses a scripted `FunctionModel` (a stand-in "brain") that makes the same realistic
tool calls a good agent would, then emits a final hypothesis. Proves the whole loop is
wired: tools are registered and callable with deps flowing, observations return typed,
the output validates through the Cohort DSL and bridges to a scorer-ready `Hypothesis`,
and the run reports usage. Swap `FunctionModel` for the real proxy model and nothing
else changes.

Run:  ../.venv/bin/python -m agent.systems.scaffold_check
"""

from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ..systems.system_b import SystemB

# A realistic investigation of inst_001 (the checkout_latency instance): find the drop,
# confirm the mechanism + cohort, rule out a confounder, size the cohort, then conclude.
_SCRIPT = [
    ("funnel", {}),
    ("metric_by_segment", {"metric": "checkout_p95", "segment_by": ["os"]}),
    ("metric_by_segment", {"metric": "conversion:checkout_start->payment_submit",
                            "segment_by": ["os"]}),
    ("metric_by_segment", {"metric": "checkout_p95", "segment_by": ["device_type"],
                            "where": {"all": [{"col": "os", "op": "eq", "value": "iOS 17"}]}}),
    ("cohort_resolve", {"cohort": {"all": [{"col": "os", "op": "eq", "value": "iOS 17"}]}}),
]

_FINAL_HYPOTHESIS = {
    "mechanism_type": "checkout_latency",
    "mechanism": "Checkout-screen p95 render latency on iOS 17 rose from ~1.3s to ~4.8s "
                 "after the changepoint, breaching the <2000ms SLO and suppressing "
                 "checkout->payment conversion.",
    "affected_cohort": {"all": [{"col": "os", "op": "eq", "value": "iOS 17"}], "any": []},
    "evidence": [
        {"claim": "iOS 17 checkout p95 1294->4778ms",
         "sql": "quantile_cont(latency_ms,0.95) WHERE screen='checkout' GROUP BY period,os",
         "result_summary": "iOS 17 pre=1294 post=4778 (+3484ms); Androids <+520ms"},
        {"claim": "conversion drop concentrated on iOS 17",
         "sql": "P(payment_submit|checkout_start) GROUP BY period,os",
         "result_summary": "iOS 17 82.6->73.2 (-9.4pp); others ~flat"},
    ],
    "confidence": 0.86,
    "confounders_considered": [
        "device age (latency rises across all iOS device tiers, not just old ones)",
        "traffic-mix shift (drop is within-cohort, not a composition change)",
    ],
}


def make_scripted_model() -> FunctionModel:
    """A FunctionModel that walks the script, printing each step, then emits output."""
    step = {"i": 0}

    def brain(messages, info: AgentInfo) -> ModelResponse:
        i = step["i"]
        step["i"] += 1
        if i < len(_SCRIPT):
            name, args = _SCRIPT[i]
            print(f"  [turn {i+1}] tool -> {name}({args})")
            return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])
        out_tool = info.output_tools[0].name  # 'final_result', wraps list under 'response'
        print(f"  [turn {i+1}] emit -> {out_tool}(1 hypothesis)")
        return ModelResponse(parts=[ToolCallPart(tool_name=out_tool,
                                                 args={"response": [_FINAL_HYPOTHESIS]})])

    return FunctionModel(brain)


def main() -> None:
    print("Running System B on inst_001 with a scripted stub model (no API key)...\n")
    sysb = SystemB()
    res = sysb.run("data/tasks/task_inst_001.json", model=make_scripted_model())

    print(f"\nsystem={res.system}  instance={res.instance_id}  error={res.error}")
    print(f"requests={res.n_requests}  tool_calls={res.n_tool_calls}  tokens={res.total_tokens}")
    print(f"hypotheses returned: {len(res.hypotheses)}")
    for h in res.hypotheses:
        print(f"\n  mechanism_type : {h.mechanism_type}")
        print(f"  affected_cohort: {h.affected_cohort!r}   ({type(h.affected_cohort).__name__})")
        print(f"  confidence     : {h.confidence}")
        print(f"  evidence rows  : {len(h.evidence)}")
        print(f"  confounders    : {len(h.confounders_considered)}")

    assert not res.error, res.error
    assert len(res.hypotheses) == 1
    assert res.hypotheses[0].mechanism_type == "checkout_latency"
    assert res.hypotheses[0].affected_cohort == "os = 'iOS 17'"  # DSL -> SQL bridge
    print("\nOK — scaffold wired: tools called, typed output validated, DSL bridged.")


if __name__ == "__main__":
    main()
