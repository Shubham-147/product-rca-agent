"""Fixed, deterministic evidence pack for non-agentic System A."""
from __future__ import annotations
from pydantic import BaseModel,ConfigDict
from src.analytics import DeterministicAnalytics
from src.database import QueryResult
from src.systems.bootstrap import FUNNEL_STEPS

class EvidenceItem(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name:str
    result:QueryResult

class FixedEvidencePack(BaseModel):
    model_config=ConfigDict(extra="forbid")
    instance_id:str
    items:list[EvidenceItem]
    @property
    def query_ids(self):return {item.result.query_id for item in self.items}
    @property
    def results(self):return [item.result for item in self.items]

def build_fixed_evidence_pack(analytics:DeterministicAnalytics,instance_id:str,raw_funnel_names:list[str],minimum_users:int)->FixedEvidencePack:
    # v_events stores normalized lowercase names. De-duplicating aliases after
    # the same normalization keeps the naive funnel deterministic.
    raw_funnel_names=list(dict.fromkeys(
        str(name).strip().lower() for name in raw_funnel_names if str(name).strip()
    ))
    calls=[
      ("instance_summary",lambda:analytics.get_instance_summary(instance_id)),
      ("naive_raw_name_funnel",lambda:analytics.get_naive_funnel(instance_id,raw_funnel_names)),
      ("canonical_ordered_funnel",lambda:analytics.get_ordered_funnel(instance_id,FUNNEL_STEPS,True)),
    ]
    for dimension in ["os","device_type","device_age_bucket","geo","channel","is_returning","payment_method"]:
        calls.append((f"checkout_completion_by_{dimension}",lambda d=dimension:analytics.compare_metric_by_dimension(instance_id,"checkout_completion_rate",d,minimum_users=minimum_users)))
    calls.extend([
      ("crash_rate_by_os",lambda:analytics.compare_metric_by_dimension(instance_id,"crash_rate","os",minimum_users=minimum_users)),
      ("checkout_crash_rate_by_os",lambda:analytics.compare_metric_by_dimension(instance_id,"checkout_crash_rate","os",minimum_users=minimum_users)),
      ("checkout_latency_p50_by_os",lambda:analytics.compare_metric_by_dimension(instance_id,"latency_p50","os",minimum_users=minimum_users,screen="checkout")),
      ("checkout_latency_p95_by_os",lambda:analytics.compare_metric_by_dimension(instance_id,"latency_p95","os",minimum_users=minimum_users,screen="checkout")),
      ("crash_rate_by_device_age_bucket",lambda:analytics.compare_metric_by_dimension(instance_id,"crash_rate","device_age_bucket",minimum_users=minimum_users)),
      ("top_screens_by_crash_users",lambda:_top(analytics.compare_metric_by_dimension(instance_id,"crash_rate","screen",minimum_users=minimum_users),"numerator_users")),
      ("top_screens_by_p95_latency",lambda:_top(analytics.compare_metric_by_dimension(instance_id,"latency_p95","screen",minimum_users=minimum_users),"metric_value")),
    ])
    return FixedEvidencePack(instance_id=instance_id,items=[EvidenceItem(name=name,result=call()) for name,call in calls])

def _top(result:QueryResult,key:str)->QueryResult:
    rows=sorted(result.rows,key=lambda row:(-(row.get(key) or 0),str(row.get("dimension_value"))))[:10]
    return result.model_copy(update={"rows":rows,"row_count":len(rows),"result_summary":f"top screens ordered by {key}"})
