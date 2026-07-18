"""Shared agent-visible corpus, retriever, resolver, and database bootstrap."""
from __future__ import annotations
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from src.config import AppSettings
from src.database import DuckDBManager
from src.retrieval import (CanonicalEventResolver,FunnelDefinition,MetricDefinition,TaxonomyRecord,
 build_hybrid_retriever,chunk_funnels,chunk_metrics,chunk_prd,chunk_taxonomy,chunk_tickets,
 load_prd_markdown,load_ticket_markdown)

FUNNEL_STEPS=["app_open","home_view","product_browse","product_detail_view","add_to_cart","cart_view","checkout_start","payment_submit","order_confirmed"]

@dataclass
class RuntimeAssets:
    settings:AppSettings;task:dict;retriever:object;resolver:CanonicalEventResolver;manager:DuckDBManager

def load_runtime_assets(instance_id:str,data_root:Path,settings:AppSettings,*,index_dense=True)->RuntimeAssets:
    task_path=data_root/"tasks"/f"task_{instance_id}.json"
    if not task_path.is_file():raise FileNotFoundError(f"task not found: {task_path}")
    task=json.loads(task_path.read_text());
    if task.get("instance_id")!=instance_id:raise ValueError("task instance_id mismatch")
    corpus=task["corpus"];cfg=settings.model_copy(update={"source_duckdb_path":data_root/task["warehouse"]})
    taxonomy=load_visible_taxonomy(data_root/corpus["taxonomy"])
    prd=load_prd_markdown(data_root/corpus["prd"],document_id="shopfunnel_prd",version="visible")
    tickets=[load_ticket_markdown(path) for path in sorted((data_root/corpus["tickets"]).glob("*.md"))]
    funnel=FunnelDefinition(funnel_name="shopfunnel",canonical_steps=FUNNEL_STEPS)
    chunks=[*chunk_taxonomy(taxonomy,version="visible"),*chunk_prd(prd),*chunk_tickets(tickets),
      *chunk_funnels([funnel]),*chunk_metrics(metric_definitions(cfg.minimum_segment_size))]
    retriever=build_hybrid_retriever(chunks,cfg,index_dense=index_dense)
    resolver=CanonicalEventResolver(taxonomy,retriever,taxonomy_version="visible")
    return RuntimeAssets(cfg,task,retriever,resolver,DuckDBManager(cfg))

def load_visible_taxonomy(path:Path)->list[TaxonomyRecord]:
    meanings={"fired when the app is brought to the foreground / a session begins.":"app_open","user views the home screen.":"home_view",
      "user views a product listing / browse screen.":"product_browse","user opens a product detail page.":"product_detail_view",
      "user adds an item to the cart.":"add_to_cart","user opens the cart.":"cart_view","user begins the checkout flow.":"checkout_start",
      "user submits a payment.":"payment_submit","order successfully placed.":"order_confirmed"}
    grouped=defaultdict(list)
    for line in path.read_text().splitlines():
        if line.strip():
            row=json.loads(line);grouped[row.get("description","").strip()].append(row)
    records=[]
    for description,rows in sorted(grouped.items()):
        names=[str(row["event_name"]) for row in rows];canonical=next((step for step in FUNNEL_STEPS if step in names),None) or meanings.get(description.lower())
        if canonical:records.append(TaxonomyRecord(canonical_event=canonical,aliases=names,description=description or canonical,
          funnel_step=canonical,is_active=any(str(row.get("status","")).lower()=="active" for row in rows)))
    missing=sorted(set(FUNNEL_STEPS)-{record.canonical_event for record in records})
    if missing:raise ValueError(f"agent-visible taxonomy cannot resolve funnel events: {missing}")
    return records

def metric_definitions(minimum:int)->list[MetricDefinition]:
    definitions={"users":("distinct users","all scoped users"),"crash_rate":("distinct crashed users","distinct exposed users"),
      "checkout_crash_rate":("users crashing after checkout_start before confirmation/session end","checkout users"),
      "checkout_completion_rate":("users reaching order_confirmed after checkout_start","checkout users"),
      "payment_completion_rate":("users reaching order_confirmed after payment_submit","payment-submit users"),
      "latency_p50":("median event latency","events with latency"),"latency_p95":("95th percentile event latency","events with latency")}
    return [MetricDefinition(metric_name=name,numerator=num,denominator=den,grain="user or event aggregate",required_events=[],minimum_sample_size=minimum,
      limitations=["Observational telemetry; association is not proof of causation."]) for name,(num,den) in definitions.items()]
