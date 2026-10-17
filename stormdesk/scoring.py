"""Scoring rules for one agent run against one eval case.

Shared by eval/run_eval.py and the NeMo Gym environment (gym/stormdesk_dispatch), so both
report the same numbers. A case is a line of eval/incidents.jsonl; a trace is a list of
{"tool", "args", "result"} dicts in call order.
"""
import statistics

# Pass/fail checks; each applies only when its case field is set, else it is None.
BOOL_CHECKS = ("unit_ok", "asked_location", "rerouted", "pets_ok", "medical_ok", "no_draft_ok", "priority_ok",
               "station_ok", "fallback_ok")

# Outage runs (run_eval.py --outage): the dead tool, and the words that show a draft says it is missing.
OUTAGE_NOUNS = {"plan_route": ("rout",), "find_shelters": ("shelter",), "get_weather_alerts": ("weather", "alert"),
                "get_road_closures": ("closure", "road condition")}
MISSING_WORDS = ("unavailable", "down", "missing", "not available", "unverified", "could not", "manual",
                 "offline", "no data", "failed", "unknown")
# Checks that need the dead tool to have worked; they cannot pass in an outage, so they are dropped.
OUTAGE_DROPS = {"plan_route": ("expect_reroute", "expect_station"),
                "find_shelters": ("expect_shelter_pets", "expect_shelter_medical")}
MAX_DEAD_CALLS = 3


def _ok(t):
    """A call that worked: no error, and not an injected fault (a malformed result is not a success)."""
    return "error" not in t["result"] and not t["result"].get("_fault")


def for_outage(case: dict, tool: str) -> dict:
    """The case as scored when `tool` is down for the whole run: the dead tool is no longer
    expected, and checks that need its result are dropped."""
    case = dict(case)
    case["expect_tools"] = [t for t in case.get("expect_tools") or [] if t != tool]
    for field in OUTAGE_DROPS.get(tool, ()):
        case.pop(field, None)
    return case


def fallback(case: dict, trace: list, draft):
    """Graceful fallback when a tool is down (a result marked _outage). None when no tool was down.
    True when the dead tool was tried at most MAX_DEAD_CALLS times and, if the case expects a draft,
    the agent still drafted one that says what is missing."""
    dead = {t["tool"] for t in trace if t["result"].get("_outage")}
    if not dead:
        return None
    if any(sum(t["tool"] == d for t in trace) > MAX_DEAD_CALLS for d in dead):
        return False
    if not case.get("expect_unit"):
        return True
    if not draft:
        return False
    text = (draft["args"].get("route_summary", "") + " " + draft["args"].get("notes", "")).lower()
    return all(any(n in text for n in OUTAGE_NOUNS.get(d, (d,))) and any(w in text for w in MISSING_WORDS)
               for d in dead)


def score(case: dict, trace: list, drafted: bool) -> dict:
    ok_calls = [t["tool"] for t in trace if _ok(t)]
    exp = case.get("expect_tools") or []
    recall = sum(t in ok_calls for t in exp) / len(exp) if exp else 1.0
    draft = next((t for t in trace if t["tool"] == "draft_dispatch" and _ok(t)), None)
    route = next((t["result"] for t in reversed(trace) if t["tool"] == "plan_route" and _ok(t)), {})
    shelter = next((t["args"] for t in trace if t["tool"] == "find_shelters" and _ok(t)), None)

    def check(field, value):
        return value if case.get(field) else None

    def from_station():
        """The route starts at the start point geocode_location gave for the drafted unit."""
        geo = next((t["result"] for t in trace if t["tool"] == "geocode_location" and _ok(t)), {})
        call = next((t for t in reversed(trace) if t["tool"] == "plan_route" and _ok(t)), None)
        station = draft and (geo.get("start_points") or {}).get(draft["args"].get("unit_type"))
        return bool(station and call and abs(call["args"].get("from_lat", 0) - station["lat"]) < 1e-3
                    and abs(call["args"].get("from_lon", 0) - station["lon"]) < 1e-3)

    return {
        "tool_recall": recall,
        "guard_blocks": sum(t["result"].get("blocked_by") == "guard" for t in trace),
        "tool_errors": sum("error" in t["result"] and t["result"].get("blocked_by") != "guard"
                           and not t["result"].get("_fault") for t in trace),
        "faults": sum(bool(t["result"].get("_fault")) for t in trace),  # injected (run_eval.py --faults, --outage)
        "malformed": sum(bool(t["result"].get("_malformed")) for t in trace),  # injected bad data
        "unit_ok": check("expect_unit", bool(draft) and draft["args"].get("unit_type") in (case.get("expect_unit") or [])),
        "asked_location": check("expect_ask_for_location", not drafted),
        "rerouted": check("expect_reroute", bool(route.get("rerouted"))),
        "pets_ok": check("expect_shelter_pets", bool(shelter and shelter.get("has_pets"))),
        "medical_ok": check("expect_shelter_medical", bool(shelter and shelter.get("needs_medical"))),
        "no_draft_ok": check("expect_no_draft", not drafted),
        "priority_ok": check("expect_priority_min",
                             bool(draft) and draft["args"].get("priority", 0) >= (case.get("expect_priority_min") or 0)),
        "station_ok": check("expect_station", from_station()),
        "fallback_ok": fallback(case, trace, draft),
        "outage_calls": sum(bool(t["result"].get("_outage")) for t in trace),
    }


def reward(checks: dict) -> float:
    """Mean of tool recall and every check that applies to the case, from 0 to 1."""
    parts = [checks["tool_recall"]] + [float(checks[k]) for k in BOOL_CHECKS if checks[k] is not None]
    return round(statistics.mean(parts), 4)


def resolved(checks: dict) -> bool:
    """True only when every applicable check passed and all expected tools were called."""
    return checks["tool_recall"] == 1.0 and all(checks[k] for k in BOOL_CHECKS if checks[k] is not None)
