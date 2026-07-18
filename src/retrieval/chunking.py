"""Stable, document-specific text chunking."""
from __future__ import annotations
import hashlib, json, re
from collections.abc import Iterable
from .schemas import *

def normalize_whitespace(text: str) -> str:
    return "\n".join(" ".join(line.split()) for line in text.strip().splitlines() if line.strip())

def _hash(text: str) -> str: return hashlib.sha256(text.encode()).hexdigest()
def _id(kind: str, doc: str, key: str) -> str:
    return hashlib.sha256(f"{kind}:{doc}:{key}".encode()).hexdigest()[:24]
def _chunk(kind, doc, key, text, metadata, parent=None):
    text=normalize_whitespace(text)
    return Chunk(chunk_id=_id(kind,doc,key),document_type=kind,document_id=doc,text=text,
                 content_hash=_hash(text),parent_chunk_id=parent,metadata=metadata)

def chunk_taxonomy(records: Iterable[TaxonomyRecord], version="unknown") -> list[Chunk]:
    out=[]
    for r in records:
        aliases=list(dict.fromkeys([r.canonical_event,*r.aliases]))
        text=(f"canonical_event: {r.canonical_event}\naliases: {', '.join(aliases)}\n"
              f"description: {r.description}\nscreen: {r.screen or 'unknown'}\n"
              f"predecessors: {', '.join(r.valid_predecessors)}\nsuccessors: {', '.join(r.valid_successors)}")
        out.append(_chunk("taxonomy",r.canonical_event,r.canonical_event,text,
            {"canonical_event":r.canonical_event,"aliases":json.dumps(aliases),"screen":r.screen or "",
             "funnel_step":r.funnel_step or "","is_active":r.is_active,
             "is_expected_dropoff":r.is_expected_dropoff,"taxonomy_version":version}))
    return deduplicate(out)

def _tokens(text): return re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]",text)
def _windows(text,size,overlap):
    t=_tokens(text)
    if len(t)<=size:return [text]
    return [" ".join(t[i:i+size]) for i in range(0,len(t),size-overlap)]

def chunk_prd(doc: PRDDocument) -> list[Chunk]:
    out=[]
    def walk(section,path):
        key="/".join([*path,section.heading]); body=f"{section.heading}\n{section.content}"
        for pi,parent_text in enumerate(_windows(body,800,50)):
            parent=_chunk("prd",doc.document_id,f"{key}:p{pi}",parent_text,
                          {"title":doc.title,"version":doc.version,"heading":section.heading,"level":"parent"})
            out.append(parent)
            for ci,child in enumerate(_windows(parent_text,325,50)):
                out.append(_chunk("prd",doc.document_id,f"{key}:p{pi}:c{ci}",child,
                    {"title":doc.title,"version":doc.version,"heading":section.heading,"level":"child"},parent.chunk_id))
        for child in section.children: walk(child,[*path,section.heading])
    for section in doc.sections: walk(section,[])
    return deduplicate(out)

def chunk_tickets(docs: Iterable[TicketDocument]) -> list[Chunk]:
    out=[]
    for d in docs:
        sections=[("description",d.description),("symptoms","; ".join(d.symptoms)),
                  ("investigation",d.investigation_notes or ""),("resolution",d.resolution or "")]
        full="\n".join(f"{k}: {v}" for k,v in sections if v)
        parts=[full] if len(_tokens(full))<=400 else [f"{k}: {v}" for k,v in sections if v]
        for i,text in enumerate(parts): out.append(_chunk("ticket",d.ticket_id,str(i),text,
            {"ticket_id":d.ticket_id,"title":d.title,"status":d.status,"affected_screen":d.affected_screen or ""}))
    return deduplicate(out)

def chunk_funnels(docs: Iterable[FunnelDefinition]) -> list[Chunk]:
    out=[]
    for d in docs:
        paths=[d.canonical_steps,*d.alternative_paths]
        for i,path in enumerate(paths):
            text=(f"funnel: {d.funnel_name}\npath: {' -> '.join(path)}\noptional_steps: {', '.join(d.optional_steps)}\n"
                  f"expected_dropoff_steps: {', '.join(d.expected_dropoff_steps)}")
            out.append(_chunk("funnel",d.funnel_name,str(i),text,{"funnel_name":d.funnel_name,"path_index":i}))
    return deduplicate(out)

def chunk_metrics(docs: Iterable[MetricDefinition]) -> list[Chunk]:
    return deduplicate([_chunk("metric",d.metric_name,d.metric_name,
        f"metric: {d.metric_name}\nnumerator: {d.numerator}\ndenominator: {d.denominator}\ngrain: {d.grain}\nrequired_events: {', '.join(d.required_events)}\nminimum_sample_size: {d.minimum_sample_size}\nlimitations: {'; '.join(d.limitations)}",
        {"metric_name":d.metric_name}) for d in docs])

def deduplicate(chunks: Iterable[Chunk]) -> list[Chunk]:
    seen=set();out=[]
    for c in chunks:
        if c.content_hash not in seen: seen.add(c.content_hash);out.append(c)
    return out
