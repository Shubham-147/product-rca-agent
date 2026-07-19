from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.scorer import load_gold, score_case
from system_a.schema import SystemAOutput


def main() -> None:
    p=argparse.ArgumentParser(description="Offline evaluation; loads gold only after saved predictions exist")
    p.add_argument("--data",default="data"); p.add_argument("--predictions",default="artifacts/system_a/predictions"); p.add_argument("--output",default="artifacts/system_a/metrics.json")
    a=p.parse_args(); data=Path(a.data); pred_dir=Path(a.predictions)
    ids=[x["instance_id"] for x in json.loads((data/"warehouses/index.json").read_text())]
    missing=[iid for iid in ids if not (pred_dir/f"{iid}.json").is_file()]
    if missing: raise FileNotFoundError(f"Predictions must exist before ground truth is loaded; missing: {missing}")
    predictions={iid:SystemAOutput.model_validate_json((pred_dir/f"{iid}.json").read_text()) for iid in ids}
    rows=[]
    for iid in ids:  # Ground truth first becomes reachable here, after all predictions are loaded.
        gold=load_gold(data/"ground_truth",iid)
        rows.append({"instance_id":iid,**score_case(predictions[iid].hypotheses,gold,str(data/"warehouses"/f"warehouse_{iid}.duckdb"))})
    faults=[r for r in rows if r["has_fault"]]; traps=[r for r in rows if not r["has_fault"]]; f1=[r["cohort_f1"] for r in faults if r.get("cohort_f1") is not None]
    timings=[]
    for iid in ids:
        trace_path=pred_dir.parent/"traces"/f"{iid}.json"
        if trace_path.is_file():
            timing=json.loads(trace_path.read_text()).get("timing",{})
            if timing.get("recorded") and timing.get("elapsed_seconds") is not None:
                timings.append(timing)
    aggregate={"cases":len(rows),"fault_cases":len(faults),"no_fault_cases":len(traps),"attribution_top1":sum(bool(r["top1_correct"]) for r in faults)/len(faults) if faults else 0,"recall_at_3":sum(bool(r["recall_at_3"]) for r in faults)/len(faults) if faults else 0,"mean_cohort_f1":sum(f1)/len(f1) if f1 else 0,"no_fault_false_positive_rate":sum(bool(r["false_positive"]) for r in traps)/len(traps) if traps else 0,"timed_cases":len(timings),"mean_elapsed_seconds":sum(t["elapsed_seconds"] for t in timings)/len(timings) if timings else None,"mean_embedding_elapsed_seconds":sum(t["embedding_elapsed_seconds"] for t in timings if t.get("embedding_elapsed_seconds") is not None)/len([t for t in timings if t.get("embedding_elapsed_seconds") is not None]) if any(t.get("embedding_elapsed_seconds") is not None for t in timings) else None,"mean_llm_elapsed_seconds":sum(t["llm_elapsed_seconds"] for t in timings)/len(timings) if timings else None}
    out={"system":"System A - Vanilla RAG","aggregate":aggregate,"cases":rows}; path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(aggregate,indent=2))


if __name__=="__main__": main()
