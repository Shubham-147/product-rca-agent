from src.guardrails import GuardrailError
from .common import Node,remember
class IntakeNode(Node):
    name="intake"
    def run(self,state):
        request=state["request"]
        if not request.instance_id:raise GuardrailError("instance_id is required")
        if request.instance_id!=self.deps.instance_id:raise GuardrailError("request instance_id does not match active System C dependencies")
        summary=remember(self.deps,self.deps.analytics.get_instance_summary(request.instance_id))
        return {**state,"instance_summary":summary,"retrieved_context":[],"candidate_hypotheses":[],
          "current_hypothesis":None,"current_hypothesis_index":-1,"resolved_events":{},"query_results":[],
          "accepted_hypotheses":[],"rejected_hypotheses":[],"revision_count":0,"revisions_by_hypothesis":{},
          "maximum_revisions":self.deps.settings.system_c_max_revisions,"node_execution_count":1,
          "context_retry_used":False,"trace":[],"errors":[],"warnings":[]}
