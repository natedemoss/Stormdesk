"""Reset the demo to a clean state before a rehearsal or the real thing.

    python scripts/reset_demo.py           # clear, then load the 10 demo reports
    python scripts/reset_demo.py --empty   # clear only (stream reports live during the demo)

Clears incidents, drafts and closures learned from reports. Keeps the synced cache:
roads, gazetteer, DriveNC closures, shelters, alerts. Refresh the console page afterwards.
The console's Reset button does the same, including inside the OpenShell sandbox.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk.config import DB_PATH  # noqa: E402
from stormdesk.demo import reset  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--empty", action="store_true", help="do not load the demo reports")
    a = ap.parse_args()
    r = reset(load_reports=not a.empty)
    print(f"cleared {r['cleared_reports']} reports, {r['cleared_drafts']} drafts, "
          f"{r['cleared_learned_closures']} learned closures in {DB_PATH}")
    if r["loaded_reports"]:
        print(f"loaded the {r['loaded_reports']} demo reports")
    print("Refresh the console page.")


if __name__ == "__main__":
    main()
