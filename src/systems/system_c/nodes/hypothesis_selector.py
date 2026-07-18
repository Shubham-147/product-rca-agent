from .common import Node
class HypothesisSelectorNode(Node):
    name="hypothesis_selector"
    def run(self,state):
        # Reserve two terminal nodes and a complete seven-node investigation
        # pass. Gracefully rank what is already accepted instead of hitting the
        # graph guard mid-hypothesis.
        if self.deps.guard.nodes + 9 > self.deps.guard.max_nodes:
            return {**state,"current_hypothesis":None,"current_hypothesis_index":-1,
              "warnings":[*state.get("warnings",[]),"graph budget ended further hypothesis testing"]}
        resolved={x.hypothesis.hypothesis_id for x in state.get("accepted_hypotheses",[])}|{x.hypothesis_id for x in state.get("rejected_hypotheses",[])}
        for i,h in enumerate(state.get("candidate_hypotheses",[])):
            if h.hypothesis_id not in resolved:return {**state,"current_hypothesis":h,"current_hypothesis_index":i,"revision_count":state.get("revisions_by_hypothesis",{}).get(h.hypothesis_id,0),"errors":[]}
        return {**state,"current_hypothesis":None,"current_hypothesis_index":-1}
