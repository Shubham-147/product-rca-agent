"""One Pydantic AI agent coordinating System B's bounded typed tools."""
from __future__ import annotations

import argparse,json,time,uuid
from dataclasses import asdict,is_dataclass
from datetime import datetime,timezone
from typing import Any,Protocol

from src.analytics import DeterministicAnalytics
from src.config import AppSettings,get_settings
from src.database import DuckDBManager
from src.guardrails import SafeAuditLogger
from src.observability import write_daily_openai_payload
from src.retrieval import CanonicalEventResolver
from src.schemas import AnalysisRequest,RCAReport,RunMetadata,RunStatus
from src.systems.bootstrap import load_runtime_assets
from src.systems.cli import add_request_arguments,analysis_request_from_args

from .budgets import build_tool_guard
from .dependencies import QueryCache,SystemBDependencies
from .instructions import SYSTEM_B_INSTRUCTIONS
from .output_validator import validate_system_b_output
from .tools import *


class AgentRunner(Protocol):
    def run_sync(self,prompt:str,*,deps:SystemBDependencies)->Any:...


class PydanticAIRunner:
    def __init__(self,model:str,api_key:str|None=None):self.model=model;self.api_key=api_key;self._agent=None
    def _build(self):
        if self._agent is not None:return self._agent
        from pydantic_ai import Agent,RunContext
        from pydantic_ai import ModelRetry
        from src.guardrails import GuardrailError
        model=self.model
        if self.api_key and self.model!="test":
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider
            model=OpenAIChatModel(self.model.removeprefix("openai:"),provider=OpenAIProvider(api_key=self.api_key))
        agent=Agent(model,deps_type=SystemBDependencies,output_type=RCAReport,
          instructions=SYSTEM_B_INSTRUCTIONS,retries=2,output_retries=2)
        def register(name,input_type,method):
            async def tool(ctx:RunContext[SystemBDependencies],args:input_type):
                try:return getattr(SystemBTools(ctx.deps),method)(args)
                except GuardrailError as exc:
                    if "budget exceeded" in str(exc):
                        return {"status":"rejected","reason":"tool budget exhausted; stop calling tools and return the best supported report"}
                    raise ModelRetry("guardrail rejected this typed call; correct the arguments without weakening guardrails") from exc
            tool.__name__=name
            # The registration factory is intentionally dynamic; replace
            # postponed annotations with concrete runtime types for Pydantic AI.
            tool.__annotations__={"ctx":RunContext[SystemBDependencies],"args":input_type}
            agent.tool(tool)
        registrations=[
          ("search_knowledge",SearchKnowledgeInput,"search_knowledge"),("resolve_events",ResolveEventsInput,"resolve_events"),
          ("get_instance_summary",InstanceSummaryInput,"get_instance_summary"),("build_funnel",BuildFunnelInput,"build_funnel"),
          ("compare_metric_by_dimension",CompareMetricInput,"compare_metric_by_dimension"),
          ("analyse_event_sequence",EventSequenceInput,"analyse_event_sequence"),
          ("compare_exposed_unexposed",ExposedControlInput,"compare_exposed_unexposed"),
          ("test_confounder",ConfounderTestInput,"test_confounder"),("materialize_cohort",MaterializeCohortInput,"materialize_cohort")]
        for item in registrations:register(*item)
        self._agent=agent;return agent
    def run_sync(self,prompt,*,deps):
        write_daily_openai_payload(system_name="system_b",stage="agent_initial_request",model=self.model,
          payload={"instructions":SYSTEM_B_INSTRUCTIONS,"prompt":prompt,
            "tools":list(self._build()._function_toolset.tools)})
        return self._build().run_sync(prompt,deps=deps)


class SystemBAgent:
    def __init__(self,*,deps:SystemBDependencies,runner:AgentRunner,settings:AppSettings):
        self.deps=deps;self.runner=runner;self.settings=settings
    def run(self,request:AnalysisRequest)->RCAReport:
        if request.instance_id!=self.deps.instance_id:raise ValueError("request instance does not match dependencies")
        started=datetime.now(timezone.utc);manager=self.deps.safe_query_executor
        manager.record_run(run_id=self.deps.run_id,system_name="system_b",instance_id=request.instance_id,started_at=started,status="running")
        metadata=RunMetadata(run_id=self.deps.run_id,system_name="system_b",instance_id=request.instance_id,start_time=started)
        prompt=json.dumps({"request":request.model_dump(mode="json"),"required_run_metadata":metadata.model_dump(mode="json")})
        before=time.perf_counter()
        try:
            result=self.runner.run_sync(prompt,deps=self.deps);latency=(time.perf_counter()-before)*1000
            output=getattr(result,"output",result)
            # The request envelope is trusted application state, not analytical
            # model output. Preserve it verbatim even if the model paraphrases
            # the symptom or echoes an incorrect instance identifier.
            if isinstance(output,RCAReport):
                report=output.model_copy(update={"instance_id":request.instance_id,"symptom":request.symptom,
                  "run_metadata":metadata})
            else:
                output={**output,"instance_id":request.instance_id,"symptom":request.symptom,
                  "run_metadata":metadata.model_dump(mode="json")}
                report=RCAReport.model_validate(output)
            report=validate_system_b_output(report,request,self.deps,self.settings)
            for hypothesis in report.hypotheses:
                if hypothesis.hypothesis_id not in self.deps.materialized_hypotheses:
                    materialized=self.deps.cohort_materializer(self.deps.run_id,"system_b",
                        hypothesis.hypothesis_id,hypothesis.affected_cohort)
                    self.deps.remember_query(materialized);self.deps.materialized_hypotheses.add(hypothesis.hypothesis_id)
                    self.deps.run_logger.log(tool="materialize_validated_cohort",query_id=materialized.query_id,
                        sql=materialized.executed_sql,parameters=materialized.parameters,result_size=materialized.row_count,
                        duration_ms=materialized.duration_ms,cache_status="miss")
            completed=datetime.now(timezone.utc);report=report.model_copy(update={"run_metadata":metadata.model_copy(
                update={"completion_time":completed,"status":RunStatus.COMPLETED})})
            usage=getattr(result,"usage",lambda:None)()
            usage_data=(asdict(usage) if usage and is_dataclass(usage) else
                        usage.model_dump(mode="json") if usage and hasattr(usage,"model_dump") else
                        str(usage) if usage else None)
            manager.record_run(run_id=self.deps.run_id,system_name="system_b",instance_id=request.instance_id,
                started_at=started,completed_at=completed,status="completed",validated=True,
                metadata={"llm_latency_ms":latency,"token_usage":usage_data,"tool_calls":self.deps.guardrail_service.total})
            return report
        except Exception as exc:
            if _caused_by_output_retry_exhaustion(exc):
                completed=datetime.now(timezone.utc)
                fallback=RCAReport(instance_id=request.instance_id,symptom=request.symptom,
                  hypotheses=[],unresolved_questions=[
                    "System B exhausted its structured-output repair attempts because the draft "
                    "claims could not be matched to exact stored aggregate evidence. Run a more "
                    "targeted analysis or obtain additional aggregate evidence."
                  ],run_metadata=metadata.model_copy(update={"completion_time":completed,"status":RunStatus.COMPLETED}))
                fallback=validate_system_b_output(fallback,request,self.deps,self.settings)
                manager.record_run(run_id=self.deps.run_id,system_name="system_b",instance_id=request.instance_id,
                  started_at=started,completed_at=completed,status="completed",validated=True,
                  metadata={"llm_latency_ms":(time.perf_counter()-before)*1000,
                    "output_repair_exhausted":True,"tool_calls":self.deps.guardrail_service.total})
                return fallback
            manager.record_run(run_id=self.deps.run_id,system_name="system_b",instance_id=request.instance_id,
                started_at=started,completed_at=datetime.now(timezone.utc),status="failed",metadata={"error":type(exc).__name__})
            raise


def _unresolved_report_events(report:RCAReport,deps:SystemBDependencies)->list[str]:
    """Return report events that lack a usable resolution in this run."""
    missing=set()
    for hypothesis in report.hypotheses:
        for event in hypothesis.resolved_events:
            resolution=deps.event_resolutions.get(event)
            if (not resolution or not resolution.resolved or not resolution.selected
                    or resolution.selected.confidence<.65):
                missing.add(event)
    return sorted(missing)


def _caused_by_output_retry_exhaustion(exc:Exception)->bool:
    """Identify Pydantic AI output-validator exhaustion without masking other failures."""
    current:BaseException|None=exc
    seen=set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__=="ToolRetryError":return True
        current=current.__cause__ or current.__context__
    return False


def build_dependencies(instance_id:str,settings:AppSettings,retriever,event_resolver,manager)->SystemBDependencies:
    analytics=DeterministicAnalytics(manager)
    return SystemBDependencies(analytics,retriever,event_resolver,analytics.materialize_cohort,manager,
        QueryCache(),SafeAuditLogger(),build_tool_guard(settings),f"run_{uuid.uuid4().hex}",instance_id)


def main():
    parser=argparse.ArgumentParser(prog="run-system-b");add_request_arguments(parser);args=parser.parse_args()
    assets=load_runtime_assets(args.instance_id,args.data_root,get_settings())
    deps=build_dependencies(args.instance_id,assets.settings,assets.retriever,assets.resolver,assets.manager)
    key=assets.settings.openai_api_key.get_secret_value() if assets.settings.openai_api_key else None
    report=SystemBAgent(deps=deps,runner=PydanticAIRunner(assets.settings.llm_model,key),settings=assets.settings).run(analysis_request_from_args(args))
    print(report.model_dump_json(indent=2))


if __name__=="__main__":main()
