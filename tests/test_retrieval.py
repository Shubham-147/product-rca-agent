from __future__ import annotations
import duckdb
from src.database.views import create_normalized_views,create_resolved_events_view
from src.retrieval import *
from src.retrieval.reranker import LexicalFallbackReranker

class FakeDense:
    def __init__(self,mapping=None):self.mapping=mapping or {}
    def index(self,chunks,batch_size=64):self.chunks=chunks
    def search(self,query,k=20,allowed_types=None):
        return [(cid,score) for cid,score in self.mapping.get(query,[])][:k]

class ConstantReranker:
    def score(self,query,texts): return [1.0 for _ in texts]

def records():
    return [TaxonomyRecord(canonical_event="checkout_start",aliases=["evt_chkout_init","ChkoutInit"],
        description="User begins checkout",screen="checkout",funnel_step="checkout_start",
        event_category="funnel",valid_predecessors=["cart_view"],valid_successors=["payment_submit"]),
        TaxonomyRecord(canonical_event="screen_load",aliases=["page_render"],description="A screen finished rendering",
        screen="generic",event_category="performance")]

def test_taxonomy_aliases_stay_together_and_ids_stable():
    first=chunk_taxonomy(records(),"v1");second=chunk_taxonomy(records(),"v1")
    assert first[0].chunk_id==second[0].chunk_id
    assert "evt_chkout_init" in first[0].text and "ChkoutInit" in first[0].text
    assert first[0].text.count("canonical_event:")==1

def test_prd_parent_child_structure():
    content=" ".join(f"rule_{i} applies except exception_{i}." for i in range(700))
    chunks=chunk_prd(PRDDocument(document_id="prd",title="Shop",version="1",sections=[PRDSection(heading="Checkout rules",content=content)]))
    parents=[c for c in chunks if c.metadata["level"]=="parent"]
    children=[c for c in chunks if c.metadata["level"]=="child"]
    assert parents and children
    assert all(c.parent_chunk_id in {p.chunk_id for p in parents} for c in children)

def test_ticket_identity_and_metric_atomicity():
    ticket=TicketDocument(ticket_id="T-1",title="Slow",description="Checkout is slow",status="open")
    assert all(c.metadata["ticket_id"]=="T-1" for c in chunk_tickets([ticket]))
    metric=MetricDefinition(metric_name="crash_rate",numerator="crashed users",denominator="exposed users",grain="user",minimum_sample_size=30,limitations=["rare events"])
    chunks=chunk_metrics([metric]);assert len(chunks)==1 and "denominator: exposed users" in chunks[0].text

def test_semantic_retrieval_metadata_filter_and_parent_diversity():
    chunks=chunk_taxonomy(records(),"v1")
    dense=FakeDense({"performance problem":[(chunks[1].chunk_id,.9)]})
    retriever=HybridRetriever(chunks,dense,ConstantReranker(),max_per_parent=2)
    hit=retriever.retrieve("performance problem",RetrievalMode.EVENT_RESOLUTION,top_k=2)
    assert hit[0].chunk.metadata["canonical_event"]=="screen_load"
    assert retriever.retrieve("performance problem",RetrievalMode.EVENT_RESOLUTION,metadata_filters={"screen":"checkout"})==[]

    parent="p"; children=[Chunk(chunk_id=f"c{i}",document_type="prd",document_id="d",text=f"checkout rule {i}",content_hash=str(i),parent_chunk_id=parent) for i in range(4)]
    r=HybridRetriever(children,FakeDense({"checkout":[(c.chunk_id,1) for c in children]}),ConstantReranker(),max_per_parent=2)
    assert len(r.retrieve("checkout",RetrievalMode.PRODUCT_INTENT,top_k=4))==2

def test_rrf_is_deterministic():
    a=reciprocal_rank_fusion(["a","b"],["b","c"],60)
    assert a==reciprocal_rank_fusion(["a","b"],["b","c"],60)
    assert a[0][0]=="b"

def test_exact_alias_and_low_confidence_unresolved():
    chunks=chunk_taxonomy(records(),"v1")
    retriever=HybridRetriever(chunks,FakeDense(),LexicalFallbackReranker())
    resolver=CanonicalEventResolver(records(),retriever,"v1")
    exact=resolver.resolve("checkout",raw_event_name="ChkoutInit")
    assert exact.resolved and exact.selected.canonical_event=="checkout_start" and exact.selected.confidence>=.85
    low=resolver.resolve("completely unrelated concept")
    assert not low.resolved and low.selected is None

def test_resolved_duckdb_view():
    con=duckdb.connect(":memory:")
    con.execute("""create table events(user_id varchar,session_id varchar,event_ts timestamp,event_name varchar,screen varchar,os varchar,device_type varchar,device_age_months int,geo varchar,channel varchar,is_returning boolean,latency_ms double,is_crash boolean,payment_method varchar,instance_id varchar)""")
    con.execute("""create table users(user_id varchar,os varchar,device_type varchar,device_age_months int,geo varchar,channel varchar,is_returning boolean,acquired_ts timestamp,instance_id varchar)""")
    con.execute("insert into events values ('u','s',now(),'ChkoutInit','checkout','ios','phone',10,'us','organic',true,10,false,null,'i')")
    create_normalized_views(con)
    resolver=CanonicalEventResolver(records(),HybridRetriever(chunk_taxonomy(records()),FakeDense()),"v1")
    create_resolved_events_view(con,resolver.alias_mappings())
    row=con.execute("select canonical_event,is_resolved,taxonomy_version from v_events_resolved").fetchone()
    assert row==("checkout_start",True,"v1")
