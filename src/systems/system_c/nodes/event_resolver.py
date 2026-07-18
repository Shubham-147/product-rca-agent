from src.guardrails import require_resolved_event,GuardrailError
from .common import Node
class EventResolverNode(Node):
    name="event_resolver"
    def run(self,state):
        hypothesis=state["current_hypothesis"];resolved=dict(state.get("resolved_events",{}));warnings=list(state.get("warnings",[]))
        try:
            for concept in hypothesis.required_events:
                result=self.deps.resolver.resolve(concept,screen=state["request"].suspected_screen,funnel_name=state["request"].funnel_name,top_k=5)
                guarded=require_resolved_event(result,concept);resolved[guarded.canonical_event]=result
                if guarded.warning:warnings.append(guarded.warning)
            self.deps.manager.set_alias_mappings(self.deps.resolver.alias_mappings())
            return {**state,"resolved_events":resolved,"warnings":warnings,"errors":[e for e in state.get("errors",[]) if e!="unresolved_events"]}
        except GuardrailError:
            return {**state,"errors":[*state.get("errors",[]),"unresolved_events"],"warnings":[*warnings,"hypothesis has unresolved required events"]}
