"""Shared CLI arguments and AnalysisRequest construction for A, B, and C."""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
from src.schemas import AnalysisRequest,TimeWindow

def add_request_arguments(parser:argparse.ArgumentParser)->None:
    parser.add_argument("--instance-id",required=True)
    parser.add_argument("--symptom",required=True)
    parser.add_argument("--funnel-name")
    parser.add_argument("--suspected-screen")
    parser.add_argument("--incident-window",nargs=2,metavar=("START","END"))
    parser.add_argument("--baseline-window",nargs=2,metavar=("START","END"))
    parser.add_argument("--data-root",type=Path,default=Path("data"))

def analysis_request_from_args(args:argparse.Namespace)->AnalysisRequest:
    return AnalysisRequest(instance_id=args.instance_id,symptom=args.symptom,
      funnel_name=args.funnel_name,suspected_screen=args.suspected_screen,
      incident_window=_window(args.incident_window),baseline_window=_window(args.baseline_window))

def _window(value):
    if value is None:return None
    try:return TimeWindow(start=datetime.fromisoformat(value[0].replace("Z","+00:00")),end=datetime.fromisoformat(value[1].replace("Z","+00:00")))
    except ValueError as exc:raise argparse.ArgumentTypeError("windows require ISO-8601 START END values") from exc
