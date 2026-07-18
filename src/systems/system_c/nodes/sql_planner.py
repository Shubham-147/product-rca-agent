from .common import Node
from ..models import QueryPlanItem,TypedQueryPlan
class SQLPlannerNode(Node):
    name="sql_planner"
    def run(self,state):
        h=state["current_hypothesis"];events=h.required_events;cohort=h.expected_cohort
        items=[]
        if len(events)>=2:items.append(QueryPlanItem(query_key="temporal",question="Do required events occur in order?",operation="event_sequence",cohort=cohort,
          expected_observation_if_true=h.expected_observations[0] if h.expected_observations else "ordered progression differs",required_canonical_events=events))
        dimension=next((d for d in ["os","device_type","geo","channel","is_returning","payment_method"] if getattr(cohort,d,None) is not None),"os")
        metric="crash_rate" if "crash" in h.proposed_mechanism.lower() else "checkout_completion_rate"
        items.append(QueryPlanItem(query_key="segment",question="Is the mechanism concentrated in its expected segment?",operation="metric_by_dimension",metric=metric,dimension=dimension,cohort=cohort,
          expected_observation_if_true=h.expected_observations[-1] if h.expected_observations else "segment differs",potential_confounder=h.possible_confounders[0] if h.possible_confounders else None,required_canonical_events=events))
        return {**state,"query_plan":TypedQueryPlan(items=items),"query_results":[]}
