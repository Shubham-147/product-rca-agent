from .common import Node
from .utils import evidence_from_results
from ..models import AcceptedHypothesis
class AcceptNode(Node):
    name="accept"
    def run(self,state):
        h=state["current_hypothesis"];f=state["falsification_result"];evidence=evidence_from_results(state["query_results"],h.context_chunk_ids)
        effect=min(1,max((abs(e.observed_value) for e in evidence),default=0));specificity=min(1,sum(getattr(h.expected_cohort,x) is not None for x in ["os","device_type","geo","channel","is_returning","payment_method","device_age_min","device_age_max"])/3)
        accepted=AcceptedHypothesis(hypothesis=h,evidence=evidence,confounders=f.confounders_found,
          limitations=["Observational telemetry cannot establish causal certainty.",f.falsification_summary],evidence_strength=min(1,len(evidence)/3),
          effect_size_score=effect,cohort_specificity=specificity,temporal_precedence=1 if state["validation_result"].temporal_order_valid else 0,
          falsification_resistance=f.falsification_score)
        return {**state,"accepted_hypotheses":[*state.get("accepted_hypotheses",[]),accepted],"current_hypothesis":None}
