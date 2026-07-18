from src.guardrails import GuardrailError
from .common import Node
from ..models import RevisionOutput
class ReviserNode(Node):
    name="reviser"
    def run(self,state):
        h=state["current_hypothesis"]
        if state.get("revision_count",0)>=state["maximum_revisions"]:
            return {**state,"errors":[*state.get("errors",[]),"revision_limit"],"falsification_result":state["falsification_result"].model_copy(update={"verdict":"reject"})}
        payload={"hypothesis":h.model_dump(mode="json"),"falsification":state["falsification_result"].model_dump(mode="json"),
          "instruction":"Revise or narrow; do not repeat the same hypothesis and retain valid source chunk IDs."}
        raw=self.deps.model.complete("reviser",payload,RevisionOutput);revision=raw if isinstance(raw,RevisionOutput) else RevisionOutput.model_validate(raw)
        if revision.hypothesis.hypothesis_id!=h.hypothesis_id:raise GuardrailError("revision must retain hypothesis_id")
        if revision.hypothesis==h:raise GuardrailError("identical hypothesis revision rejected")
        self.deps.guard.register_revision(revision.hypothesis,h.hypothesis_id)
        candidates=list(state["candidate_hypotheses"]);candidates[state["current_hypothesis_index"]]=revision.hypothesis
        count=state.get("revision_count",0)+1;by=dict(state.get("revisions_by_hypothesis",{}));by[h.hypothesis_id]=count
        return {**state,"candidate_hypotheses":candidates,"current_hypothesis":revision.hypothesis,"revision_count":count,"revisions_by_hypothesis":by,"errors":[]}
