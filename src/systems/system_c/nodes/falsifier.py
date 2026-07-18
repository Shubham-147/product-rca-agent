from src.schemas import ConfounderTest
from .common import Node,remember
from .utils import evidence_from_results
from ..models import FalsificationResult
FALSIFICATION_TESTS=("screen_reach","temporal_precedence","exposed_unexposed","os_by_device_age",
 "os_by_device_type","crash_by_device_age","payment_method","geo","channel","returning_status",
 "latency_dose_response","expected_dropoff_optional_step","alternative_funnel_path","missing_alias",
 "deprecated_event","same_session_cross_session","naive_ordered_funnel")
class FalsifierNode(Node):
    name="falsifier"
    def run(self,state):
        h=state["current_hypothesis"];validation=state["validation_result"];counter=[];confounders=[];additional=[];revision=None
        if not validation.supported:
            verdict="reject";score=0.0;summary="Evidence fails validation: "+", ".join(validation.reasons)
        else:
            mechanism=h.proposed_mechanism.lower();context=" ".join(c["text"].lower() for c in state.get("retrieved_context",[]))
            expected=("expected drop" in context or "optional" in context) and any(e.lower() in context for e in h.required_events)
            if expected and h.benign_explanation:
                verdict="reject";score=.1;summary="Product context identifies expected drop-off or an optional valid path."
            else:
                confounder_text=" ".join(h.possible_confounders).lower()
                dimension=("payment_method" if "payment" in confounder_text else "geo" if "geo" in confounder_text else
                  "channel" if "channel" in confounder_text else "is_returning" if "return" in confounder_text else
                  "device_type" if "device type" in confounder_text else "device_age_bucket" if ("age" in confounder_text or h.expected_cohort.os or "crash" in mechanism) else "os")
                metric="latency_p95" if "latency" in mechanism else "crash_rate" if "crash" in mechanism else "checkout_completion_rate"
                cache_key=f"falsifier:{state['request'].instance_id}:{metric}:{dimension}"
                cached=cache_key in self.deps.query_cache
                if cached:result=self.deps.query_cache[cache_key]
                else:
                    result=self.deps.analytics.compare_metric_by_dimension(state["request"].instance_id,metric,dimension,None,self.deps.settings.minimum_segment_size)
                    self.deps.query_cache[cache_key]=result
                result=remember(self.deps,result)
                self.deps.logger.log(tool="system_c_falsifier",query_id=result.query_id,sql=result.executed_sql,
                  parameters=result.parameters,result_size=result.row_count,result_summary=result.result_summary,
                  duration_ms=result.duration_ms,cache_status="hit" if cached else "miss")
                counter=[result];additional.append(result.query_id)
                rates=[row.get("metric_value") for row in result.rows if isinstance(row.get("metric_value"),(int,float))]
                spread=(max(rates)-min(rates)) if len(rates)>1 else 0
                if spread>.25:
                    verdict="revise";score=.45;summary=f"Counter-test found material {dimension} variation."
                    confounders=[ConfounderTest(confounder=dimension,method=f"controlled {metric} segmentation",result=f"rate spread={spread:.3f}",status="supported")]
                else:
                    verdict="pass";score=.85;summary=f"Counter-test did not materially weaken the mechanism after {dimension} control."
                    confounders=[ConfounderTest(confounder=dimension,method=f"controlled {metric} segmentation",result=f"rate spread={spread:.3f}",status="ruled_out")]
                if verdict=="revise" and self.deps.guard.nodes+9>self.deps.guard.max_nodes:
                    verdict="reject";summary+=" Revision skipped because the graph budget cannot complete another guarded pass."
            revision="Narrow the cohort around the confounding segment and revise the mechanism." if verdict=="revise" else None
        falsification=FalsificationResult(verdict=verdict,counter_evidence=evidence_from_results(counter,h.context_chunk_ids,"counter"),
          confounders_found=confounders,additional_queries=additional,revision_instruction=revision,
          falsification_summary=summary,falsification_score=score)
        return {**state,"falsification_result":falsification,"query_results":[*state.get("query_results",[]),*counter]}
