"""Strict public API contracts; no internal controls are client-settable."""
from __future__ import annotations
from typing import Literal
import re
from pydantic import BaseModel,ConfigDict,Field,field_validator
from src.schemas import AnalysisRequest,RCAReport,TimeWindow

class APIModel(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)

class AnalysisAPIRequest(APIModel):
    instance_id:str=Field(min_length=1,max_length=64,pattern=r"^[A-Za-z0-9_-]+$")
    symptom:str=Field(min_length=1,max_length=2000)
    funnel_name:str|None=Field(default=None,max_length=100)
    suspected_screen:str|None=Field(default=None,max_length=100)
    incident_window:TimeWindow|None=None
    baseline_window:TimeWindow|None=None
    @field_validator("symptom")
    @classmethod
    def reject_control_or_protected_content(cls,value):
        lowered=value.lower()
        blocked=("manifest","ground_truth","planted_fault","fault_manifest","scorer","chain-of-thought",
          "system prompt","ignore previous","api key","tool budget","database path")
        if any(term in lowered for term in blocked):raise ValueError("symptom contains protected or control content")
        if re.search(r"\b(select|insert|update|delete|drop|alter|attach|copy|install|load)\b[\s\S]*\b(from|into|table|database)\b",lowered):
            raise ValueError("symptom must not contain SQL")
        return value
    def to_domain(self)->AnalysisRequest:return AnalysisRequest.model_validate(self.model_dump())

class SafeError(APIModel):
    code:str
    message:str

class ErrorResponse(APIModel):
    status:Literal["failed"]="failed"
    error:SafeError

class AnalysisResponse(APIModel):
    system:Literal["system_a","system_b","system_c"]
    instance_id:str
    status:Literal["completed"]="completed"
    duration_ms:float=Field(ge=0)
    result:RCAReport

class ComparedSystemResponse(APIModel):
    status:Literal["completed","failed"]
    duration_ms:float=Field(ge=0)
    result:RCAReport|None=None
    error:SafeError|None=None

class ComparisonResponse(APIModel):
    instance_id:str
    symptom:str
    systems:dict[Literal["system_a","system_b","system_c"],ComparedSystemResponse]

class HealthResponse(APIModel):
    status:Literal["ok"]="ok"
    systems:list[Literal["system_a","system_b","system_c"]]
