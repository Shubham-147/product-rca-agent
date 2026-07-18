from __future__ import annotations
from datetime import datetime,timezone
import pytest
from pydantic import BaseModel
from src.database import QueryResult
from src.guardrails import *
from src.observability import retrieval_chunk_descriptors,write_daily_openai_payload
from src.retrieval.schemas import CanonicalCandidate,Chunk,EventResolution
from src.schemas import AnalysisRequest,CohortDefinition,Evidence,RCAReport,RootCauseHypothesis,RunMetadata

@pytest.mark.parametrize("sql",[
 "SELECT * FROM v_events WHERE instance_id=?; DELETE FROM users",
 "SELECT * FROM v_events WHERE instance_id=? -- DELETE FROM users LIMIT 10",
 "SELECT * FROM manifest WHERE instance_id=? LIMIT 10",
 "SELECT * FROM ground_truth_labels WHERE instance_id=? LIMIT 10",
 "UPDATE users SET os='x'",
 "ATTACH 'x' AS hidden",
 "COPY events TO 'x'",
 "CREATE TABLE x(a int)",
])
def test_sql_injection_mutations_and_blocked_tables(sql):
    with pytest.raises(GuardrailError):validate_fallback_query(sql,"inst_1",100)

def test_fallback_requires_instance_and_bounded_limit():
    with pytest.raises(GuardrailError):validate_fallback_query("SELECT * FROM v_events LIMIT 10","inst_1",100)
    with pytest.raises(GuardrailError):validate_fallback_query("SELECT * FROM v_events WHERE instance_id=?","inst_1",100)
    with pytest.raises(GuardrailError):validate_fallback_query("SELECT * FROM v_events WHERE instance_id=? LIMIT 101","inst_1",100)
    validate_fallback_query("SELECT event_name FROM v_events WHERE instance_id=? LIMIT 10","inst_1",100)

def test_identifier_allowlists_and_typed_query():
    with pytest.raises(GuardrailError):validate_dimension("os;drop table users")
    with pytest.raises(GuardrailError):validate_metric("revenue")
    with pytest.raises(GuardrailError):sanitize_cohort_table_name("cohort_x;drop")
    sql,params=SafeSelectQuery(instance_id="i",relation="v_events",columns=["event_name"],limit=5).compile(10)
    assert "instance_id = ?" in sql and params==["i"]

def _resolution(confidence,resolved=True):
    candidate=CanonicalCandidate(canonical_event="checkout_start",aliases=["checkout_start"],confidence=confidence,
        resolution_method="hybrid",evidence_chunk_ids=["tax_1"])
    return EventResolution(concept="checkout",candidates=[candidate],resolved=resolved,selected=candidate if resolved else None)

def test_event_resolution_guardrail():
    with pytest.raises(GuardrailError):require_resolved_event(_resolution(.5,False),"raw")
    medium=require_resolved_event(_resolution(.7),"raw_checkout")
    assert medium.warning and medium.raw_event_name=="raw_checkout"
    assert require_resolved_event(_resolution(.9)).warning is None

class Args(BaseModel): value:int

def test_tool_budgets_duplicates_and_limits():
    guard=SystemBToolGuard(total=2,retrieval=1,analytical=1,timeout_seconds=1)
    assert guard.execute("retrieve","retrieval",Args(value=1),lambda:"x")== ("x",False)
    assert guard.execute("retrieve","retrieval",Args(value=1),lambda:"y")== ("x",True)
    guard.execute("analyse","analytical",Args(value=2),lambda:"z")
    with pytest.raises(GuardrailError):guard.execute("analyse2","analytical",Args(value=3),lambda:"z")

def test_graph_cycle_and_identical_revision_limits():
    graph=SystemCGraphGuard(max_revisions=2,max_node_executions=1,timeout_seconds=1)
    graph.register_revision({"mechanism":"a"})
    with pytest.raises(GuardrailError):graph.register_revision({"mechanism":"a"})
    graph.register_revision({"mechanism":"b"})
    with pytest.raises(GuardrailError):graph.register_revision({"mechanism":"c"})
    graph.execute_node("n",Args(value=1),lambda:1)
    with pytest.raises(GuardrailError):graph.execute_node("m",Args(value=2),lambda:2)

def test_prompt_size_raw_rows_and_deduplication():
    chunk=Chunk(chunk_id="c",document_type="prd",document_id="d",text="rule",content_hash="h")
    result=QueryResult(query_id="q",executed_sql="select",duration_ms=1,row_count=1,result_summary="aggregate",rows=[{"users":3}])
    context=build_prompt_context([chunk,chunk],[result,result],max_chunks=1,max_chars=10)
    assert len(context.chunks)==1 and len(context.aggregate_results)==1
    with pytest.raises(GuardrailError):build_prompt_context([chunk,Chunk(chunk_id="d",document_type="prd",document_id="d",text="x",content_hash="x")],[],max_chunks=1,max_chars=10)
    raw=result.model_copy(update={"rows":[{"user_id":"u","session_id":"s","event_ts":"t"}]})
    with pytest.raises(GuardrailError):build_prompt_context([], [raw],max_chunks=1,max_chars=10)

def _report(query_id="q1",mechanism="Checkout latency exceeds the product SLO"):
    cohort=CohortDefinition(instance_id="i",description="all")
    evidence=Evidence(evidence_id="e",claim="p95 is high",metric_name="latency_p95",observed_value=4,
        sample_size=40,query_id=query_id,source_chunk_ids=["prd1"])
    hyp=RootCauseHypothesis(hypothesis_id="h",rank=1,mechanism=mechanism,affected_cohort=cohort,
        resolved_events=[],evidence=[evidence],confidence=.8,limitations=["short window"])
    return RCAReport(instance_id="i",symptom="checkout conversion declined",hypotheses=[hyp],
        run_metadata=RunMetadata(run_id="r",system_name="system_a",instance_id="i",start_time=datetime.now(timezone.utc)))

def test_evidence_traceability_and_symptom_only_rejection():
    validate_report(_report(),query_ids={"q1"},source_chunk_ids={"prd1"})
    with pytest.raises(GuardrailError):validate_report(_report("missing"),query_ids={"q1"},source_chunk_ids={"prd1"})
    with pytest.raises(GuardrailError):validate_report(_report(mechanism="checkout conversion declined"),query_ids={"q1"},source_chunk_ids={"prd1"})

def test_safe_logging_redacts_secrets_and_large_sets():
    record=SafeAuditLogger().log(tool="sql",parameters={"api_key":"secret","users":list(range(30))},query_id="q")
    assert record["parameters"]["api_key"]=="[REDACTED]"
    assert "REDACTED COLLECTION" in record["parameters"]["users"]

def test_retrieval_chunk_logging_is_bounded_and_redacted():
    chunks=[Chunk(chunk_id="prd1",document_type="prd",document_id="d",text="A "*400,content_hash="h"),
      {"chunk_id":"ticket1","document_type":"ticket","text":"authorization token must stay secret"}]
    records=retrieval_chunk_descriptors(chunks)
    assert records[0]["chunk_id"]=="prd1" and len(records[0]["preview"])==300
    assert records[0]["character_count"]==800
    assert records[1]["preview"]=="[REDACTED]"

def test_daily_openai_payload_log_excludes_credentials(tmp_path):
    target=write_daily_openai_payload(system_name="system_a",stage="test",model="test",
      payload={"messages":[{"content":"checkout context"}],"api_key":"must-not-appear"},log_root=tmp_path/"log")
    record=target.read_text()
    assert target.parent.name=="log" and target.suffix==".txt"
    assert "checkout context" in record and "must-not-appear" not in record and "[REDACTED]" in record
