"""LangGraph construction and runnable System C orchestration."""
from __future__ import annotations
import argparse,json,uuid,warnings
try:
    from langchain_core._api import LangChainPendingDeprecationWarning
    warnings.filterwarnings("ignore",category=LangChainPendingDeprecationWarning)
except ImportError:pass
from typing import Any
from pydantic import BaseModel
from src.analytics import DeterministicAnalytics
from src.config import AppSettings,get_settings
from src.database import DuckDBManager
from src.guardrails import SafeAuditLogger,SystemCGraphGuard
from src.retrieval import CanonicalEventResolver
from src.schemas import AnalysisRequest,RCAReport
from src.systems.bootstrap import load_runtime_assets
from src.systems.cli import add_request_arguments,analysis_request_from_args
from .nodes import *
from .nodes.common import SystemCDependencies
from .routing import *
from .state import SystemCState

warnings.filterwarnings("ignore",message="The default value of `allowed_objects` will change.*")

class OpenAIStructuredModel:
    def __init__(self,model,api_key=None):self.model=model;self.api_key=api_key;self._client=None
    def complete(self,task,payload,output_type):
        if self._client is None:
            from openai import OpenAI
            self._client=OpenAI(api_key=self.api_key)
        prompt="Return only a JSON object matching the supplied JSON schema. "+json.dumps(
          {"task":task,"input":payload,"schema":output_type.model_json_schema()})
        response=self._client.chat.completions.create(model=self.model,temperature=.1,messages=[{"role":"user","content":prompt}],response_format={"type":"json_object"})
        return output_type.model_validate_json(response.choices[0].message.content)

def build_graph(deps:SystemCDependencies):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore",message="The default value of `allowed_objects` will change.*")
        from langgraph.graph import END,START,StateGraph
    graph=StateGraph(SystemCState)
    nodes={"intake":IntakeNode(deps),"context_retriever":ContextRetrieverNode(deps),"hypothesis_generator":HypothesisGeneratorNode(deps),
      "hypothesis_selector":HypothesisSelectorNode(deps),"event_resolver":EventResolverNode(deps),"sql_planner":SQLPlannerNode(deps),
      "sql_executor":SQLExecutorNode(deps),"validator":ValidatorNode(deps),"falsifier":FalsifierNode(deps),"reviser":ReviserNode(deps),
      "accept":AcceptNode(deps),"reject":RejectNode(deps),"ranker":RankerNode(deps),"reporter":ReporterNode(deps)}
    for name,node in nodes.items():graph.add_node(name,node)
    graph.add_edge(START,"intake");graph.add_edge("intake","context_retriever")
    graph.add_conditional_edges("context_retriever",after_context,{"hypothesis_generator":"hypothesis_generator","event_resolver":"event_resolver"})
    graph.add_edge("hypothesis_generator","hypothesis_selector")
    graph.add_conditional_edges("hypothesis_selector",after_selector,{"ranker":"ranker","event_resolver":"event_resolver"})
    graph.add_conditional_edges("event_resolver",after_resolution,{"context_retriever":"context_retriever","reject":"reject","sql_planner":"sql_planner"})
    graph.add_edge("sql_planner","sql_executor");graph.add_edge("sql_executor","validator");graph.add_edge("validator","falsifier")
    graph.add_conditional_edges("falsifier",after_falsifier,{"accept":"accept","reviser":"reviser","reject":"reject"})
    graph.add_conditional_edges("reviser",after_reviser,{"reject":"reject","event_resolver":"event_resolver"})
    graph.add_edge("accept","hypothesis_selector");graph.add_edge("reject","hypothesis_selector")
    graph.add_edge("ranker","reporter");graph.add_edge("reporter",END)
    return graph.compile()

class SystemCWorkflow:
    def __init__(self,deps:SystemCDependencies):self.deps=deps;self.graph=build_graph(deps)
    def run(self,request:AnalysisRequest)->RCAReport:
        from datetime import datetime,timezone
        started=datetime.now(timezone.utc);m=self.deps.manager
        m.record_run(run_id=self.deps.run_id,system_name="system_c",instance_id=request.instance_id,started_at=started,status="running")
        try:
            state=self.graph.invoke({"request":request},{"recursion_limit":self.deps.settings.system_c_max_node_executions+5})
            report=state["report"];m.record_run(run_id=self.deps.run_id,system_name="system_c",instance_id=request.instance_id,
              started_at=started,completed_at=datetime.now(timezone.utc),status="completed",validated=True,
              metadata={"node_executions":self.deps.guard.nodes,"accepted":len(report.hypotheses),"rejected":len(state.get("rejected_hypotheses",[]))})
            return report
        except Exception as exc:
            m.record_run(run_id=self.deps.run_id,system_name="system_c",instance_id=request.instance_id,started_at=started,
              completed_at=datetime.now(timezone.utc),status="failed",metadata={"error":type(exc).__name__,"node_executions":self.deps.guard.nodes});raise

def build_dependencies(instance_id,settings,retriever,resolver,manager,model):
    return SystemCDependencies(DeterministicAnalytics(manager),retriever,resolver,manager,model,
      SystemCGraphGuard(settings.system_c_max_revisions,settings.system_c_max_node_executions,settings.node_timeout_seconds),SafeAuditLogger(),settings,instance_id,f"run_{uuid.uuid4().hex}")

def main():
    parser=argparse.ArgumentParser(prog="run-system-c");add_request_arguments(parser);args=parser.parse_args()
    assets=load_runtime_assets(args.instance_id,args.data_root,get_settings())
    key=assets.settings.openai_api_key.get_secret_value() if assets.settings.openai_api_key else None
    deps=build_dependencies(args.instance_id,assets.settings,assets.retriever,assets.resolver,assets.manager,OpenAIStructuredModel(assets.settings.llm_model,key))
    print(SystemCWorkflow(deps).run(analysis_request_from_args(args)).model_dump_json(indent=2))
if __name__=="__main__":main()
