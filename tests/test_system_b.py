from __future__ import annotations
import time
from datetime import datetime,timezone
import pytest
from src.config import AppSettings
from src.database import QueryResult
from src.guardrails import GuardrailError,SafeAuditLogger,SystemBToolGuard
from src.retrieval.schemas import AliasMapping,CanonicalCandidate,Chunk,EventResolution,RetrievedChunk,RetrievalMode
from src.schemas import AnalysisRequest,CohortDefinition,RCAReport
from src.systems.system_b.agent import PydanticAIRunner,SystemBAgent,_unresolved_report_events
from src.systems.system_b.dependencies import QueryCache,SystemBDependencies
from src.systems.system_b.output_validator import draft_evidence_errors
from src.systems.system_b.tools import *

class Manager:
    def __init__(self):self.runs=[];self.mappings=[]
    def record_run(self,**kwargs):self.runs.append(kwargs)
    def set_alias_mappings(self,m):self.mappings=m
class Analytics:
    def __init__(self):self.n=0;self.materialized=[]
    def result(self,name,instance):
        self.n+=1;return QueryResult(query_id=f"q{self.n}",executed_sql=f"SELECT aggregate FROM {name} WHERE instance_id=?",
          parameters=[instance],duration_ms=1,row_count=1,result_summary=name,
          rows=[{"dimension_value":"android","exposed_users":100,"numerator_users":20,"metric_value":.2}])
    def get_instance_summary(self,i):return self.result("summary",i)
    def get_ordered_funnel(self,i,s,x):return self.result("funnel",i)
    def compare_metric_by_dimension(self,i,m,d,c=None,minimum_users=30):return self.result(m,i)
    def analyse_event_sequence(self,i,s,m,o,c=None):return self.result("sequence",i)
    def compare_exposed_unexposed(self,i,e,c,o):return self.result("control",i)
    def materialize_cohort(self,run,system,hyp,cohort):self.materialized.append(hyp);return self.result("materialize",cohort.instance_id)
class Retriever:
    chunk=Chunk(chunk_id="prd1",document_type="prd",document_id="prd",text="Checkout should complete.",content_hash="h")
    def retrieve(self,*args,**kwargs):return [RetrievedChunk(chunk=self.chunk,fused_score=1)]
class Resolver:
    def resolve(self,concept,**kwargs):
        c=CanonicalCandidate(canonical_event=concept,aliases=[concept],confidence=.99,resolution_method="exact_alias",evidence_chunk_ids=["tax1"])
        return EventResolution(concept=concept,candidates=[c],resolved=True,selected=c)
    def alias_mappings(self):return [AliasMapping(raw_event_name="checkout_start",canonical_event="checkout_start",is_resolved=True,taxonomy_version="v1")]

def make_deps(tmp_path,total=15,retrieval=4,analytical=10,timeout=1):
    a=Analytics();m=Manager();guard=SystemBToolGuard(total,retrieval,analytical,timeout)
    return SystemBDependencies(a,Retriever(),Resolver(),a.materialize_cohort,m,QueryCache(),SafeAuditLogger(),guard,"run1","inst_003")
def cohort():return CohortDefinition(instance_id="inst_003",os="android",description="Android users")

def test_dependency_injection_and_tool_schemas(tmp_path):
    deps=make_deps(tmp_path);tools=SystemBTools(deps)
    assert tools.deps is deps and SearchKnowledgeInput.model_json_schema()["properties"]["top_k"]["maximum"]==8
    assert set(PydanticAIRunner("test")._build()._function_toolset.tools)=={
      "search_knowledge","resolve_events","get_instance_summary","build_funnel",
      "compare_metric_by_dimension","analyse_event_sequence","compare_exposed_unexposed",
      "test_confounder","materialize_cohort"}

def test_resolution_required_before_event_analytics(tmp_path):
    tools=SystemBTools(make_deps(tmp_path))
    with pytest.raises(GuardrailError):tools.build_funnel(BuildFunnelInput(instance_id="inst_003",canonical_steps=["checkout_start","order_confirmed"]))
    tools.resolve_events(ResolveEventsInput(instance_id="inst_003",concept="checkout_start"));tools.resolve_events(ResolveEventsInput(instance_id="inst_003",concept="order_confirmed"))
    assert tools.build_funnel(BuildFunnelInput(instance_id="inst_003",canonical_steps=["checkout_start","order_confirmed"]))["query_id"]

def test_budgets_duplicate_cache_timeout_and_manifest(tmp_path):
    deps=make_deps(tmp_path,total=2,retrieval=1,analytical=1);tools=SystemBTools(deps);args=InstanceSummaryInput(instance_id="inst_003")
    assert tools.get_instance_summary(args)==tools.get_instance_summary(args) and deps.guardrail_service.total==1
    with pytest.raises(GuardrailError):tools.compare_metric_by_dimension(CompareMetricInput(instance_id="inst_003",metric="crash_rate",dimension="os"))
    with pytest.raises(GuardrailError):tools.search_knowledge(SearchKnowledgeInput(instance_id="inst_003",query="ground_truth manifest",document_types=["prd"],retrieval_mode=RetrievalMode.PRODUCT_INTENT))
    timed=SystemBToolGuard(timeout_seconds=.01)
    with pytest.raises(GuardrailError):timed.execute("slow","analytical",args,lambda:time.sleep(.1))

class CompleteRunner:
    def run_sync(self,prompt,*,deps):
        t=SystemBTools(deps);t.get_instance_summary(InstanceSummaryInput(instance_id=deps.instance_id))
        t.search_knowledge(SearchKnowledgeInput(instance_id=deps.instance_id,query="checkout intent",document_types=["prd"],retrieval_mode=RetrievalMode.PRODUCT_INTENT))
        t.resolve_events(ResolveEventsInput(instance_id=deps.instance_id,concept="order_confirmed"))
        q1=t.compare_metric_by_dimension(CompareMetricInput(instance_id=deps.instance_id,metric="checkout_completion_rate",dimension="os",minimum_users=1))
        q2=t.test_confounder(ConfounderTestInput(instance_id=deps.instance_id,confounder="device mix",metric="checkout_completion_rate",dimension="device_type",minimum_users=1))
        return {"instance_id":deps.instance_id,"symptom":"checkout declined","hypotheses":[{"hypothesis_id":"h1","rank":1,
          "mechanism":"Android checkout completion fails after payment submission","affected_cohort":cohort().model_dump(),"resolved_events":["order_confirmed"],
          "evidence":[{"evidence_id":"e1","claim":"low completion","metric_name":"checkout_completion_rate","observed_value":.2,"sample_size":100,"query_id":q1["query_id"],"source_chunk_ids":["prd1"]},
                      {"evidence_id":"e2","claim":"device mix checked","metric_name":"checkout_completion_rate","observed_value":.2,"sample_size":100,"query_id":q2["query_id"],"source_chunk_ids":["prd1"]}],
          "confounders":[{"confounder":"device mix","method":"segmentation","result":"persists","status":"ruled_out"}],"confidence":.7,"limitations":["Observational evidence"]}],
          "unresolved_questions":[],"run_metadata":{"run_id":deps.run_id,"system_name":"system_b","instance_id":deps.instance_id,"start_time":datetime.now(timezone.utc).isoformat(),"status":"running"}}

class ParaphrasedEnvelopeRunner(CompleteRunner):
    def run_sync(self,prompt,*,deps):
        result=super().run_sync(prompt,deps=deps)
        result["instance_id"]="wrong_instance"
        result["symptom"]="A model-generated paraphrase"
        return result

class ExhaustedOutputRepairRunner:
    def run_sync(self,prompt,*,deps):
        cause=type("ToolRetryError",(Exception,),{})("repair exhausted")
        raise RuntimeError("model output retries exceeded") from cause

def test_mocked_complete_agent_run_validates_and_materializes(tmp_path):
    deps=make_deps(tmp_path);settings=AppSettings(source_duckdb_path=tmp_path/"s",runtime_duckdb_path=tmp_path/"r",chroma_persist_path=tmp_path/"c",minimum_segment_size=50)
    report=SystemBAgent(deps=deps,runner=CompleteRunner(),settings=settings).run(AnalysisRequest(instance_id="inst_003",symptom="checkout declined"))
    assert report.run_metadata.status.value=="completed" and deps.analytics.materialized==["h1"]
    assert deps.safe_query_executor.runs[-1]["validated"] and all(event["arguments"]["instance_id"]=="inst_003" for event in deps.tool_events)

def test_request_envelope_is_canonicalized_before_validation(tmp_path):
    deps=make_deps(tmp_path);settings=AppSettings(source_duckdb_path=tmp_path/"s",runtime_duckdb_path=tmp_path/"r",chroma_persist_path=tmp_path/"c",minimum_segment_size=50)
    request=AnalysisRequest(instance_id="inst_003",symptom="checkout declined")
    report=SystemBAgent(deps=deps,runner=ParaphrasedEnvelopeRunner(),settings=settings).run(request)
    assert report.instance_id==request.instance_id
    assert report.symptom==request.symptom

def test_draft_report_identifies_events_not_resolved_in_this_run(tmp_path):
    deps=make_deps(tmp_path)
    report=RCAReport.model_validate(CompleteRunner().run_sync("",deps=deps))
    assert _unresolved_report_events(report,deps)==[]
    report.hypotheses[0].resolved_events.append("payment_submit")
    assert _unresolved_report_events(report,deps)==["payment_submit"]

def test_draft_report_identifies_values_not_present_in_stored_query(tmp_path):
    deps=make_deps(tmp_path)
    report=RCAReport.model_validate(CompleteRunner().run_sync("",deps=deps))
    assert draft_evidence_errors(report,deps)==[]
    report.hypotheses[0].evidence[0].observed_value=.99
    errors=draft_evidence_errors(report,deps)
    assert errors==["evidence e1 observed_value does not match its stored query result"]

def test_output_repair_exhaustion_returns_truthful_unresolved_report(tmp_path):
    deps=make_deps(tmp_path);settings=AppSettings(source_duckdb_path=tmp_path/"s",runtime_duckdb_path=tmp_path/"r",chroma_persist_path=tmp_path/"c")
    request=AnalysisRequest(instance_id="inst_003",symptom="checkout declined")
    report=SystemBAgent(deps=deps,runner=ExhaustedOutputRepairRunner(),settings=settings).run(request)
    assert report.hypotheses==[]
    assert report.unresolved_questions
    assert report.run_metadata.status.value=="completed"
    assert deps.safe_query_executor.runs[-1]["metadata"]["output_repair_exhausted"] is True
