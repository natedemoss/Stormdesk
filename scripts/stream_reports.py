"""Feed demo reports into the incident queue one at a time (for the live demo).

    python scripts/stream_reports.py --file data/demo_reports.jsonl --delay 3
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk.triage import ingest  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--file", default="data/demo_reports.jsonl")
ap.add_argument("--delay", type=float, default=3)
a = ap.parse_args()

for line in open(a.file):
    r = json.loads(line)
    out = ingest(r["text"], r.get("channel", "sms"))
    print(f"#{out['id']:>3}  U{out['urgency']}  {out['category']:<36} {r['text'][:60]}")
    time.sleep(a.delay)
