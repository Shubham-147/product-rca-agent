from src.analytics import SUPPORTED_METRICS
from src.guardrails import compile_cohort
from .common import Node
from .utils import row_sample_size
from ..models import ValidationResult
class ValidatorNode(Node):
    name="validator"
    def run(self,state):
        results=state.get("query_results",[]);plan=state["query_plan"];reasons=[]
        cohort_valid=True
        try:compile_cohort(state["request"].instance_id,state["current_hypothesis"].expected_cohort)
        except Exception as exc:cohort_valid=False;reasons.append("cohort does not compile")
        sufficient=any(row_sample_size(row)>=self.deps.settings.minimum_segment_size for r in results for row in r.rows)
        denominator=all(item.metric is None or item.metric in SUPPORTED_METRICS for item in plan.items)
        resolution=all(event in state.get("resolved_events",{}) for item in plan.items for event in item.required_canonical_events)
        temporal=True
        for item,result in zip(plan.items,results):
            if item.operation=="event_sequence":
                counts=[row.get("users",0) for row in result.rows];temporal=temporal and counts==sorted(counts,reverse=True)
        consistent=all(r.query_id in self.deps.known_query_results and r.rows for r in results)
        supported=bool(results and sufficient and denominator and resolution and temporal and cohort_valid and consistent)
        if not sufficient:reasons.append("sample size below minimum")
        if not temporal:reasons.append("temporal ordering contradicted")
        return {**state,"validation_result":ValidationResult(supported=supported,sufficient_sample=sufficient,
          denominator_valid=denominator,event_resolution_valid=resolution,temporal_order_valid=temporal,
          cohort_valid=cohort_valid,evidence_consistent=consistent,query_ids=[r.query_id for r in results],reasons=reasons)}
