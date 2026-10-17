"""Pull NCDOT road events from DriveNC into the local cache. Run while online.

NCDOT retired the old TIMS endpoint (eapps.ncdot.gov/services/traffic-prod) on
May 27, 2026. Its replacement is the DriveNC Events API, documented at
https://drivenc.gov/help/endpoint/event. It needs a free developer key:
sign up on drivenc.gov, then put DRIVENC_API_KEY=... in .env.

    python sync/sync_ncdot.py                    # every county in config.COUNTIES
    python sync/sync_ncdot.py --county McDowell  # just one (repeatable)
    python sync/sync_ncdot.py --all-nc           # the whole state

Field names below are the documented ones (ID, RoadwayName, Latitude, IsFullClosure, ...).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk import db  # noqa: E402
from stormdesk.config import CACHE_DIR, COUNTIES  # noqa: E402

URL = "https://www.drivenc.gov/api/v2/get/event"
# Damage words that matter for routing even when the event is not a full closure.
# ("closed" alone is too broad: "All Shoulders Closed" roadwork is everywhere.)
DAMAGE_WORDS = ("washed", "washout", "flood", "bridge out", "impassable", "rockslide", "mudslide", "slide")


def is_closure(ev: dict) -> bool:
    if ev.get("IsFullClosure") or ev.get("EventType") == "closures" or ev.get("MajorEvent"):
        return True
    text = f"{ev.get('Description', '')} {ev.get('LanesAffected', '')}".lower()
    return "all lanes closed" in text or any(w in text for w in DAMAGE_WORDS)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", action="append", help="county name, e.g. McDowell (default: config.COUNTIES)")
    ap.add_argument("--all-nc", action="store_true", help="keep closures from every county")
    a = ap.parse_args()
    wanted = None if a.all_nc else {c.lower() for c in (a.county or COUNTIES)}
    key = os.getenv("DRIVENC_API_KEY")
    if not key:
        sys.exit("Set DRIVENC_API_KEY (free developer key from drivenc.gov) in .env first.")

    r = requests.get(URL, params={"key": key, "format": "json"}, timeout=60)
    r.raise_for_status()
    events = r.json()
    (CACHE_DIR / "drivenc_raw.json").write_text(json.dumps(events, indent=1))

    conn = db.connect()
    db.init(conn)
    conn.execute("DELETE FROM closures WHERE source='ncdot'")
    kept = 0
    for ev in events:
        if wanted and (ev.get("County") or "").lower() not in wanted:
            continue
        if ev.get("Latitude") is None or ev.get("Longitude") is None or not is_closure(ev):
            continue
        desc = " ".join(str(ev.get("Description") or "").split())
        if ev.get("MajorEvent"):
            desc = f"[{ev['MajorEvent']}] {desc}"
        conn.execute(f"INSERT OR REPLACE INTO closures({db.CLOSURE_COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (f"ncdot-{ev['ID']}", ev.get("RoadwayName") or "", ev.get("County") or "",
                      float(ev["Latitude"]), float(ev["Longitude"]), desc, "ncdot", 1,
                      iso(ev.get("Reported")), db.now(),
                      ev.get("LatitudeSecondary"), ev.get("LongitudeSecondary")))
        kept += 1
    db.mark_synced(conn, "ncdot", f"{kept} closures of {len(events)} DriveNC events")
    conn.commit()
    print(f"saved {kept} closures (of {len(events)} DriveNC events)")


if __name__ == "__main__":
    main()
