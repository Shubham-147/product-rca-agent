from .common import Node
class RankerNode(Node):
    name="ranker"
    def run(self,state):
        ranked=[]
        for item in state.get("accepted_hypotheses",[]):
            score=.30*item.evidence_strength+.20*item.effect_size_score+.15*item.cohort_specificity+.15*item.temporal_precedence+.20*item.falsification_resistance
            ranked.append(item.model_copy(update={"rank_score":score}))
        ranked.sort(key=lambda x:(-x.rank_score,x.hypothesis.hypothesis_id));ranked=[x.model_copy(update={"rank":i}) for i,x in enumerate(ranked,1)]
        return {**state,"ranked_hypotheses":ranked}
