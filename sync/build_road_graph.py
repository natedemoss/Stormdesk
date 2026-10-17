"""Download the drivable road network for the configured counties, save it for offline routing.

    python sync/build_road_graph.py                      # every county in config.COUNTIES
    python sync/build_road_graph.py --county McDowell    # just one (repeatable)

One county per request: a single query for several counties is too large for Overpass
(HTTP 413). truncate_by_edge keeps roads that cross a county line, and shared OSM node ids
join the pieces. For a fully offline, statewide setup, download the NC extract from
https://download.geofabrik.de/north-america/us/north-carolina.html instead.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk.config import COUNTIES, ROAD_GRAPH, osm_county  # noqa: E402
from sync.overpass import county_query_shape, with_mirrors  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", action="append", help="county name, e.g. McDowell (default: config.COUNTIES)")
    a = ap.parse_args()
    import networkx as nx
    import osmnx as ox
    counties = a.county or COUNTIES
    graphs = []
    for c in counties:
        shape = county_query_shape(osm_county(c))
        graphs.append(with_mirrors(f"{c} County roads", lambda: ox.graph_from_polygon(
            shape, network_type="drive", truncate_by_edge=True)))
    G = nx.compose_all(graphs)
    ROAD_GRAPH.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, ROAD_GRAPH)
    print(f"saved {len(G.nodes)} nodes / {len(G.edges)} edges to {ROAD_GRAPH}")


if __name__ == "__main__":
    main()
