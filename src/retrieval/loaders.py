"""Load agent-visible textual knowledge into the shared document contracts."""
from __future__ import annotations
import json,re
from pathlib import Path
from pydantic import BaseModel
from .schemas import PRDDocument,PRDSection,TaxonomyRecord,TicketDocument

def load_taxonomy_records(path:Path)->list[TaxonomyRecord]:
    records=[]
    with path.open() as handle:
        for line_number,line in enumerate(handle,1):
            if not line.strip():continue
            data=json.loads(line)
            if "canonical_event" not in data:
                raise ValueError(f"{path}:{line_number} is alias-only; canonical grouping must be agent-visible")
            records.append(TaxonomyRecord.model_validate(data))
    return records

def load_prd_markdown(path:Path,*,document_id:str,version:str)->PRDDocument:
    text=path.read_text();title=path.stem;sections=[];current=None
    for line in text.splitlines():
        match=re.match(r"^(#{1,6})\s+(.+)$",line)
        if match:
            if len(match.group(1))==1:title=match.group(2);continue
            current=PRDSection(heading=match.group(2),content="");sections.append(current)
        elif current is not None: current.content += line+"\n"
    return PRDDocument(document_id=document_id,title=title,version=version,sections=sections)

def load_ticket_markdown(path:Path)->TicketDocument:
    text=path.read_text().strip();lines=text.splitlines();title=path.stem
    if lines and lines[0].lower().startswith("subject:"): title=lines.pop(0).split(":",1)[1].strip()
    return TicketDocument(ticket_id=path.stem,title=title,description="\n".join(lines).strip(),status="unknown")

def load_json_documents(path:Path,model:type[BaseModel]):
    data=json.loads(path.read_text());items=data if isinstance(data,list) else [data]
    return [model.model_validate(item) for item in items]
