import hashlib
from src.guardrails import GuardrailError,compile_cohort
from .common import Node,remember
class SQLExecutorNode(Node):
    name="sql_executor"
    def run(self,state):
        known=set(state.get("resolved_events",{}));results=[]
        for item in state["query_plan"].items:
            if set(item.required_canonical_events)-known:raise GuardrailError("unresolved events cannot reach SQL Executor")
            if item.cohort:compile_cohort(state["request"].instance_id,item.cohort)
            key=hashlib.sha256(item.model_dump_json().encode()).hexdigest()
            cached=key in self.deps.query_cache
            if cached:result=self.deps.query_cache[key]
            elif item.operation=="funnel":result=self.deps.analytics.get_ordered_funnel(state["request"].instance_id,item.required_canonical_events,item.same_session)
            elif item.operation=="metric_by_dimension":result=self.deps.analytics.compare_metric_by_dimension(state["request"].instance_id,item.metric,item.dimension,item.cohort,self.deps.settings.minimum_segment_size)
            elif item.operation=="event_sequence":result=self.deps.analytics.analyse_event_sequence(state["request"].instance_id,item.required_canonical_events[0],item.required_canonical_events[1:-1],item.required_canonical_events[-1],item.cohort)
            else:
                if not item.exposure or not item.control:raise GuardrailError("exposed/control plan requires both cohorts")
                result=self.deps.analytics.compare_exposed_unexposed(state["request"].instance_id,item.exposure,item.control,item.required_canonical_events[-1])
            if key not in self.deps.query_cache:self.deps.query_cache[key]=result
            results.append(remember(self.deps,result));self.deps.logger.log(tool="system_c_sql_executor",query_id=result.query_id,sql=result.executed_sql,parameters=result.parameters,result_size=result.row_count,result_summary=result.result_summary,duration_ms=result.duration_ms,cache_status="hit" if cached else "miss")
        return {**state,"query_results":results}
