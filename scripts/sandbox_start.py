"""Entry point inside the OpenShell sandbox.

Seeds the writable DB in /tmp from the read-only cache in /app/data, then starts
the console on 127.0.0.1:8080. Reach it from the host with:
    openshell forward start 8080 stormdesk
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk import db  # noqa: E402
from stormdesk.config import DATA_DIR, DB_PATH  # noqa: E402

baked = DATA_DIR / "stormdesk.db"  # produced by the sync scripts before `docker build`
if not DB_PATH.exists():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if baked.exists():
        shutil.copy(baked, DB_PATH)
        print(f"seeded {DB_PATH} from {baked}")
    else:
        c = db.connect()
        db.init(c)
        db.load_samples(c)
        print(f"no synced cache found, loaded SAMPLE data into {DB_PATH}")

import uvicorn  # noqa: E402

from ui.server import app  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning")
