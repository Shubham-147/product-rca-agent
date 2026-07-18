"""Pure routing decisions for System C."""
def after_selector(state):return "ranker" if state.get("current_hypothesis") is None else "event_resolver"
def after_resolution(state):
    if state.get("errors") and state["errors"][-1]=="unresolved_events":
        return "context_retriever" if not state.get("context_retry_used") else "reject"
    return "sql_planner"
def after_context(state):return "event_resolver" if state.get("current_hypothesis") is not None else "hypothesis_generator"
def after_falsifier(state):return {"pass":"accept","revise":"reviser","reject":"reject"}[state["falsification_result"].verdict]
def after_reviser(state):return "reject" if state.get("errors") and state["errors"][-1]=="revision_limit" else "event_resolver"
