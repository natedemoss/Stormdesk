"""Run the agent on one report and print every tool call and its final words.

    python scripts/trace_one.py "House fire on Jacktown Road, family got out"
    python scripts/trace_one.py "..." --faults 0.5 --seed 3     # with injected tool failures
    python scripts/trace_one.py "..." --outage plan_route       # one tool down for the whole run

Uses a copy of the cache (data/trace.db), so nothing lands in the demo queue.
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if "STORMDESK_DB" not in os.environ:
    shutil.copy(ROOT / "data" / "stormdesk.db", ROOT / "data" / "trace.db")
    os.environ["STORMDESK_DB"] = str(ROOT / "data" / "trace.db")
sys.path.insert(0, str(ROOT))
from stormdesk import agent  # noqa: E402
from stormdesk.triage import ingest  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("text")
ap.add_argument("--faults", type=float, default=0.0)
ap.add_argument("--seed", type=int, default=None)
ap.add_argument("--outage", choices=list(agent.OUTAGES), default=None)
a = ap.parse_args()

inc = ingest(a.text, "trace")
print(f"triage: {inc['category']}, urgency {inc['urgency']}")
res = agent.run(inc["id"], fault_rate=a.faults, fault_seed=a.seed, outage=a.outage)
for t in res["trace"]:
    r = t["result"]
    status = ("DOWN" if r.get("_outage") else "BAD" if r.get("_malformed") else "FAULT" if r.get("_fault")
              else "CHECK" if r.get("_rule") == "self_check" else "GUARD" if r.get("blocked_by")
              else "ERROR" if "error" in r else "ok")
    shown = f"  -> {r['error']}" if "error" in r else f"  -> {json.dumps(agent.for_model(r))[:90]}" if r.get("_malformed") else ""
    print(f"{status:5} {t['tool']}({json.dumps(t['args'])[:90]})" + shown)
print(f"\ndrafted: {res['drafted']}  ({res['seconds']} s)\nFINAL: {res['final'][:800]}")
draft = next((t for t in reversed(res["trace"]) if t["tool"] == "draft_dispatch" and "error" not in t["result"]), None)
if draft:
    print(f"ROUTE: {draft['args'].get('route_summary')}\nNOTES: {draft['args'].get('notes')}")
