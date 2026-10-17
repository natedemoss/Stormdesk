"""Build the offline gazetteer (places table) for geocode_location. Run while online,
after sync/build_road_graph.py.

  - every named road in the cached OSM road graph, at the middle of its longest stretch
  - towns, villages, hamlets and named localities from OpenStreetMap

Each entry is tagged with the county whose OSM boundary contains it.

    python sync/build_gazetteer.py                      # every county in config.COUNTIES
    python sync/build_gazetteer.py --county McDowell    # just one (repeatable)
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk import db  # noqa: E402
from stormdesk.config import COUNTIES, ROAD_GRAPH, osm_county  # noqa: E402
from sync.overpass import county_query_shape, with_mirrors  # noqa: E402

PLACE_TAGS = {"place": ["city", "town", "village", "hamlet", "suburb", "neighbourhood", "locality"]}


def road_points(G, county_of):
    """One point per (road name, county): the midpoint of that road's longest edge there.
    Keyed by county too, so "Main Street" in Marion and in Asheville stay separate."""
    best = defaultdict(lambda: (0, None))
    for u, v, d in G.edges(data=True):
        names = d.get("name")
        if not names:
            continue
        a, b = G.nodes[u], G.nodes[v]
        mid = ((a["y"] + b["y"]) / 2, (a["x"] + b["x"]) / 2)
        county = county_of(*mid)
        if not county:
            continue
        for name in names if isinstance(names, list) else [names]:
            if d.get("length", 0) > best[(name, county)][0]:
                best[(name, county)] = (d.get("length", 0), mid)
    return {k: p for k, (_, p) in best.items() if p}


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

    G = ox.load_graphml(ROAD_GRAPH)
    rows = [(name, county, lat, lon) for (name, county), (lat, lon) in road_points(G, county_of).items()]
    n_roads = len(rows)
    seen = set()
    for county in counties:
        shape = county_query_shape(osm_county(county))
        places = with_mirrors(f"{county} County places",
                              lambda: ox.features_from_polygon(shape, tags=PLACE_TAGS))
        for _, row in places[places["name"].notna()].iterrows():
            c = row.geometry.centroid
            # the query outline is padded, so tag by the real boundary and skip repeats
            if (where := county_of(c.y, c.x)) and (row["name"], where) not in seen:
                seen.add((row["name"], where))
                rows.append((row["name"], where, c.y, c.x))

    conn = db.connect()
    db.init(conn)
    conn.execute("DELETE FROM places")
    conn.executemany("INSERT INTO places VALUES(?,?,?,?)", rows)
    db.mark_synced(conn, "gazetteer", f"{n_roads} roads, {len(rows) - n_roads} places ({', '.join(counties)})")
    conn.commit()
    print(f"saved {n_roads} named roads and {len(rows) - n_roads} places for {', '.join(counties)}")


if __name__ == "__main__":
    main()
