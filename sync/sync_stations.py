"""Fire stations, ambulance bases and police/sheriff stations from OpenStreetMap, so each unit
routes from where it would really start instead of the county staging point. Run while online.

  - fire:   amenity=fire_station          (fire, swift-water rescue, high-water vehicles)
  - ems:    emergency=ambulance_station   (EMS)
  - police: amenity=police                (welfare checks)
Each station is tagged with the county whose OSM boundary contains it.

    python sync/sync_stations.py                      # every county in config.COUNTIES
    python sync/sync_stations.py --county McDowell    # just one (repeatable)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk import db  # noqa: E402
from stormdesk.config import COUNTIES, osm_county  # noqa: E402
from sync.overpass import county_query_shape, with_mirrors  # noqa: E402

TAGS = {"amenity": ["fire_station", "police"], "emergency": "ambulance_station"}
DEFAULT_NAME = {"fire": "Fire station", "ems": "Ambulance base", "police": "Police station"}


def kind_of(row):
    if row.get("amenity") == "fire_station":
        return "fire"
    if row.get("emergency") == "ambulance_station":
        return "ems"
    if row.get("amenity") == "police":
        return "police"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", action="append", help="county name, e.g. McDowell (default: config.COUNTIES)")
    a = ap.parse_args()
    import osmnx as ox
    from shapely.geometry import Point
    from shapely.prepared import prep
    counties = a.county or COUNTIES

    bounds = ox.geocode_to_gdf([osm_county(c) for c in counties])
    shapes = [(f"{c} County", prep(geom)) for c, geom in zip(counties, bounds.geometry)]

    def county_of(lat, lon):
        p = Point(lon, lat)
        return next((name for name, shape in shapes if shape.contains(p)), None)

    rows, seen = [], set()
    for county in counties:
        shape = county_query_shape(osm_county(county))
        found = with_mirrors(f"{county} County stations", lambda: ox.features_from_polygon(shape, tags=TAGS))
        for idx, row in found.iterrows():
            kind = kind_of(row)
            c = row.geometry.centroid
            where = county_of(c.y, c.x)  # the query outline is padded: tag by the real boundary
            osm_id = f"{idx[0]}/{idx[1]}" if isinstance(idx, tuple) else str(idx)
            if not kind or not where or osm_id in seen:
                continue
            seen.add(osm_id)
            name = row.get("name")
            if not isinstance(name, str) or not name.strip():
                name = f"{DEFAULT_NAME[kind]} ({where})"
            rows.append((f"osm-{osm_id}", name.strip(), kind, where, c.y, c.x))

    conn = db.connect()
    db.init(conn)
    conn.execute("DELETE FROM stations")
    conn.executemany("INSERT INTO stations VALUES(?,?,?,?,?,?)", rows)
    n = {k: sum(r[2] == k for r in rows) for k in DEFAULT_NAME}
    note = f"{n['fire']} fire stations, {n['ems']} ambulance bases, {n['police']} police/sheriff stations"
    db.mark_synced(conn, "stations", note)
    conn.commit()
    print(f"saved {note} for {', '.join(counties)}")


if __name__ == "__main__":
    main()
