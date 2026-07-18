from src.guardrails import BLOCKED_PATTERNS,GuardrailError
from src.retrieval import RetrievalMode
from .common import Node
class ContextRetrieverNode(Node):
    name="context_retriever"
    def run(self,state):
        request=state["request"];query=f"{request.symptom} {request.suspected_screen or ''}".strip()
        if any(x in query.lower() for x in BLOCKED_PATTERNS):raise GuardrailError("protected context request")
        searches=[(query,RetrievalMode.PRODUCT_INTENT),(query,RetrievalMode.HISTORICAL_TICKET),
          (query,RetrievalMode.EVENT_RESOLUTION),
          ("funnel optional expected dropoff alternative path",RetrievalMode.PRODUCT_INTENT),
          ("conversion crash latency numerator denominator",RetrievalMode.METRIC_DEFINITION)]
        chunks=[];seen=set()
        for text,mode in searches:
            for hit in self.deps.retriever.retrieve(text,mode,top_k=5):
                c=hit.chunk
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id);chunks.append({"chunk_id":c.chunk_id,"document_type":c.document_type,"text":c.text[:self.deps.settings.max_chunk_characters],"metadata":c.metadata})
                if len(chunks)>=self.deps.settings.max_prompt_chunks:break
            if len(chunks)>=self.deps.settings.max_prompt_chunks:break
        self.deps.known_chunk_ids.update(seen)
        return {**state,"retrieved_context":chunks,"context_retry_used":bool(state.get("current_hypothesis")) or state.get("context_retry_used",False)}
