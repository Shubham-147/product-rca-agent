"""Two-store writer — the physical enforcement of the data-exposure contract.

AGENT-VISIBLE   -> data/warehouses/warehouse_<id>.duckdb
    events(user_id, session_id, event_ts, event_name, screen, os, device_type,
           device_age_months, geo, channel, is_returning, latency_ms, is_crash,
           payment_method, instance_id)
    users (user_id, os, device_type, device_age_months, geo, channel,
           is_returning, acquired_ts, instance_id)
    NO `persona`, NO `canonical` — those would leak the answer.

SCORER-ONLY     -> data/ground_truth/
    gold_<id>.json          the held-out Gold record
    persona_<id>.json       user_id -> persona
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from .schemas import Gold

# columns the agent may see on the users table (denormalised onto events too)
_USER_ATTRS = ["os", "device_type", "device_age_months", "geo", "channel", "is_returning"]


def write_instance(warehouse_dir: Path, ground_truth_dir: Path,
                   gen: dict, gold: Gold) -> Path:
    warehouse_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_dir.mkdir(parents=True, exist_ok=True)
    iid = gold.instance_id

    users = pd.DataFrame(gen["users"])
    events = pd.DataFrame(gen["events"])

    # --- build the AGENT-VISIBLE warehouse -----------------------------------
    # drop `canonical` (that IS the event-resolution answer)
    events = events.drop(columns=[c for c in ["canonical"] if c in events.columns])
    # denormalise user attributes onto events
    attrs = users[["user_id"] + _USER_ATTRS]
    events = events.merge(attrs, on="user_id", how="left")
    events["instance_id"] = iid

    users_public = users[["user_id"] + _USER_ATTRS + ["acquired_ts"]].copy()
    users_public["instance_id"] = iid

    wh_path = warehouse_dir / f"warehouse_{iid}.duckdb"
    if wh_path.exists():
        wh_path.unlink()
    con = duckdb.connect(str(wh_path))
    con.register("events_df", events)
    con.register("users_df", users_public)
    con.execute("CREATE TABLE events AS SELECT * FROM events_df")
    con.execute("CREATE TABLE users  AS SELECT * FROM users_df")
    con.close()

    # --- SCORER-ONLY ground truth --------------------------------------------
    (ground_truth_dir / f"gold_{iid}.json").write_text(gold.model_dump_json(indent=2))
    persona_map = dict(zip(users["user_id"], users["persona"]))
    (ground_truth_dir / f"persona_{iid}.json").write_text(json.dumps(persona_map))

    return wh_path
