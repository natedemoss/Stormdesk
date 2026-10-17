"""OpenAI-style tool definitions sent to Lightning through vLLM."""


def _fn(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required,
                       "additionalProperties": False}}}


NUM = {"type": "number"}
LAT = {"type": "number", "minimum": 33.5, "maximum": 36.7, "description": "Latitude in NC"}
LON = {"type": "number", "minimum": -84.4, "maximum": -75.4, "description": "Longitude in NC"}

TOOLS = [
    _fn("geocode_location", "Convert a place name, road, or landmark from a report into coordinates "
        "(offline). Also returns where units start: the nearest fire station and ambulance base "
        "(stations), and the county staging point for every other unit.",
        {"text": {"type": "string"}}, ["text"]),
    _fn("get_road_closures", "List known road closures near a point. Includes unverified public reports.",
        {"lat": LAT, "lon": LON, "radius_km": {"type": "number", "default": 15}}, ["lat", "lon"]),
    _fn("report_closure", "Record a new road closure described in an incoming report (marked unverified).",
        {"road": {"type": "string"}, "lat": LAT, "lon": LON, "description": {"type": "string"}},
        ["road", "lat", "lon", "description"]),
    _fn("get_weather_alerts", "Active NWS weather alerts for a county.",
        {"county": {"type": "string", "description": "e.g. 'McDowell County'"}}, ["county"]),
    _fn("find_shelters", "Nearest open shelters with space left.",
        {"lat": LAT, "lon": LON, "needs_medical": {"type": "boolean"}, "has_pets": {"type": "boolean"},
         "limit": {"type": "integer", "default": 3}}, ["lat", "lon"]),
    _fn("plan_route", "Drivable route between two points that avoids all known closures.",
        {"from_lat": LAT, "from_lon": LON, "to_lat": LAT, "to_lon": LON},
        ["from_lat", "from_lon", "to_lat", "to_lon"]),
    _fn("draft_dispatch", "Create a DRAFT dispatch plan for human review. This does not send anything.",
        {"incident_id": {"type": "integer"},
         "unit_type": {"type": "string", "enum": ["swift_water_rescue", "ems", "fire", "high_water_vehicle",
                                                   "supply_drop", "welfare_check", "road_crew"]},
         "destination": {"type": "string"}, "route_summary": {"type": "string"},
         "notes": {"type": "string"}, "priority": {"type": "integer", "minimum": 1, "maximum": 5}},
        ["incident_id", "unit_type", "destination", "route_summary", "notes", "priority"]),
]

SCHEMAS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}

# McDowell's responder staging point (sample: Marion, NC). Other counties stage at their county
# seat (tools.staging_points); geocode_location returns the one to route from.
STAGING = {"name": "County EOC (sample)", "lat": 35.6840, "lon": -82.0093}
