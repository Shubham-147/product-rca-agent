from .common import Node
from ..models import RejectedHypothesis
class RejectNode(Node):
    name="reject"
    def run(self,state):
        h=state["current_hypothesis"];f=state.get("falsification_result");reason=f.falsification_summary if f else "unresolved or untestable hypothesis"
        return {**state,"rejected_hypotheses":[*state.get("rejected_hypotheses",[]),RejectedHypothesis(hypothesis_id=h.hypothesis_id,reason=reason)],"current_hypothesis":None,"errors":[]}
