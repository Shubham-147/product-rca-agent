"""Lazy CPU cross-encoder with an injectable test boundary."""
class CrossEncoderReranker:
    def __init__(self,model_name):self.model_name=model_name;self._model=None
    def score(self,query,texts):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            try:self._model=CrossEncoder(self.model_name,device="cpu",local_files_only=True)
            except Exception:self._model=CrossEncoder(self.model_name,device="cpu")
        return [float(x) for x in self._model.predict([(query,t) for t in texts])]

class LexicalFallbackReranker:
    def score(self,query,texts):
        q=set(query.lower().split())
        return [len(q & set(t.lower().split()))/max(len(q),1) for t in texts]
