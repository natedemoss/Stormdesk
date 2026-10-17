"""Tool implementations. Every tool reads the local cache only, so the agent
keeps working when the network is down. Each returns a JSON-serializable dict.
"""
import json
import math
import re
import uuid
from functools import lru_cache

from stormdesk import db
from stormdesk.config import COUNTIES, COUNTY_SEATS, ROAD_GRAPH
from stormdesk.tool_schemas import STAGING

CLOSURE_RADIUS_M = 150  # road nodes this close to a closure are treated as blocked
KNOWN_SPACE_KM = 15  # a shelter with confirmed space is preferred over closer ones within this distance
_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = db.connect()
        db.init(_conn)
    return _conn


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _age_note(source: str) -> str:
    ts = db.last_synced(conn(), source)
    return f"{source} data last synced {ts} UTC" if ts else f"{source} data never synced"


# ---------------------------------------------------------------- geocode
ABBREV = {"rd": "road", "st": "street", "hwy": "highway", "dr": "drive", "ln": "lane", "ave": "avenue",
           "mtn": "mountain", "mt": "mount", "pkwy": "parkway", "blvd": "boulevard", "ct": "court",
           "cir": "circle", "n": "north", "s": "south", "e": "east", "w": "west"}
GENERIC = {"road", "street", "highway", "drive", "lane", "avenue", "the", "of", "old", "new", "north",
           "south", "east", "west", "court", "circle", "trail", "way", "route", "us", "nc"}


def _norm(s: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()
    return " ".join(ABBREV.get(w, w) for w in words)


def _match_score(name: str, q: str, q_words: set) -> float:
    # exact > whole-phrase match (longer names win ties, so "old fort road" beats "old fort").
    # Both strings are normalized to single-spaced words, so padding with spaces gives whole-word
    # matching without a regex per row (17,000 rows for six counties).
    if name == q:
        return 2
    if f" {name} " in f" {q} " or f" {q} " in f" {name} ":
        return 1 + len(name) / 100
    # partial: needs two distinctive words, so "water" alone never means Water Street
    key = set(name.split()) - GENERIC
    hit = key & q_words
    return len(hit) / len(key) * 0.9 if len(hit) >= 2 else 0


_gaz_cache = {}


def _gazetteer():
    """(normalized name, row) for every place, plus the road names in NCDOT closures (DriveNC
    spells some roads differently from OSM: "Nanneytown Rd" vs "Nannytown Road").
    Rebuilt when either table changes."""
    n = conn().execute("SELECT (SELECT COUNT(*) FROM places), (SELECT MAX(rowid) FROM places), "
                       "(SELECT COUNT(*) FROM closures WHERE source='ncdot')").fetchone()
    key = tuple(n)
    if _gaz_cache.get("key") != key:
        rows = list(conn().execute("SELECT * FROM places").fetchall())
        rows += [{"name": r["road"], "county": f"{r['county']} County" if r["county"] else "",
                  "lat": r["lat"], "lon": r["lon"]}
                 for r in conn().execute("SELECT road, county, lat, lon FROM closures WHERE source='ncdot'")]
        _gaz_cache["rows"] = [(nm, r) for r in rows if (nm := _norm(r["name"]))]
        _gaz_cache["key"] = key
    return _gaz_cache["rows"]


def _close(a: str, b: str) -> bool:
    from difflib import SequenceMatcher
    return len(a) >= 6 and len(b) >= 6 and a[0] == b[0] and SequenceMatcher(None, a, b).ratio() >= 0.85


def _fuzzy_match(name: str, q_words: list) -> bool:
    """The name appears in the report as consecutive words, with at least one close misspelling
    of a long distinctive word ("nanneytown road" for "nannytown road"). Generic words must match."""
    words = name.split()
    if not any(w not in GENERIC for w in words):
        return False
    for i in range(len(q_words) - len(words) + 1):
        window = q_words[i:i + len(words)]
        exact = [w == qw for w, qw in zip(words, window)]
        if all(e or (w not in GENERIC and _close(w, qw)) for w, qw, e in zip(words, window, exact)) \
                and not all(exact):
            return True
    return False


def geocode_location(text: str) -> dict:
    """Offline fuzzy lookup in the local gazetteer (places table)."""
    q = _norm(text)
    q_words = set(q.split())
    scored = []
    for name, r in _gazetteer():
        # cheap prefilter: any match needs at least one shared word
        if q_words.isdisjoint(name.split()):
            continue
        if (s := _match_score(name, q, q_words)) >= 0.5:
            scored.append((s, name, r))
    fuzzy = False
    if not scored:  # nothing spelled the same: allow close misspellings of long words
        q_list = q.split()
        scored = [(0.8, name, r) for name, r in _gazetteer()
                  if len(name.split()) <= len(q_list) and _fuzzy_match(name, q_list)]
        fuzzy = bool(scored)
    if not scored:
        return {"found": False, "query": text, "hint": "Ask the reporter for a nearby landmark or road."}
    # Same road name in several counties ("Main Street"): prefer the county the report points
    # to, through a "<name> county" phrase or another place it mentions (a town in that county).
    best_s, best_name, best = max(scored, key=lambda t: t[0])
    tied = [r for s, n, r in scored if n == best_name and s == best_s]
    # other places actually named in the report (a town), and any "<name> county" phrase
    named = [(n, r) for s, n, r in scored if n != best_name and f" {n} " in f" {q} "]
    context = {r["county"].lower() for n, r in named}
    context |= {f"{c} county".lower() for c in re.findall(r"\b(\w+) county\b", text, re.I)}
    in_context = [r for r in tied if r["county"].lower() in context]
    note = ""
    if in_context:
        best = in_context[0]
    elif named and len({r["county"] for r in tied}) > 1:
        # "Main Street in Burnsville" but Burnsville's county has no Main Street: use the town
        # rather than a same-named road in another county
        town_name, best = max(named, key=lambda t: len(t[0]))
        note = (f"No '{tied[0]['name']}' found in {best['county']}; located the report at {best['name']}. "
                "Ask the reporter for a nearby landmark.")
    else:
        best = tied[0]
        if len({r["county"] for r in tied}) > 1:
            note = (f"'{best['name']}' exists in {len(tied)} counties; picked {best['county']}. "
                    "Ask the reporter for the town if unsure.")
    out = {"found": True, "name": best["name"], "county": best["county"],
           "lat": best["lat"], "lon": best["lon"], "confidence": round(min(best_s, 1.0), 2)}
    if fuzzy:
        note = (f"The report's spelling differs from '{best['name']}'; confirm the location. " + note).strip()
    if note:
        out["note"] = note
    out["staging"] = staging_for(best["county"], best["lat"], best["lon"])
    return out


# ---------------------------------------------------------------- staging
@lru_cache(maxsize=1)
def staging_points() -> tuple:
    """One responder staging point per configured county: McDowell keeps the sample EOC point,
    the others use their county seat's coordinates from the OSM gazetteer (never invented)."""
    pts = []
    for county in COUNTIES:
        if county == "McDowell":
            pts.append({**STAGING, "county": "McDowell County"})
            continue
        seat = COUNTY_SEATS.get(county)
        r = seat and conn().execute("SELECT lat, lon FROM places WHERE name=? AND county=?",
                                    (seat, f"{county} County")).fetchone()
        if r:
            pts.append({"name": f"{county} staging ({seat})", "county": f"{county} County",
                        "lat": r["lat"], "lon": r["lon"]})
    return tuple(pts)


def staging_for(county: str, lat: float, lon: float) -> dict:
    """The staging point in the incident's county, else the nearest one."""
    pts = staging_points() or ({**STAGING, "county": "McDowell County"},)
    same = [p for p in pts if p["county"] == county]
    p = same[0] if same else min(pts, key=lambda p: haversine_m(lat, lon, p["lat"], p["lon"]))
    return {"name": p["name"], "lat": p["lat"], "lon": p["lon"]}


# ---------------------------------------------------------------- closures
def get_road_closures(lat: float, lon: float, radius_km: float = 15) -> dict:
    out = []
    for r in conn().execute("SELECT * FROM closures").fetchall():
        d = haversine_m(lat, lon, r["lat"], r["lon"]) / 1000
        if d <= radius_km:
            out.append({"road": r["road"], "description": r["description"],
                        "distance_km": round(d, 1), "verified": bool(r["verified"]),
                        "source": r["source"], "reported_at": r["reported_at"]})
    out.sort(key=lambda x: x["distance_km"])
    return {"closures": out, "freshness": _age_note("ncdot")}


def report_closure(road: str, lat: float, lon: float, description: str) -> dict:
    """Closure learned from an incoming public report. Marked unverified."""
    cid = f"pub-{uuid.uuid4().hex[:8]}"
    c = conn()
    c.execute(f"INSERT INTO closures({db.CLOSURE_COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (cid, road, "", lat, lon, description, "public_report", 0, db.now(), db.now(), None, None))
    c.commit()
    return {"added": cid, "verified": False}


# ---------------------------------------------------------------- weather
def get_weather_alerts(county: str) -> dict:
    rows = conn().execute(
        "SELECT event, severity, headline, expires FROM alerts WHERE area LIKE ?",
        (f"%{county.replace(' County', '')}%",),
    ).fetchall()
    return {"alerts": [dict(r) for r in rows], "freshness": _age_note("noaa")}


# ---------------------------------------------------------------- shelters
def find_shelters(lat: float, lon: float, needs_medical: bool = False,
                  has_pets: bool = False, limit: int = 3) -> dict:
    """Open shelters with known space first, then potential shelters (capacity unknown)."""
    out = []
    for r in conn().execute("SELECT * FROM shelters").fetchall():
        space = None if r["capacity"] is None else r["capacity"] - (r["occupancy"] or 0)
        if (space is not None and space <= 0) or (needs_medical and not r["medical"]) \
                or (has_pets and not r["accepts_pets"]):
            continue
        out.append({"id": r["id"], "name": r["name"], "space_left": space,
                    "lat": r["lat"], "lon": r["lon"],
                    "distance_km": round(haversine_m(lat, lon, r["lat"], r["lon"]) / 1000, 1)})
    # Known open space wins only nearby; across six counties a shelter with space 30 km away
    # should not beat a closer potential shelter.
    out.sort(key=lambda x: (not (x["space_left"] is not None and x["distance_km"] <= KNOWN_SPACE_KM),
                            x["distance_km"]))
    note = "" if any(s["space_left"] is not None for s in out) else \
        "No shelter with confirmed open space; listed sites are potential shelters, capacity unknown."
    return {"shelters": out[:limit], **({"note": note} if note else {})}


# ---------------------------------------------------------------- routing
@lru_cache(maxsize=1)
def _graph():
    if not ROAD_GRAPH.exists():
        return None
    import osmnx as ox
    return ox.load_graphml(ROAD_GRAPH)


@lru_cache(maxsize=1)
def _node_index():
    """Node ids and coordinates as arrays, so nearest-node and closure checks are vectorized
    (the six-county graph has ~39,000 nodes; plain Python loops took seconds per route)."""
    import numpy as np
    G = _graph()
    ids = list(G.nodes)
    lat = np.array([G.nodes[n]["y"] for n in ids])
    lon = np.array([G.nodes[n]["x"] for n in ids])
    return ids, lat, lon


def _nearest_node(G, lat, lon, exclude=frozenset()):
    import numpy as np
    ids, la, lo = _node_index()
    k = math.cos(math.radians(lat))
    d = ((la - lat) * 110540) ** 2 + ((lo - lon) * k * 111320) ** 2
    for i in np.argsort(d)[:len(exclude) + 1]:
        if ids[i] not in exclude:
            return ids[i]
    return min((n for n in G.nodes if n not in exclude),
               key=lambda n: haversine_m(lat, lon, G.nodes[n]["y"], G.nodes[n]["x"]))


def _blocked_nodes(closures) -> set:
    """Nodes within CLOSURE_RADIUS_M of a closure. A bounding-box prefilter keeps the exact
    distance check to the few nodes near each closure."""
    import numpy as np
    ids, la, lo = _node_index()
    pad = CLOSURE_RADIUS_M / 100000 * 1.5  # degrees, generous
    out = set()
    for c in closures:
        lats = [c["lat"]] + ([c["lat2"]] if c["lat2"] is not None else [])
        lons = [c["lon"]] + ([c["lon2"]] if c["lon2"] is not None else [])
        near = np.nonzero((la >= min(lats) - pad) & (la <= max(lats) + pad) &
                          (lo >= min(lons) - pad * 1.3) & (lo <= max(lons) + pad * 1.3))[0]
        out.update(ids[i] for i in near if _closure_dist_m(c, la[i], lo[i]) < CLOSURE_RADIUS_M)
    return out


def _closure_dist_m(c, lat, lon) -> float:
    """Distance from a point to a closure: a point, or the stretch between (lat, lon) and (lat2, lon2)."""
    if c["lat2"] is None or c["lon2"] is None:
        return haversine_m(c["lat"], c["lon"], lat, lon)
    k = math.cos(math.radians(lat))  # local flat projection, fine at county scale
    ax, ay = (c["lon"] - lon) * k * 111320, (c["lat"] - lat) * 110540
    bx, by = (c["lon2"] - lon) * k * 111320, (c["lat2"] - lat) * 110540
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(ax + t * dx, ay + t * dy)


def _edge_coords(G, u, v):
    """[lon, lat] points along edge u->v, using the OSM road shape when present."""
    data = min(G.get_edge_data(u, v).values(), key=lambda e: e.get("length", 0))
    a, b = G.nodes[u], G.nodes[v]
    geom = data.get("geometry")
    if geom is None:
        return [[a["x"], a["y"]], [b["x"], b["y"]]]
    pts = [[x, y] for x, y in geom.coords]
    if haversine_m(a["y"], a["x"], pts[0][1], pts[0][0]) > haversine_m(a["y"], a["x"], pts[-1][1], pts[-1][0]):
        pts.reverse()
    return pts


def _path_coords(G, path):
    out = []
    for u, v in zip(path, path[1:]):
        seg = _edge_coords(G, u, v)
        out.extend(seg if not out else seg[1:])
    return out


def _path_m(G, path):
    return sum(min(e.get("length", 0) for e in G.get_edge_data(u, v).values())
               for u, v in zip(path, path[1:]))


def plan_route(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> dict:
    """Shortest drivable route that avoids every known closure.

    Keys starting with "_" are route geometry for the map. The agent strips them
    before the result goes back to the model.
    """
    G = _graph()
    closures = conn().execute("SELECT road, lat, lon, lat2, lon2 FROM closures").fetchall()
    if G is None:
        km = haversine_m(from_lat, from_lon, to_lat, to_lon) / 1000
        return {"ok": True, "mode": "straight_line_fallback", "distance_km": round(km, 1),
                "note": "Road graph not built. Run sync/build_road_graph.py.",
                "_path": [[from_lon, from_lat], [to_lon, to_lat]]}
    import networkx as nx
    blocked = _blocked_nodes(closures)
    # The route we would take with no closures, to show what the detour avoided.
    try:
        direct = nx.shortest_path(G, _nearest_node(G, from_lat, from_lon),
                                  _nearest_node(G, to_lat, to_lon), weight="length")
    except nx.NetworkXNoPath:
        direct = None
    direct_blocked = bool(direct) and any(n in blocked for n in direct)
    blocked_extra = {"_blocked_path": _path_coords(G, direct)} if direct_blocked else {}

    H = G.subgraph([n for n in G.nodes if n not in blocked])
    a, b = _nearest_node(H, from_lat, from_lon, blocked), _nearest_node(H, to_lat, to_lon, blocked)
    try:
        path = nx.shortest_path(H, a, b, weight="length")
    except nx.NetworkXNoPath:
        return {"ok": False, "reason": "No open route. All paths cross a closure.",
                "blocked_nodes": len(blocked), **blocked_extra}
    meters = _path_m(H, path)
    reroute = {"rerouted": direct_blocked}
    if direct_blocked:
        reroute["direct_route_km"] = round(_path_m(G, direct) / 1000, 1)
    roads = []
    for u, v in zip(path, path[1:]):
        name = next(iter(H.get_edge_data(u, v).values())).get("name")
        name = name[0] if isinstance(name, list) else name
        if name and (not roads or roads[-1] != name):
            roads.append(name)
    return {"ok": True, "mode": "road_graph", "distance_km": round(meters / 1000, 1),
            "via": roads[:12], "closures_avoided": len(closures), **reroute,
            "_path": _path_coords(H, path), **blocked_extra}


# ---------------------------------------------------------------- dispatch
def draft_dispatch(incident_id: int, unit_type: str, destination: str,
                   route_summary: str, notes: str, priority: int) -> dict:
    """Writes a DRAFT to the review queue. There is no send function on purpose."""
    plan = {"unit_type": unit_type, "destination": destination, "route": route_summary,
            "notes": notes, "priority": priority}
    c = conn()
    cur = c.execute("INSERT INTO dispatch_queue(incident_id, plan_json, trace_json, created_at) "
                    "VALUES(?,?,?,?)", (incident_id, json.dumps(plan), "[]", db.now()))
    c.execute("UPDATE incidents SET status='drafted' WHERE id=?", (incident_id,))
    c.commit()
    return {"draft_id": cur.lastrowid, "status": "pending_human_review"}


REGISTRY = {
    "geocode_location": geocode_location,
    "get_road_closures": get_road_closures,
    "report_closure": report_closure,
    "get_weather_alerts": get_weather_alerts,
    "find_shelters": find_shelters,
    "plan_route": plan_route,
    "draft_dispatch": draft_dispatch,
}
