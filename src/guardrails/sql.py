"""SQL and identifier boundaries for compiled and fallback source reads."""
from __future__ import annotations
import re
from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field
from .errors import GuardrailError

ALLOWED_RELATIONS={"events","users","v_events","v_users","v_users_enriched","v_events_resolved"}
BLOCKED_PATTERNS=("manifest","ground_truth","planted_fault","fault_manifest","scorer","labels","answers")
ALLOWED_DIMENSIONS={"os","device_type","device_age_bucket","geo","channel","is_returning","payment_method","screen"}
ALLOWED_METRICS={"users","crash_rate","checkout_crash_rate","checkout_completion_rate","payment_completion_rate","latency_p50","latency_p95"}
ALLOWED_COLUMNS={"user_id","session_id","event_ts","event_name","raw_event_name","canonical_event","screen","os","device_type","device_age_months","device_age_bucket","geo","channel","is_returning","latency_ms","is_crash","payment_method","instance_id","acquired_ts","funnel_step","is_expected_dropoff","taxonomy_version"}
_MUTATION=re.compile(r"\b(insert|update|delete|create|drop|alter|copy|attach|detach|install|load|export|import|pragma|call|vacuum|truncate)\b",re.I)
_RELATION=re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)",re.I)
_CTE=re.compile(r"(?:\bwith|,)\s*([a-z_][a-z0-9_]*)(?:\s*\([^)]*\))?\s+as\s*\(",re.I)

def validate_identifier(value:str,allowed:set[str],kind="identifier")->str:
    if value not in allowed: raise GuardrailError(f"unsupported {kind}: {value}")
    return value
def validate_dimension(value:str)->str:return validate_identifier(value,ALLOWED_DIMENSIONS,"dimension")
def validate_metric(value:str)->str:return validate_identifier(value,ALLOWED_METRICS,"metric")
def sanitize_cohort_table_name(value:str)->str:
    if not re.fullmatch(r"cohort_[a-z0-9_]{1,48}",value):raise GuardrailError("invalid cohort table name")
    return value

def _base(sql:str)->tuple[str,set[str]]:
    stripped=sql.strip()
    if not stripped or ";" in stripped.rstrip(";"):raise GuardrailError("exactly one SQL statement is allowed")
    if "--" in stripped or "/*" in stripped or "*/" in stripped:raise GuardrailError("SQL comments are not allowed")
    if not re.match(r"^(select|with)\b",stripped,re.I):raise GuardrailError("source queries must be SELECT or WITH")
    if _MUTATION.search(stripped):raise GuardrailError("source query contains a forbidden operation")
    low=stripped.lower()
    for pattern in BLOCKED_PATTERNS:
        if re.search(rf"\b[a-z0-9_]*{re.escape(pattern)}[a-z0-9_]*\b",low):raise GuardrailError(f"blocked source pattern: {pattern}")
    relations={x.lower() for x in _RELATION.findall(stripped)};relations.discard("lateral")
    ctes={x.lower() for x in _CTE.findall(stripped)}
    forbidden=relations-ALLOWED_RELATIONS-ctes
    if forbidden:raise GuardrailError(f"source query references forbidden relations: {sorted(forbidden)}")
    return stripped,relations

def validate_compiled_query(sql:str,instance_id:str)->None:
    stripped,_=_base(sql)
    if not instance_id or not instance_id.strip():raise GuardrailError("instance_id is required")
    if "instance_id" not in stripped.lower():raise GuardrailError("query must filter by instance_id")

def validate_fallback_query(sql:str,instance_id:str,max_rows:int)->None:
    stripped,_=_base(sql);validate_compiled_query(stripped,instance_id)
    limits=re.findall(r"\blimit\s+(\d+)\b",stripped,re.I)
    if not limits:raise GuardrailError("fallback SQL requires a literal LIMIT")
    if int(limits[-1])>max_rows:raise GuardrailError("fallback LIMIT exceeds configured row maximum")

# Backward-compatible name for trusted deterministic analytics.
def validate_source_query(sql:str,instance_id:str="__compiled__")->None:
    validate_compiled_query(sql,instance_id)

class SafeSelectQuery(BaseModel):
    model_config=ConfigDict(extra="forbid")
    instance_id:str=Field(min_length=1)
    relation:Literal["v_events","v_users","v_users_enriched","v_events_resolved"]
    columns:list[str]
    equals:dict[str,Any]=Field(default_factory=dict)
    limit:int=Field(default=100,ge=1)
    def compile(self,max_rows:int)->tuple[str,list[Any]]:
        if self.limit>max_rows:raise GuardrailError("query limit exceeds configured maximum")
        cols=[validate_identifier(c,ALLOWED_COLUMNS,"column") for c in self.columns]
        filters=[];params=[]
        for col,val in self.equals.items():filters.append(f"{validate_identifier(col,ALLOWED_COLUMNS,'column')} = ?");params.append(val)
        filters.insert(0,"instance_id = ?");params.insert(0,self.instance_id)
        return f"SELECT {', '.join(cols)} FROM {self.relation} WHERE {' AND '.join(filters)} LIMIT {self.limit}",params
