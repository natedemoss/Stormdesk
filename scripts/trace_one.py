"""Run the agent on one report and print every tool call and its final words.

    python scripts/trace_one.py "House fire on Jacktown Road, family got out"
    python scripts/trace_one.py "..." --faults 0.5 --seed 3     # with injected tool failures

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
a = ap.parse_args()

inc = ingest(a.text, "trace")
print(f"triage: {inc['category']}, urgency {inc['urgency']}")
res = agent.run(inc["id"], fault_rate=a.faults, fault_seed=a.seed)
for t in res["trace"]:
    r = t["result"]
    status = "FAULT" if r.get("_fault") else "GUARD" if r.get("blocked_by") else "ERROR" if "error" in r else "ok"
    print(f"{status:5} {t['tool']}({json.dumps(t['args'])[:90]})" + (f"  -> {r['error']}" if "error" in r else ""))
print(f"\ndrafted: {res['drafted']}  ({res['seconds']} s)\nFINAL: {res['final'][:800]}")
