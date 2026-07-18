from .common import Node
from ..models import HypothesisBatch
class HypothesisGeneratorNode(Node):
    name="hypothesis_generator"
    def run(self,state):
        if state.get("candidate_hypotheses"):return state
        payload={"request":state["request"].model_dump(mode="json"),"instance_summary":state["instance_summary"].model_dump(mode="json"),
          "context":state["retrieved_context"],"requirements":"Generate 3-5 testable candidates, including benign explanations where relevant. Use only supplied chunk IDs."}
        raw=self.deps.model.complete("hypothesis_generator",payload,HypothesisBatch)
        batch=raw if isinstance(raw,HypothesisBatch) else HypothesisBatch.model_validate(raw)
        for h in batch.hypotheses:
            if h.expected_cohort.instance_id!=state["request"].instance_id:raise ValueError("candidate cohort instance mismatch")
            if set(h.context_chunk_ids)-self.deps.known_chunk_ids:raise ValueError("candidate references unknown context")
        return {**state,"candidate_hypotheses":batch.hypotheses}
