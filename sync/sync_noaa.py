"""Pull active NWS alerts for North Carolina into the local cache."""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk import db  # noqa: E402
from stormdesk.config import NWS_USER_AGENT  # noqa: E402

URL = "https://api.weather.gov/alerts/active"


def main(area: str = "NC"):
    r = requests.get(URL, params={"area": area}, timeout=30,
                     headers={"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"})
    r.raise_for_status()
    feats = r.json().get("features", [])
    conn = db.connect()
    db.init(conn)
    conn.execute("DELETE FROM alerts")
    for f in feats:
        p = f["properties"]
        conn.execute("INSERT OR REPLACE INTO alerts VALUES(?,?,?,?,?,?,?,?)",
                     (p["id"], p.get("event"), p.get("severity"), p.get("areaDesc"),
                      p.get("headline"), p.get("onset"), p.get("expires"), db.now()))
    db.mark_synced(conn, "noaa", f"{len(feats)} alerts")
    conn.commit()
    print(f"saved {len(feats)} alerts for {area}")


if __name__ == "__main__":
    main(*sys.argv[1:])
