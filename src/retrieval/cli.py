"""Explicit command for building/updating the shared persistent RAG index."""
from __future__ import annotations
import argparse
from pathlib import Path
from src.config import get_settings
from src.systems.bootstrap import load_runtime_assets

def main()->None:
    parser=argparse.ArgumentParser(prog="build-rag-index")
    parser.add_argument("--instance-id",required=True,help="Task whose agent-visible corpus paths are indexed")
    parser.add_argument("--data-root",type=Path,default=Path("data"))
    args=parser.parse_args()
    assets=load_runtime_assets(args.instance_id,args.data_root,get_settings(),index_dense=True)
    print(f"RAG index ready at {assets.settings.chroma_persist_path} for {args.instance_id}")
if __name__=="__main__":main()
