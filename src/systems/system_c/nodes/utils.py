from src.schemas import Evidence
def row_sample_size(row):
    for key in ("exposed_users","users","sessions","events","outcome_users"):
        value=row.get(key)
        if isinstance(value,(int,float)):return int(value)
    return 0
def row_observed(row):
    for key in ("metric_value","outcome_rate","users","numerator_users","events","sessions"):
        value=row.get(key)
        if isinstance(value,(int,float)):return float(value)
    return 0.0
def evidence_from_results(results,chunk_ids,prefix="e"):
    evidence=[]
    for index,result in enumerate(results,1):
        if not result.rows:continue
        row=max(result.rows,key=row_sample_size)
        evidence.append(Evidence(evidence_id=f"{prefix}{index}",claim=result.result_summary,
          metric_name=result.result_summary,observed_value=row_observed(row),sample_size=row_sample_size(row),
          query_id=result.query_id,source_chunk_ids=list(chunk_ids)))
    return evidence
