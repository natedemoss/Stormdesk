"""Refresh every offline cache for the configured counties, in the right order. Run while online.

    python sync/sync_all.py                 # everything (roads and gazetteer take a few minutes)
    python sync/sync_all.py --quick         # only what changes daily: closures, alerts, shelters

Counties come from config.COUNTIES (STORMDESK_COUNTIES in .env). DriveNC closures need
DRIVENC_API_KEY in .env; without it that step is skipped.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from stormdesk.config import COUNTIES  # noqa: E402

FULL = ["build_road_graph.py", "build_gazetteer.py"]
DAILY = ["sync_ncdot.py", "sync_noaa.py", "sync_shelters.py"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip the road graph and gazetteer")
    a = ap.parse_args()
    print(f"counties: {', '.join(COUNTIES)}")
    failed = []
    for script in ([] if a.quick else FULL) + DAILY:
        if script == "sync_ncdot.py" and not os.getenv("DRIVENC_API_KEY"):
            print("== sync_ncdot.py skipped: no DRIVENC_API_KEY in .env")
            continue
        print(f"== {script}")
        if subprocess.run([sys.executable, str(ROOT / "sync" / script)], cwd=ROOT).returncode:
            failed.append(script)
    if failed:
        sys.exit(f"failed: {', '.join(failed)}")
    print("all caches refreshed")


if __name__ == "__main__":
    main()
