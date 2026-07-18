"""FastAPI demo surface over the existing Product RCA systems."""
from __future__ import annotations
import time
import traceback
from pathlib import Path
from fastapi import Depends,FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.config import get_settings
from src.observability import get_logger
from .dependencies import PipelineRunner,SystemName,get_pipeline_runner
from .models import *

REQUEST_EXAMPLE={"instance_id":"inst_003","symptom":"Investigate the checkout funnel and identify the most likely root cause","funnel_name":"purchase","suspected_screen":"checkout"}
ERROR_EXAMPLE={"status":"failed","error":{"code":"ANALYSIS_FAILED","message":"System B could not complete the analysis."}}
REPORT_EXAMPLE={"instance_id":"inst_003","symptom":REQUEST_EXAMPLE["symptom"],"hypotheses":[],"unresolved_questions":[],
  "run_metadata":{"run_id":"run_demo","system_name":"system_a","instance_id":"inst_003","start_time":"2026-01-01T00:00:00Z","completion_time":"2026-01-01T00:00:01Z","status":"completed"}}
ANALYSIS_EXAMPLE={"system":"system_a","instance_id":"inst_003","status":"completed","duration_ms":1250,"result":REPORT_EXAMPLE}
app=FastAPI(title="Product RCA Agent API",version="1.0.0",docs_url="/docs",redoc_url="/redoc")
logger=get_logger(__name__)
app.add_middleware(CORSMiddleware,allow_origins=get_settings().api_cors_origins,allow_credentials=True,
  allow_methods=["GET","POST"],allow_headers=["Content-Type"])

@app.get("/api/v1/health",response_model=HealthResponse,tags=["Health"],summary="API health",
  responses={200:{"content":{"application/json":{"example":{"status":"ok","systems":["system_a","system_b","system_c"]}}}}})
def health()->HealthResponse:return HealthResponse(systems=["system_a","system_b","system_c"])

def _failure(system:SystemName,exc:Exception):
    logger.error("analysis_failed system=%s error_type=%s reason_code=%s location=%s provider=%s",
      system,type(exc).__name__,_safe_reason_code(exc),_safe_failure_location(exc),_safe_provider_metadata(exc))
    code,status=_classify(exc);label=system.replace("_"," ").title()
    return JSONResponse(status_code=status,content=ErrorResponse(error=SafeError(code=code,message=f"{label} could not complete the analysis.")).model_dump(mode="json"))

def _execute(system:SystemName,request:AnalysisAPIRequest,runner:PipelineRunner):
    started=time.perf_counter()
    try:
        report=runner.run(system,request.to_domain())
        return AnalysisResponse(system=system,instance_id=request.instance_id,duration_ms=(time.perf_counter()-started)*1000,result=report)
    except Exception as exc:return _failure(system,exc)

@app.post("/api/v1/analyse/system-a",response_model=AnalysisResponse,responses={200:{"content":{"application/json":{"example":ANALYSIS_EXAMPLE}}},400:{"model":ErrorResponse},500:{"model":ErrorResponse,"content":{"application/json":{"example":ERROR_EXAMPLE}}},503:{"model":ErrorResponse},504:{"model":ErrorResponse}},
  tags=["Analysis"],summary="Run System A",description="Runs the fixed non-agentic Vanilla RAG pipeline.",openapi_extra={"requestBody":{"content":{"application/json":{"example":REQUEST_EXAMPLE}}}})
def analyse_system_a(request:AnalysisAPIRequest,runner:PipelineRunner=Depends(get_pipeline_runner)):return _execute("system_a",request,runner)

@app.post("/api/v1/analyse/system-b",response_model=AnalysisResponse,responses={200:{"content":{"application/json":{"example":{**ANALYSIS_EXAMPLE,"system":"system_b","result":{**REPORT_EXAMPLE,"run_metadata":{**REPORT_EXAMPLE["run_metadata"],"system_name":"system_b"}}}}}},400:{"model":ErrorResponse},500:{"model":ErrorResponse,"content":{"application/json":{"example":ERROR_EXAMPLE}}},503:{"model":ErrorResponse},504:{"model":ErrorResponse}},
  tags=["Analysis"],summary="Run System B",description="Runs the bounded Pydantic AI agent with typed tools.",openapi_extra={"requestBody":{"content":{"application/json":{"example":REQUEST_EXAMPLE}}}})
def analyse_system_b(request:AnalysisAPIRequest,runner:PipelineRunner=Depends(get_pipeline_runner)):return _execute("system_b",request,runner)

@app.post("/api/v1/analyse/system-c",response_model=AnalysisResponse,responses={200:{"content":{"application/json":{"example":{**ANALYSIS_EXAMPLE,"system":"system_c","result":{**REPORT_EXAMPLE,"run_metadata":{**REPORT_EXAMPLE["run_metadata"],"system_name":"system_c"}}}}}},400:{"model":ErrorResponse},500:{"model":ErrorResponse,"content":{"application/json":{"example":ERROR_EXAMPLE}}},503:{"model":ErrorResponse},504:{"model":ErrorResponse}},
  tags=["Analysis"],summary="Run System C",description="Runs the LangGraph Validator/Falsifier workflow.",openapi_extra={"requestBody":{"content":{"application/json":{"example":REQUEST_EXAMPLE}}}})
def analyse_system_c(request:AnalysisAPIRequest,runner:PipelineRunner=Depends(get_pipeline_runner)):return _execute("system_c",request,runner)

@app.post("/api/v1/analyse/compare",response_model=ComparisonResponse,tags=["Analysis"],summary="Run all three systems",
  description="Runs A, B, and C independently and sequentially. Results are not scored or judged.",openapi_extra={"requestBody":{"content":{"application/json":{"example":REQUEST_EXAMPLE}}}})
def compare(request:AnalysisAPIRequest,runner:PipelineRunner=Depends(get_pipeline_runner)):
    systems={}
    for system in ("system_a","system_b","system_c"):
        started=time.perf_counter()
        try:
            report=runner.run(system,request.to_domain());systems[system]=ComparedSystemResponse(status="completed",duration_ms=(time.perf_counter()-started)*1000,result=report)
        except Exception as exc:
            logger.error("comparison_system_failed system=%s error_type=%s reason_code=%s location=%s provider=%s",
              system,type(exc).__name__,_safe_reason_code(exc),_safe_failure_location(exc),_safe_provider_metadata(exc))
            code,_=_classify(exc);systems[system]=ComparedSystemResponse(status="failed",duration_ms=(time.perf_counter()-started)*1000,
              error=SafeError(code=code,message=f"{system.replace('_',' ').title()} could not complete the analysis."))
    return ComparisonResponse(instance_id=request.instance_id,symptom=request.symptom,systems=systems)

def _classify(exc:Exception)->tuple[str,int]:
    text=str(exc).lower()
    error_type=type(exc).__name__
    if isinstance(exc,(TimeoutError,)) or "timed out" in text or "timeout" in text:return "ANALYSIS_TIMEOUT",504
    if isinstance(exc,FileNotFoundError) and "task not found" in text:return "INVALID_REQUEST",400
    if error_type in {"PermissionDeniedError","AuthenticationError","ModelHTTPError","NotFoundError"}:return "DEPENDENCY_UNAVAILABLE",503
    if isinstance(exc,(FileNotFoundError,ConnectionError,ImportError)) or any(x in text for x in ("api key","credential","database does not exist","index","connection error")):return "DEPENDENCY_UNAVAILABLE",503
    if isinstance(exc,(ValueError,KeyError)) and any(x in text for x in ("task","instance","unsupported system")):return "INVALID_REQUEST",400
    return "ANALYSIS_FAILED",500

def _safe_reason_code(exc:Exception)->str:
    text=str(exc).lower();error_type=type(exc).__name__
    reasons=(("tool-call budget","TOOL_BUDGET"),("mechanism only repeats","SYMPTOM_ONLY_MECHANISM"),
      ("query_id","EVIDENCE_QUERY_ID"),("sample_size","EVIDENCE_SAMPLE_SIZE"),("stored query result","EVIDENCE_VALUE_MISMATCH"),
      ("source chunk","SOURCE_CHUNK_ID"),("unresolved event","UNRESOLVED_EVENT"),("cohort","COHORT_INVALID"),
      ("limitations","LIMITATIONS_MISSING"),("exit conditions","EXIT_CONDITIONS"),("schema","OUTPUT_SCHEMA"))
    for fragment,code in reasons:
        if fragment in text:return code
    if error_type=="BadRequestError":
        return f"PROVIDER_BAD_REQUEST_{str(getattr(exc,'code',None) or 'UNKNOWN').upper()}"
    if error_type in {"PermissionDeniedError","AuthenticationError","ModelHTTPError","NotFoundError"}:return "PROVIDER_ACCESS"
    if error_type=="InvalidInputException":return "DUCKDB_INVALID_INPUT"
    if error_type=="UnexpectedModelBehavior":return "MODEL_PROTOCOL"
    return "UNCLASSIFIED"

def _safe_failure_location(exc:Exception)->str:
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        if "/src/" in frame.filename:
            path=Path(frame.filename);return f"{path.parent.name}.{path.stem}:{frame.name}:{frame.lineno}"
    return "external"

def _safe_provider_metadata(exc:Exception)->dict:
    target=exc
    while target.__cause__ is not None:target=target.__cause__
    body=getattr(target,"body",None);error=body.get("error",body) if isinstance(body,dict) else {}
    return {"error_type":type(target).__name__,"status":getattr(target,"status_code",None),
      "type":error.get("type") if isinstance(error,dict) else None,
      "code":error.get("code") if isinstance(error,dict) else getattr(target,"code",None),
      "param":error.get("param") if isinstance(error,dict) else getattr(target,"param",None)}
