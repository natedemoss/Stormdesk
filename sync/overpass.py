"""Shared OpenStreetMap (Overpass) download helpers for the sync scripts.

The public Overpass servers often throttle or fail (502, 500, timeouts), so each query is
retried on mirrors. osmnx caches every finished response in ./cache, so a rerun only
downloads what is still missing.
"""
import sys

OVERPASS_URLS = ["https://overpass-api.de/api", "https://overpass.private.coffee/api",
                 "https://overpass.kumi.systems/api", "https://maps.mail.ru/osm/tools/overpass/api"]


def county_query_shape(osm_name):
    """County outline for queries. Outlines are very detailed (Mitchell's is ~76 KB of
    coordinates) and go into the query, which some servers reject with HTTP 500. A slightly
    simplified outline padded by ~200 m is much smaller; the padding overlaps neighbors, so
    nothing at a county line is lost."""
    import osmnx as ox
    return ox.geocode_to_gdf(osm_name).geometry.iloc[0].simplify(0.0005).buffer(0.002)


def with_mirrors(what, fn):
    """Run fn() against each Overpass server until one works."""
    import osmnx as ox
    for url in OVERPASS_URLS:
        ox.settings.overpass_url = url
        try:
            print(f"{what} from {url} ...")
            return fn()
        except Exception as e:  # noqa: BLE001 - network errors vary (timeouts, 429, 500, 502)
            print(f"  failed: {type(e).__name__}: {str(e)[:120]}")
    sys.exit(f"could not get {what} from any Overpass server; try again later")
