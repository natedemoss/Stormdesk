"""Local SQLite store. Everything the agent reads lives here so it works offline.

Run:  python -m stormdesk.db --init --load-samples
"""
import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone

from stormdesk.config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS closures (
    id TEXT PRIMARY KEY,
    road TEXT,
    county TEXT,
    lat REAL, lon REAL,
    description TEXT,
    source TEXT,            -- 'ncdot' | 'public_report' | 'sample'
    verified INTEGER,       -- 1 = official, 0 = reported by public
    reported_at TEXT,
    synced_at TEXT,
    lat2 REAL, lon2 REAL    -- optional far end: the closure covers the stretch between the two points
);
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    event TEXT, severity TEXT, area TEXT, headline TEXT,
    onset TEXT, expires TEXT, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS shelters (
    id TEXT PRIMARY KEY,
    name TEXT, county TEXT, lat REAL, lon REAL,
    capacity INTEGER, occupancy INTEGER,
    accepts_pets INTEGER, medical INTEGER
);
CREATE TABLE IF NOT EXISTS places (      -- offline gazetteer
    name TEXT, county TEXT, lat REAL, lon REAL
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text TEXT, channel TEXT,
    category TEXT, urgency INTEGER, location_text TEXT,
    lat REAL, lon REAL,
    status TEXT DEFAULT 'new',  -- new | drafted | approved | rejected
    created_at TEXT,
    flag TEXT                   -- set when a triage safety rule overrode the model's ranking
);
CREATE TABLE IF NOT EXISTS dispatch_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER, plan_json TEXT, trace_json TEXT,
    status TEXT DEFAULT 'pending_review',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS sync_log (
    source TEXT PRIMARY KEY, last_success TEXT, note TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)  # wait out parallel writers
    conn.row_factory = sqlite3.Row
    return conn


CLOSURE_COLS = "id, road, county, lat, lon, description, source, verified, reported_at, synced_at, lat2, lon2"


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(closures)")}
    for col in ("lat2", "lon2"):  # databases created before stretch closures existed
        if col not in cols:
            conn.execute(f"ALTER TABLE closures ADD COLUMN {col} REAL")
    if "flag" not in {r[1] for r in conn.execute("PRAGMA table_info(incidents)")}:
        conn.execute("ALTER TABLE incidents ADD COLUMN flag TEXT")
    conn.commit()


def mark_synced(conn, source: str, note: str = "") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO sync_log(source,last_success,note) VALUES(?,?,?)",
        (source, now(), note),
    )
    conn.commit()


def last_synced(conn, source: str):
    row = conn.execute("SELECT last_success FROM sync_log WHERE source=?", (source,)).fetchone()
    return row["last_success"] if row else None


def load_samples(conn) -> None:
    with open(DATA_DIR / "shelters_sample.csv", newline="") as f:
        for r in csv.DictReader(f):
            conn.execute(
                "INSERT OR REPLACE INTO shelters VALUES(?,?,?,?,?,?,?,?,?)",
                (r["id"], r["name"], r["county"], float(r["lat"]), float(r["lon"]),
                 int(r["capacity"]), int(r["occupancy"]), int(r["accepts_pets"]), int(r["medical"])),
            )
    # Sample places only fill an empty gazetteer, so they never overwrite sync/build_gazetteer.py output.
    has_places = conn.execute("SELECT 1 FROM places LIMIT 1").fetchone()
    with open(DATA_DIR / "places_sample.csv", newline="") as f:
        for r in [] if has_places else csv.DictReader(f):
            conn.execute("INSERT INTO places VALUES(?,?,?,?)",
                         (r["name"], r["county"], float(r["lat"]), float(r["lon"])))
    with open(DATA_DIR / "closures_sample.json") as f:
        for c in json.load(f):
            conn.execute(
                f"INSERT OR REPLACE INTO closures({CLOSURE_COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (c["id"], c["road"], c["county"], c["lat"], c["lon"], c["description"],
                 "sample", 1, c.get("reported_at", now()), now(), c.get("lat2"), c.get("lon2")),
            )
    mark_synced(conn, "sample", "loaded sample data")
    conn.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--load-samples", action="store_true")
    a = ap.parse_args()
    c = connect()
    if a.init:
        init(c)
        print(f"initialized {DB_PATH}")
    if a.load_samples:
        load_samples(c)
        print("loaded sample shelters, places, closures")
