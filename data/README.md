# `data/` — generated benchmark (git-ignored, reproducible)

The contents here are **generated and not committed** (large + fully reproducible
from seeds). Regenerate with:

```bash
python -m simulator.generate --n 24 --users 8000 --seed 1000 --out data
```

Layout produced (see [../docs/generated-data-overview.md](../docs/generated-data-overview.md)):

```
data/
  corpus/         AGENT-VISIBLE  PRD + cursed event taxonomy (static)
  warehouses/     AGENT-VISIBLE  warehouse_<id>.duckdb per instance + index.json
  tasks/          AGENT-VISIBLE  task_<id>.json (the question per instance)
  TASK.md         AGENT-VISIBLE  human-readable task definition
  ground_truth/   SCORER-ONLY    gold_<id>.json, persona_<id>.json, event_canonical_map.json
```

Run a scored test case:
```bash
python -m eval.run_case --id inst_001     # one case, verbose
python -m eval.run_case --all             # all cases, summary
```
