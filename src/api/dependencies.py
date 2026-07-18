"""Lazy construction of existing pipelines for synchronous demo requests."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Literal,Protocol
from src.config import AppSettings,get_settings
from src.schemas import AnalysisRequest,RCAReport
from src.systems.bootstrap import RuntimeAssets,load_runtime_assets
from src.systems.system_a.pipeline import OpenAIStructuredLLM,SystemAPipeline
from src.systems.system_b.agent import PydanticAIRunner,SystemBAgent,build_dependencies as build_b_dependencies
from src.systems.system_c.graph import OpenAIStructuredModel,SystemCWorkflow,build_dependencies as build_c_dependencies

SystemName=Literal["system_a","system_b","system_c"]

class PipelineRunner(Protocol):
    def run(self,system:SystemName,request:AnalysisRequest)->RCAReport:...

class ExistingPipelineRunner:
    def __init__(self,settings:AppSettings|None=None,data_root:Path=Path("data")):
        self.settings=settings or get_settings();self.data_root=data_root
        self._assets:dict[str,RuntimeAssets]={};self._system_a:dict[str,SystemAPipeline]={}
        self._b_runners:dict[str,PydanticAIRunner]={};self._c_models:dict[str,OpenAIStructuredModel]={}
    def _runtime(self,instance_id:str)->RuntimeAssets:
        if instance_id not in self._assets:
            self._assets[instance_id]=load_runtime_assets(instance_id,self.data_root,self.settings)
        return self._assets[instance_id]
    def run(self,system:SystemName,request:AnalysisRequest)->RCAReport:
        assets=self._runtime(request.instance_id)
        if system=="system_a":
            if request.instance_id not in self._system_a:
                key=assets.settings.openai_api_key.get_secret_value() if assets.settings.openai_api_key else None
                self._system_a[request.instance_id]=SystemAPipeline(retriever=assets.retriever,resolver=assets.resolver,
                  llm=OpenAIStructuredLLM(assets.settings.llm_model,key),settings=assets.settings,manager=assets.manager)
            return self._system_a[request.instance_id].run(request)
        if system=="system_b":
            key=assets.settings.openai_api_key.get_secret_value() if assets.settings.openai_api_key else None
            runner=self._b_runners.setdefault(assets.settings.llm_model,PydanticAIRunner(assets.settings.llm_model,key))
            deps=build_b_dependencies(request.instance_id,assets.settings,assets.retriever,assets.resolver,assets.manager)
            return SystemBAgent(deps=deps,runner=runner,settings=assets.settings).run(request)
        if system=="system_c":
            key=assets.settings.openai_api_key.get_secret_value() if assets.settings.openai_api_key else None
            model=self._c_models.setdefault(assets.settings.llm_model,OpenAIStructuredModel(assets.settings.llm_model,key))
            deps=build_c_dependencies(request.instance_id,assets.settings,assets.retriever,assets.resolver,assets.manager,model)
            return SystemCWorkflow(deps).run(request)
        raise ValueError("unsupported system")

@lru_cache(maxsize=1)
def get_pipeline_runner()->ExistingPipelineRunner:return ExistingPipelineRunner()
