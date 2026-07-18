from datetime import datetime,timezone
from src.guardrails import validate_report
from src.schemas import RCAReport,RootCauseHypothesis,RunMetadata,RunStatus
from .common import Node,remember
class ReporterNode(Node):
    name="reporter"
    def run(self,state):
        request=state["request"];hypotheses=[]
        materialized_items=[]
        for item in state.get("ranked_hypotheses",[]):
            materialized=remember(self.deps,self.deps.analytics.materialize_cohort(self.deps.run_id,"system_c",item.hypothesis.hypothesis_id,item.hypothesis.expected_cohort))
            item.materialized_query_id=materialized.query_id
            materialized_items.append(item.model_copy(update={"materialized_query_id":materialized.query_id}))
            hypotheses.append(RootCauseHypothesis(hypothesis_id=item.hypothesis.hypothesis_id,rank=item.rank,
              mechanism=item.hypothesis.proposed_mechanism,affected_cohort=item.hypothesis.expected_cohort,
              resolved_events=item.hypothesis.required_events,evidence=item.evidence,confounders=item.confounders,
              confidence=min(1,max(0,item.rank_score)),limitations=[*item.limitations,
                f"Materialized cohort reference: {materialized.query_id}"]))
        warnings=list(dict.fromkeys(state.get("warnings",[])))
        now=datetime.now(timezone.utc);report=RCAReport(instance_id=request.instance_id,symptom=request.symptom,hypotheses=hypotheses,
          unresolved_questions=warnings,run_metadata=RunMetadata(run_id=self.deps.run_id,system_name="system_c",instance_id=request.instance_id,start_time=now,completion_time=now,status=RunStatus.COMPLETED))
        validate_report(report,query_ids=set(self.deps.known_query_results),source_chunk_ids=self.deps.known_chunk_ids,
          event_resolutions=state.get("resolved_events",{}),max_hypotheses=self.deps.settings.max_hypotheses)
        return {**state,"report":report,"ranked_hypotheses":materialized_items}
