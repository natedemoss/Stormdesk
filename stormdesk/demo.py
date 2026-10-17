"""Reset the demo to a clean state. Used by scripts/reset_demo.py and the console's Reset button.

Clears incidents, drafts and closures learned from reports. Keeps the synced cache:
roads, gazetteer, DriveNC closures, shelters, alerts.
"""
import json

from stormdesk import db
from stormdesk.config import DATA_DIR
from stormdesk.triage import ingest

DEMO_REPORTS = DATA_DIR / "demo_reports.jsonl"   # sample texts, calls and posts written for the demo
HELENE_REPORTS = DATA_DIR / "helene_lsr.jsonl"    # real NWS storm reports from Helene (sync/fetch_helene_reports.py)


def reset(load_reports: bool = True) -> dict:
    conn = db.connect()
    db.init(conn)
    drafts = conn.execute("DELETE FROM dispatch_queue").rowcount
    incidents = conn.execute("DELETE FROM incidents").rowcount
    learned = conn.execute("DELETE FROM closures WHERE source='public_report'").rowcount
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('incidents', 'dispatch_queue')")  # ids restart at 1
    conn.commit()
    loaded = 0
    if load_reports:
        for path in (HELENE_REPORTS, DEMO_REPORTS):
            if not path.exists():
                continue
            for line in open(path, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    ingest(r["text"], r.get("channel", "sms"))
                    loaded += 1
    return {"cleared_reports": incidents, "cleared_drafts": drafts,
            "cleared_learned_closures": learned, "loaded_reports": loaded}
