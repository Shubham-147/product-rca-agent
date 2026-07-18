from __future__ import annotations
import json
from src.config import AppSettings
from src.database import QueryResult
from src.retrieval.schemas import AliasMapping,CanonicalCandidate,Chunk,EventResolution,RetrievedChunk
from src.schemas import AnalysisRequest
from src.systems.system_a.evidence_pack import FUNNEL_STEPS,build_fixed_evidence_pack
from src.systems.system_a.pipeline import SystemAPipeline

class FakeManager:
    def __init__(self):self.runs=[];self.mappings=[]
    def record_run(self,**kwargs):self.runs.append(kwargs)
    def set_alias_mappings(self,mappings):self.mappings=mappings

class FakeAnalytics:
    def __init__(self):self.calls=[];self.materialized=[];self.n=0
    def _result(self,name,instance):
        self.calls.append((name,instance));self.n+=1
        return QueryResult(query_id=f"q{self.n}",executed_sql=f"SELECT aggregate FROM {name} WHERE instance_id = ?",
            parameters=[instance],duration_ms=1,row_count=1,result_summary=name,
            rows=[{"dimension_value":"android","exposed_users":100,"numerator_users":10,"metric_value":.1}])
    def get_instance_summary(self,i):return self._result("summary",i)
    def get_naive_funnel(self,i,s):return self._result("naive",i)
    def get_ordered_funnel(self,i,s,x):return self._result("ordered",i)
    def compare_metric_by_dimension(self,i,m,d,**kwargs):return self._result(f"{m}_{d}_{kwargs.get('screen','all')}",i)
    def materialize_cohort(self,run,system,hyp,cohort):self.materialized.append((run,system,hyp,cohort.instance_id));return self._result("materialize",cohort.instance_id)

class FakeResolver:
    def resolve(self,concept,**kwargs):
        c=CanonicalCandidate(canonical_event=concept,aliases=[concept,f"raw_{concept}"],confidence=.99,resolution_method="exact_alias")
        return EventResolution(concept=concept,candidates=[c],resolved=True,selected=c)
    def alias_mappings(self):return [AliasMapping(raw_event_name=f"raw_{x}",canonical_event=x,is_resolved=True,taxonomy_version="v1") for x in FUNNEL_STEPS]

class FakeRetriever:
    def __init__(self):
        self.chunk=Chunk(chunk_id="prd1",document_type="prd",document_id="prd",text="Checkout must be fast.",content_hash="h")
    def retrieve(self,query,mode,top_k=8):return [RetrievedChunk(chunk=self.chunk,fused_score=1)]

class FakeLLM:
    def __init__(self,invalid=False):self.calls=[];self.invalid=invalid
    def complete(self,prompt,output_type,*,temperature):
        self.calls.append({"prompt":prompt,"temperature":temperature,"tools":None})
        if self.invalid and len(self.calls)==1:return {"bad":"schema"}
        payload=json.loads(prompt.split("INPUT:\n",1)[1].split("\n\nSCHEMA REPAIR",1)[0])
        meta=payload["required_run_metadata"];query=payload["aggregate_evidence"][0]["query_id"]
        return {"instance_id":payload["request"]["instance_id"],"symptom":payload["request"]["symptom"],
          "hypotheses":[{"hypothesis_id":"h1","rank":1,"mechanism":"Checkout latency exceeds the documented SLO",
            "affected_cohort":{"instance_id":payload["request"]["instance_id"],"os":"android","required_events":[],"excluded_events":[],"description":"Android users"},
            "resolved_events":[],"evidence":[{"evidence_id":"e1","claim":"Observed aggregate differs","metric_name":"users","observed_value":100,"sample_size":100,"query_id":query,"source_chunk_ids":["prd1"]}],
            "confounders":[],"confidence":.7,"limitations":["No follow-up investigation loop"]}],
          "unresolved_questions":[],"run_metadata":meta}

def settings(tmp_path):return AppSettings(source_duckdb_path=tmp_path/"s",runtime_duckdb_path=tmp_path/"r",chroma_persist_path=tmp_path/"c",minimum_segment_size=1,max_prompt_chunks=3)

def test_system_a_one_call_no_tools_fixed_pack_and_materialization(tmp_path):
    manager=FakeManager();analytics=FakeAnalytics();llm=FakeLLM()
    pipeline=SystemAPipeline(retriever=FakeRetriever(),resolver=FakeResolver(),llm=llm,settings=settings(tmp_path),manager=manager,analytics=analytics)
    report=pipeline.run(AnalysisRequest(instance_id="inst_003",symptom="checkout conversion declined"))
    assert len(llm.calls)==1 and llm.calls[0]["tools"] is None and llm.calls[0]["temperature"]==.1
    assert len([call for call in analytics.calls if call[0]!="materialize"])==17
    assert all(instance=="inst_003" for _,instance in analytics.calls)
    assert analytics.materialized[0][3]=="inst_003"
    assert manager.runs[-1]["status"]=="completed" and manager.runs[-1]["validated"]
    prompt=llm.calls[0]["prompt"]
    assert "ground_truth" not in prompt and "user_id" not in prompt and "aggregate_evidence" in prompt
    assert report.run_metadata.status.value=="completed"

def test_schema_repair_only_retries_structured_output(tmp_path):
    llm=FakeLLM(invalid=True);analytics=FakeAnalytics()
    SystemAPipeline(retriever=FakeRetriever(),resolver=FakeResolver(),llm=llm,settings=settings(tmp_path),manager=FakeManager(),analytics=analytics).run(
        AnalysisRequest(instance_id="i",symptom="conversion declined"))
    assert len(llm.calls)==2 and llm.calls[1]["temperature"]==0
    assert len([call for call in analytics.calls if call[0]!="materialize"])==17

def test_fixed_evidence_pack_order_is_deterministic():
    first=build_fixed_evidence_pack(FakeAnalytics(),"i",FUNNEL_STEPS,1)
    second=build_fixed_evidence_pack(FakeAnalytics(),"i",FUNNEL_STEPS,1)
    assert [x.name for x in first.items]==[x.name for x in second.items]
