"""Guard self-check, bad-data detection and the routing-down fallback. No model or database needed:
python tests/test_guard.py (or pytest)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stormdesk import scoring  # noqa: E402
from stormdesk.agent import DOWN_AFTER, MALFORMED, Guard, usable  # noqa: E402

STATION = {"name": "Old Fort Fire Department", "lat": 35.63, "lon": -82.18}
POLICE = {"name": "Marion Police Department", "lat": 35.68, "lon": -82.01}
GEO = {"found": True, "name": "Mill Creek Road", "county": "McDowell", "lat": 35.65, "lon": -82.15,
       "start_points": {"fire": STATION, "welfare_check": POLICE}}
DRAFT = {"incident_id": 1, "unit_type": "fire", "destination": "Mill Creek Road",
         "route_summary": "From Old Fort Fire Department", "notes": "-", "priority": 4}


def route(start):
    return {"from_lat": start["lat"], "from_lon": start["lon"], "to_lat": GEO["lat"], "to_lon": GEO["lon"]}


def guard_after(route_from):
    g = Guard()
    g.record("geocode_location", {"text": "Mill Creek Road"}, GEO)
    g.record("plan_route", route(route_from), {"ok": True, "distance_km": 4.2})
    return g


def test_draft_passes_when_route_starts_at_the_units_start_point():
    assert guard_after(STATION).check("draft_dispatch", DRAFT) is None


def test_self_check_blocks_route_from_the_wrong_start():
    g = guard_after(POLICE)  # routed from the police station, but drafting a fire unit
    err = g.check("draft_dispatch", DRAFT)
    assert err and "Old Fort Fire Department" in err and "plan_route" in err, err
    assert g.rule == "self_check"
    # re-routing from the right start fixes it
    g.record("plan_route", route(STATION), {"ok": True, "distance_km": 3.1})
    assert g.check("draft_dispatch", DRAFT) is None


def test_malformed_results_are_not_usable():
    for tool, bad in MALFORMED.items():
        assert not usable(tool, bad), tool
    assert usable("geocode_location", {"found": False, "query": "x"})  # a real "not found" answer
    assert usable("plan_route", {"ok": False, "reason": "No open route."})


def test_malformed_geocode_does_not_unlock_routing():
    g = Guard()
    g.record("geocode_location", {"text": "x"}, MALFORMED["geocode_location"])
    assert g.check("plan_route", route(STATION)), "routing allowed without real coordinates"


def test_draft_without_route_only_when_routing_is_down():
    g = Guard()
    g.record("geocode_location", {"text": "x"}, GEO)
    args = route(STATION)
    for n in range(DOWN_AFTER):
        assert g.check("draft_dispatch", DRAFT), f"draft allowed after {n} routing failures"
        g.record("plan_route", args, {"error": "ConnectionError: routing engine is down"})
    assert g.check("draft_dispatch", DRAFT) is None


def test_scoring_treats_faults_as_failures():
    trace = [{"tool": "geocode_location", "args": {}, "result": {**MALFORMED["geocode_location"], "_fault": True}}]
    assert scoring.score({"expect_tools": ["geocode_location"]}, trace, False)["tool_recall"] == 0


def test_fallback_scoring():
    dead = {"error": "ConnectionError: routing engine is down", "_fault": True, "_outage": True}
    case = scoring.for_outage({"expect_tools": ["geocode_location", "plan_route", "draft_dispatch"],
                               "expect_unit": ["fire"], "expect_station": True}, "plan_route")
    assert case["expect_tools"] == ["geocode_location", "draft_dispatch"] and "expect_station" not in case
    draft = {"tool": "draft_dispatch", "args": {**DRAFT, "route_summary": "Route unavailable: routing engine down."},
             "result": {"draft_id": 1}}
    trace = [{"tool": "plan_route", "args": {}, "result": dead}] * 3 + [draft]
    assert scoring.score(case, trace, True)["fallback_ok"] is True
    assert scoring.score(case, [{"tool": "plan_route", "args": {}, "result": dead}] * 4 + [draft], True)["fallback_ok"] is False
    silent = {**draft, "args": DRAFT}  # drafted but never says the route is missing
    assert scoring.score(case, trace[:3] + [silent], True)["fallback_ok"] is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
