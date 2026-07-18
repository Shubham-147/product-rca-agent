from __future__ import annotations
from datetime import datetime,timezone
import pytest
from src.config import AppSettings
from src.database import QueryResult
from src.guardrails import GuardrailError,SafeAuditLogger,SystemCGraphGuard
from src.retrieval.schemas import AliasMapping,CanonicalCandidate,Chunk,EventResolution,RetrievedChunk
from src.schemas import AnalysisRequest,CohortDefinition
from src.systems.system_c.graph import SystemCWorkflow,build_dependencies,build_graph
from src.systems.system_c.models import *
from src.systems.system_c.nodes.event_resolver import EventResolverNode
from src.systems.system_c.nodes.falsifier import FalsifierNode
from src.systems.system_c.nodes.intake import IntakeNode
from src.systems.system_c.nodes.common import SystemCDependencies
from src.systems.system_c.nodes.reviser import ReviserNode
from src.systems.system_c.nodes.validator import ValidatorNode
from src.systems.system_c.routing import after_falsifier,after_resolution

class Manager:
    def __init__(self):self.runs=[];self.mappings=[]
    def record_run(self,**kwargs):self.runs.append(kwargs)
    def set_alias_mappings(self,m):self.mappings=m
class Analytics:
    def __init__(self,spread=.05):self.n=0;self.materialized=[];self.spread=spread
    def result(self,name,rows=None):
        self.n+=1;return QueryResult(query_id=f"q{self.n}",executed_sql=f"SELECT aggregate FROM {name} WHERE instance_id=?",parameters=["inst_003"],duration_ms=1,row_count=len(rows or [{}]),result_summary=name,rows=rows or [{"users":100}])
    def get_instance_summary(self,i):return self.result("summary",[{"users":100,"events":500,"sessions":150}])
    def analyse_event_sequence(self,*args):return self.result("ordered sequence",[{"step_order":0,"users":100},{"step_order":1,"users":60}])
    def get_ordered_funnel(self,*args):return self.analyse_event_sequence()
    def compare_metric_by_dimension(self,*args):return self.result("metric",[{"dimension_value":"a","exposed_users":100,"numerator_users":20,"metric_value":.2},{"dimension_value":"b","exposed_users":100,"numerator_users":int((.2+self.spread)*100),"metric_value":.2+self.spread}])
    def compare_exposed_unexposed(self,*args):return self.result("control",[{"group_name":"control","users":100,"outcome_users":50,"outcome_rate":.5}])
    def materialize_cohort(self,run,system,hyp,cohort):self.materialized.append(hyp);return self.result("materialized",[{"users":100}])
class Retriever:
    chunk=Chunk(chunk_id="prd1",document_type="prd",document_id="p",text="Checkout must complete; this is not an optional expected drop-off.",content_hash="h")
    def retrieve(self,*args,**kwargs):return [RetrievedChunk(chunk=self.chunk,fused_score=1)]
class Resolver:
    unresolved=False
    def resolve(self,concept,**kwargs):
        c=CanonicalCandidate(canonical_event=concept,aliases=[concept],confidence=.4 if self.unresolved else .99,resolution_method="exact_alias",evidence_chunk_ids=["prd1"])
        return EventResolution(concept=concept,candidates=[c],resolved=not self.unresolved,selected=c if not self.unresolved else None)
    def alias_mappings(self):return [AliasMapping(raw_event_name="checkout_start",canonical_event="checkout_start",is_resolved=True,taxonomy_version="v1")]
class Model:
    def complete(self,task,payload,output_type):
        if task=="hypothesis_generator":
            return HypothesisBatch(hypotheses=[candidate(f"h{i}") for i in range(3)])
        h=CandidateHypothesis.model_validate(payload["hypothesis"])
        return RevisionOutput(hypothesis=h.model_copy(update={"proposed_mechanism":h.proposed_mechanism+" for older devices","expected_cohort":h.expected_cohort.model_copy(update={"device_age_min":24})}))
def candidate(hid="h1",benign=False):return CandidateHypothesis(hypothesis_id=hid,proposed_mechanism="Checkout crashes before order confirmation",expected_cohort=CohortDefinition(instance_id="inst_003",os="android",description="Android users"),required_events=["checkout_start","order_confirmed"],expected_observations=["lower completion"],alternative_explanations=["traffic mix"],possible_confounders=["device age"],benign_explanation=benign,context_chunk_ids=["prd1"])
def settings(tmp_path,nodes=30):return AppSettings(source_duckdb_path=tmp_path/"s",runtime_duckdb_path=tmp_path/"r",chroma_persist_path=tmp_path/"c",minimum_segment_size=30,system_c_max_node_executions=nodes)
def deps(tmp_path,analytics=None,resolver=None,nodes=30):
    cfg=settings(tmp_path,nodes);a=analytics or Analytics();m=Manager()
    return SystemCDependencies(a,Retriever(),resolver or Resolver(),m,Model(),SystemCGraphGuard(2,nodes,1),SafeAuditLogger(),cfg,"inst_003","run1")
def base_state(h=None):
    h=h or candidate()
    return {"request":AnalysisRequest(instance_id="inst_003",symptom="conversion declined"),"current_hypothesis":h,"current_hypothesis_index":0,"candidate_hypotheses":[h],"resolved_events":{},"query_results":[],"accepted_hypotheses":[],"rejected_hypotheses":[],"revision_count":0,"revisions_by_hypothesis":{},"maximum_revisions":2,"trace":[],"errors":[],"warnings":[],"retrieved_context":[]}

def test_state_initialization_and_node_contracts(tmp_path):
    d=deps(tmp_path);state=IntakeNode(d)({"request":AnalysisRequest(instance_id="inst_003",symptom="decline")})
    assert state["instance_summary"].query_id and state["maximum_revisions"]==2 and state["node_execution_count"]==1
    assert build_graph(d) is not None

def test_event_resolution_and_routes(tmp_path):
    resolver=Resolver();resolver.unresolved=True;state=EventResolverNode(deps(tmp_path,resolver=resolver))(base_state())
    assert after_resolution(state)=="context_retriever"
    state["context_retry_used"]=True;assert after_resolution(state)=="reject"
    for verdict,route in [("pass","accept"),("revise","reviser"),("reject","reject")]:
        state["falsification_result"]=FalsificationResult(verdict=verdict,falsification_summary="x",falsification_score=.5)
        assert after_falsifier(state)==route

def test_revision_limits_and_identical_revision(tmp_path):
    d=deps(tmp_path);state=base_state();state["falsification_result"]=FalsificationResult(verdict="revise",revision_instruction="narrow",falsification_summary="confounded",falsification_score=.4)
    revised=ReviserNode(d)(state);assert revised["revision_count"]==1
    guard=SystemCGraphGuard(max_revisions=2);guard.register_revision(candidate(),"h1")
    with pytest.raises(GuardrailError):guard.register_revision(candidate(),"h1")
    guard.register_revision(candidate("h2"),"h2")

def test_temporal_order_and_device_age_falsification(tmp_path):
    d=deps(tmp_path,analytics=Analytics(spread=.5));state=base_state();state["resolved_events"]={x:Resolver().resolve(x) for x in ["checkout_start","order_confirmed"]}
    state["query_plan"]=TypedQueryPlan(items=[QueryPlanItem(query_key="t",question="ordered?",operation="event_sequence",cohort=candidate().expected_cohort,expected_observation_if_true="drop",required_canonical_events=["checkout_start","order_confirmed"])])
    state["query_results"]=[d.analytics.result("bad sequence",[{"step_order":0,"users":50},{"step_order":1,"users":70}])]
    validated=ValidatorNode(d)(state);assert not validated["validation_result"].temporal_order_valid
    state["validation_result"]=validated["validation_result"].model_copy(update={"supported":True,"temporal_order_valid":True})
    falsified=FalsifierNode(d)(state);assert falsified["falsification_result"].verdict=="revise" and falsified["falsification_result"].confounders_found[0].confounder=="device_age_bucket"

def test_expected_dropoff_rejection_and_manifest_protection(tmp_path):
    d=deps(tmp_path);state=base_state(candidate(benign=True));state["retrieved_context"]=[{"chunk_id":"prd1","text":"checkout_start is an optional expected drop-off","document_type":"prd","metadata":{}}]
    state["validation_result"]=ValidationResult(supported=True,sufficient_sample=True,denominator_valid=True,event_resolution_valid=True,temporal_order_valid=True,cohort_valid=True,evidence_consistent=True)
    assert FalsifierNode(d)(state)["falsification_result"].verdict=="reject"
    with pytest.raises(Exception):SystemCWorkflow(d).run(AnalysisRequest(instance_id="inst_003",symptom="inspect ground_truth manifest"))

def test_falsifier_rejects_unsupported_validation_without_revision_error(tmp_path):
    d=deps(tmp_path);state=base_state()
    state["validation_result"]=ValidationResult(supported=False,sufficient_sample=False,
      denominator_valid=True,event_resolution_valid=True,temporal_order_valid=True,
      cohort_valid=True,evidence_consistent=False,reasons=["insufficient supporting evidence"])
    result=FalsifierNode(d)(state)["falsification_result"]
    assert result.verdict=="reject"
    assert result.revision_instruction is None

def test_mocked_complete_graph_terminates_and_materializes(tmp_path):
    d=deps(tmp_path);report=SystemCWorkflow(d).run(AnalysisRequest(instance_id="inst_003",symptom="checkout conversion declined",funnel_name="shopfunnel"))
    assert len(report.hypotheses)==3 and d.analytics.materialized==["h0","h1","h2"]
    assert d.guard.nodes<=d.settings.system_c_max_node_executions and d.manager.runs[-1]["validated"]
