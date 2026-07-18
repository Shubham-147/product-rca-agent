"""Credential-free integration checks shared by Systems A, B, and C."""
from __future__ import annotations
import argparse,subprocess,sys
from pathlib import Path
from src.config import AppSettings
from src.schemas import AnalysisRequest,RCAReport
from src.systems.bootstrap import FUNNEL_STEPS,load_runtime_assets
from src.systems.cli import add_request_arguments,analysis_request_from_args
from src.systems.system_a.pipeline import SystemAPipeline
from src.systems.system_b.agent import SystemBAgent
from src.systems.system_c.graph import SystemCWorkflow

ROOT=Path(__file__).resolve().parents[1]

def test_unified_cli_builds_the_shared_analysis_request():
    parser=argparse.ArgumentParser();add_request_arguments(parser)
    args=parser.parse_args(["--instance-id","inst_003","--symptom","decline","--funnel-name","shopfunnel",
      "--suspected-screen","checkout","--incident-window","2026-01-15T00:00:00+00:00","2026-01-29T00:00:00+00:00",
      "--baseline-window","2026-01-01T00:00:00+00:00","2026-01-15T00:00:00+00:00"])
    request=analysis_request_from_args(args)
    assert isinstance(request,AnalysisRequest) and request.funnel_name=="shopfunnel" and request.incident_window.start>request.baseline_window.start

def test_all_commands_expose_identical_request_flags():
    flags={"--instance-id","--symptom","--funnel-name","--suspected-screen","--incident-window","--baseline-window"}
    for command in ("run-system-a","run-system-b","run-system-c"):
        output=subprocess.run([sys.executable,str(ROOT/"scripts"/command),"--help"],cwd=ROOT,text=True,capture_output=True,check=True).stdout
        assert all(flag in output for flag in flags)

def test_shared_runtime_assets_are_lazy_and_agent_visible(tmp_path):
    cfg=AppSettings(source_duckdb_path=tmp_path/"unused",runtime_duckdb_path=tmp_path/"runtime.duckdb",chroma_persist_path=tmp_path/"chroma")
    assets=load_runtime_assets("inst_003",ROOT/"data",cfg,index_dense=False)
    assert assets.task["instance_id"]=="inst_003" and assets.manager.settings.source_duckdb_path.name=="warehouse_inst_003.duckdb"
    assert set(FUNNEL_STEPS)==set(assets.resolver.records)
    assert not (tmp_path/"runtime.duckdb").exists() and not (tmp_path/"chroma").exists()

def test_three_systems_share_the_rca_report_contract():
    assert SystemAPipeline.run.__annotations__["return"]=="RCAReport"
    assert SystemBAgent.run.__annotations__["return"]=="RCAReport"
    assert SystemCWorkflow.run.__annotations__["return"]=="RCAReport"
