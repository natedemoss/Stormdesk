"""Pull shelters for the configured counties into the local cache. Run while online.

Two public sources, no key needed:
  1. FEMA Open Shelters (ESF#6, synced with the American Red Cross): shelters that
     are OPEN right now, with capacity, occupancy and pet info. Empty when no
     disaster is active in NC.
  2. NC OneMap "Potential Emergency Shelters" (NC CGIA): buildings that may be used
     as shelters. Locations only; capacity is usually blank, so it stays unknown.

Contact names and phone numbers in the NC layer are not stored.

    python sync/sync_shelters.py                    # every county in config.COUNTIES
    python sync/sync_shelters.py --county McDowell  # just one (repeatable)
"""
import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk import db  # noqa: E402
from stormdesk.config import COUNTIES  # noqa: E402

FEMA = "https://gis.fema.gov/arcgis/rest/services/NSS/OpenShelters/FeatureServer/0/query"
NC_ONEMAP = ("https://services.nconemap.gov/secure/rest/services/"
             "NC1Map_Emergency_Law_Enforcement/FeatureServer/2/query")


def arcgis(url, where, fields):
    r = requests.get(url, params={"where": where, "outFields": fields, "outSR": 4326, "f": "json"}, timeout=60)
    r.raise_for_status()
    return r.json().get("features", [])


def to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", action="append", help="county name, e.g. McDowell (default: config.COUNTIES)")
    a = ap.parse_args()
    counties = a.county or COUNTIES
    conn = db.connect()
    db.init(conn)
    conn.execute("DELETE FROM shelters WHERE id LIKE 'fema-%' OR id LIKE 'nc-%'")

    # FEMA has no county field; filter NC open shelters, keep all (they are few).
    fema = arcgis(FEMA, "state='NC' AND shelter_status='OPEN'",
                  "shelter_id,shelter_name,city,evacuation_capacity,total_population,"
                  "pet_accommodations_code,latitude,longitude")
    for f in fema:
        p = f["attributes"]
        if p.get("latitude") is None:
            continue
        pets = str(p.get("pet_accommodations_code") or "").strip().upper() not in ("", "NONE", "NO")
        conn.execute("INSERT OR REPLACE INTO shelters VALUES(?,?,?,?,?,?,?,?,?)",
                     (f"fema-{p['shelter_id']}", f"{p['shelter_name']} ({p.get('city') or ''})", "",
                      p["latitude"], p["longitude"], to_int(p.get("evacuation_capacity")),
                      to_int(p.get("total_population")) or 0, int(pets), 0))

    by_upper = {c.upper(): c for c in counties}  # the layer stores MCDOWELL; keep McDowell
    names = ", ".join(f"'{c}'" for c in by_upper)
    nc = arcgis(NC_ONEMAP, f"county IN ({names})", "objectid,bldg_name,bldg_type,city,county,capacity")
    for f in nc:
        p, g = f["attributes"], f.get("geometry") or {}
        if "x" not in g:
            continue
        name = f"{p['bldg_name'].title()} (potential)"
        conn.execute("INSERT OR REPLACE INTO shelters VALUES(?,?,?,?,?,?,?,?,?)",
                     (f"nc-{p['objectid']}", name, by_upper.get((p.get("county") or "").upper(), ""), g["y"], g["x"],
                      to_int(p.get("capacity")), 0, 0, 0))

    db.mark_synced(conn, "shelters", f"{len(fema)} FEMA open (NC), {len(nc)} NC OneMap potential ({', '.join(counties)})")
    conn.commit()
    print(f"saved {len(fema)} FEMA open shelters in NC and {len(nc)} potential shelters in {', '.join(counties)}")


if __name__ == "__main__":
    main()
