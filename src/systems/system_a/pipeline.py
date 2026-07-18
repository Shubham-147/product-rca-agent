"""Non-agentic Vanilla RAG pipeline: fixed evidence, retrieval, one LLM call."""
from __future__ import annotations
import argparse,json,time,uuid
from datetime import datetime,timezone
from typing import Any,Protocol
from pydantic import ValidationError
from src.analytics import DeterministicAnalytics
from src.config import AppSettings,get_settings
from src.database import DuckDBManager,get_duckdb_manager
from src.guardrails import SafeAuditLogger,build_prompt_context,require_resolved_event
from src.observability import get_logger,log_retrieved_chunks,write_daily_openai_payload
from src.retrieval import CanonicalEventResolver,HybridRetriever
from src.schemas import AnalysisRequest,RCAReport,RunMetadata,RunStatus
from src.systems.bootstrap import load_runtime_assets
from src.systems.cli import add_request_arguments,analysis_request_from_args
from .evidence_pack import FUNNEL_STEPS,build_fixed_evidence_pack
from .output_validator import validate_system_a_output
from .prompts import build_prompt,build_schema_repair_prompt
from .retrieval_query import retrieve_context

class StructuredLLM(Protocol):
    def complete(self,prompt:str,output_type:type[RCAReport],*,temperature:float)->Any:...

class OpenAIStructuredLLM:
    def __init__(self,model:str,api_key:str|None=None):self.model=model;self.api_key=api_key;self._client=None;self._call_count=0
    def complete(self,prompt,output_type,*,temperature):
        if self._client is None:
            from openai import OpenAI
            self._client=OpenAI(api_key=self.api_key)
        self._call_count+=1
        request={"model":self.model,"temperature":temperature,"messages":[{"role":"user","content":prompt}],
          "response_format":{"type":"json_object"}}
        write_daily_openai_payload(system_name="system_a",stage=f"structured_call_{self._call_count}",
          model=self.model,payload=request)
        response=self._client.chat.completions.create(**request)
        return json.loads(response.choices[0].message.content)

class SystemAPipeline:
    def __init__(self,*,retriever:HybridRetriever,resolver:CanonicalEventResolver,llm:StructuredLLM,
                 settings:AppSettings|None=None,manager:DuckDBManager|None=None,analytics:DeterministicAnalytics|None=None):
        self.settings=settings or get_settings();self.manager=manager or get_duckdb_manager()
        self.analytics=analytics or DeterministicAnalytics(self.manager);self.retriever=retriever;self.resolver=resolver;self.llm=llm
        self.logger=get_logger(__name__)

    def run(self,request:AnalysisRequest)->RCAReport:
        run_id=f"run_{uuid.uuid4().hex}";started=datetime.now(timezone.utc)
        self.manager.record_run(run_id=run_id,system_name="system_a",instance_id=request.instance_id,
                                started_at=started,status="running")
        try:
            resolutions={}
            for concept in FUNNEL_STEPS:
                resolution=self.resolver.resolve(concept,raw_event_name=concept,funnel_name=request.funnel_name,top_k=5)
                require_resolved_event(resolution,concept);resolutions[concept]=resolution
            self.manager.set_alias_mappings(self.resolver.alias_mappings())
            raw_names=[]
            for concept in FUNNEL_STEPS:
                selected=resolutions[concept].selected
                raw_names.extend(selected.aliases if selected else [concept])
            pack=build_fixed_evidence_pack(self.analytics,request.instance_id,list(dict.fromkeys(raw_names)),self.settings.minimum_segment_size)
            chunks=retrieve_context(self.retriever,request,self.settings.max_prompt_chunks)
            context=build_prompt_context(chunks,pack.results,max_chunks=self.settings.max_prompt_chunks,
                                         max_chars=self.settings.max_chunk_characters)
            metadata=RunMetadata(run_id=run_id,system_name="system_a",instance_id=request.instance_id,start_time=started)
            prompt=build_prompt(request,pack,context,metadata)
            log_retrieved_chunks(SafeAuditLogger(self.logger),system_name="system_a",
              stage="analytical_call",chunks=chunks)
            llm_started=time.perf_counter()
            report=self._structured_call(prompt)
            llm_latency_ms=(time.perf_counter()-llm_started)*1000
            report=validate_system_a_output(report,request,query_ids=pack.query_ids,
                chunk_ids={c.chunk_id for c in chunks},resolutions=resolutions,
                max_hypotheses=self.settings.max_hypotheses,run_id=run_id)
            for hypothesis in report.hypotheses:
                self.analytics.materialize_cohort(run_id,"system_a",hypothesis.hypothesis_id,hypothesis.affected_cohort)
            completed=datetime.now(timezone.utc)
            final_metadata=metadata.model_copy(update={"completion_time":completed,"status":RunStatus.COMPLETED})
            report=report.model_copy(update={"run_metadata":final_metadata})
            self.manager.record_run(run_id=run_id,system_name="system_a",instance_id=request.instance_id,
                started_at=started,completed_at=completed,status="completed",validated=True,
                metadata={"hypotheses":len(report.hypotheses),"evidence_queries":len(pack.items),"retrieval_chunks":len(chunks),"llm_latency_ms":llm_latency_ms})
            return report
        except Exception as exc:
            self.manager.record_run(run_id=run_id,system_name="system_a",instance_id=request.instance_id,
                                    started_at=started,completed_at=datetime.now(timezone.utc),status="failed",
                                    metadata={"error":type(exc).__name__})
            raise

    def _structured_call(self,prompt:str)->RCAReport:
        raw=self.llm.complete(prompt,RCAReport,temperature=0.1)
        try:return raw if isinstance(raw,RCAReport) else RCAReport.model_validate(raw)
        except ValidationError as exc:
            repaired=self.llm.complete(build_schema_repair_prompt(prompt,str(exc)),RCAReport,temperature=0.0)
            return repaired if isinstance(repaired,RCAReport) else RCAReport.model_validate(repaired)

def main()->None:
    parser=argparse.ArgumentParser(prog="run-system-a")
    add_request_arguments(parser)
    args=parser.parse_args()
    assets=load_runtime_assets(args.instance_id,args.data_root,get_settings())
    pipeline=SystemAPipeline(retriever=assets.retriever,resolver=assets.resolver,
        llm=OpenAIStructuredLLM(assets.settings.llm_model,assets.settings.openai_api_key.get_secret_value() if assets.settings.openai_api_key else None),settings=assets.settings,manager=assets.manager)
    report=pipeline.run(analysis_request_from_args(args))
    print(report.model_dump_json(indent=2))

if __name__=="__main__":main()
