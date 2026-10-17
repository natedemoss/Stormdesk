"""Agent benchmark: run every test incident with and without the guard.

    python eval/run_eval.py              # both modes
    python eval/run_eval.py --no-guard   # baseline only
    python eval/run_eval.py --faults 0.3 # 30% of tool calls fail before running: does it recover?
    python eval/run_eval.py --outage plan_route   # one tool down all run: does it fall back?
    python eval/run_eval.py --outage all          # each of the four outages in turn

--faults: an injected fault is either an exception (timeout, database locked) or, for
geocode_location, plan_route and find_shelters, half the time a malformed result (no coordinates,
no distance, an HTML error page instead of a shelter list). Results: eval/results_faults.json.
--outage TOOL: every call to TOOL fails (plan_route, find_shelters, get_weather_alerts,
get_road_closures). The dead tool is dropped from expect_tools, and checks that need its result
(reroute and station for plan_route, pets and medical for find_shelters) are skipped; fallback_ok
is scored instead. Results: eval/results_outage_<tool>.json.

Metrics per run:
  tool_recall     share of expected tools the agent actually called successfully
                  (an injected fault or malformed result is not a success)
  guard_blocks    tool calls the guard rejected (and the model then had to fix), including the
                  pre-draft self-check: the route must start where the drafted unit starts
  tool_errors     tool calls that crashed (not counting injected faults)
  faults          tool calls failed on purpose by --faults or --outage
  malformed       of those, the ones that returned bad data instead of an error
  outage_calls    calls to the dead tool (--outage); fallback_ok fails above 3
  unit_ok         drafted unit type is one of the acceptable ones
  asked_location  for vague reports, agent did NOT draft and asked for location
  rerouted        for cases marked expect_reroute, plan_route detoured around a closure
  pets_ok         for expect_shelter_pets, find_shelters was called with has_pets
  medical_ok      for expect_shelter_medical, find_shelters was called with needs_medical
  no_draft_ok     for expect_no_draft (noise, injected instructions), nothing was drafted
  priority_ok     for expect_priority_min, the draft's priority is at least that
  station_ok      for expect_station, the route starts at start_points[drafted unit]
  fallback_ok     with --outage, when the dead tool was called: it was tried at most 3 times, and
                  if the case expects a draft, one was written that says what is missing
  reward          mean of tool_recall and every applicable check (same as the NeMo Gym environment)
  resolved        share of cases where every applicable check passed
  seconds         wall time to finish
Each case has a "tag" (rescue, vague, adversarial, ...); results are also reported per tag.
Add incidents to eval/incidents.jsonl. Aim for 50, including tricky ones.
"""
import argparse
import json
import os
import shutil
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Run against a copy of the cache so eval incidents never land in the demo queue.
if "STORMDESK_DB" not in os.environ:
    src, dst = ROOT / "data" / "stormdesk.db", ROOT / "data" / "eval.db"
    if src.exists():
        shutil.copy(src, dst)
    os.environ["STORMDESK_DB"] = str(dst)

sys.path.insert(0, str(ROOT))
from stormdesk import agent, db, scoring  # noqa: E402
from stormdesk.triage import ingest  # noqa: E402

HERE = Path(__file__).resolve().parent


def score(case, res):
    checks = scoring.score(case, res["trace"], res["drafted"])
    return {**checks, "reward": scoring.reward(checks), "resolved": scoring.resolved(checks),
            "seconds": res["seconds"]}


def summarize(rows):
    def mean(k):
        v = [r[k] for r in rows if r[k] is not None]
        return round(statistics.mean(v), 3) if v else None
    return {k: mean(k) for k in rows[0] if k != "tag"}


def tool_choice(sequences):
    """How much the agent's tool use varies by report: evidence it is not one hard-coded sequence.
    A sequence is the tools a run called, in order, with repeats (retries) collapsed."""
    from collections import Counter
    seqs = Counter(" > ".join(s) or "(no tools)" for s in sequences)
    used = Counter(t for s in sequences for t in set(s))
    return {"distinct_sequences": len(seqs), "runs": len(sequences),
            "most_common_share": round(seqs.most_common(1)[0][1] / len(sequences), 3) if sequences else None,
            "no_tool_runs": seqs.get("(no tools)", 0),
            "tool_use_share": {t: round(n / len(sequences), 3) for t, n in sorted(used.items())},
            "top_sequences": [{"sequence": s, "runs": n} for s, n in seqs.most_common(5)]}


def run_mode(cases, use_guard, fault_rate=0.0, outage=None):
    rows, sequences = [], []
    for n, c in enumerate(cases):
        inc = ingest(c["text"], "eval")
        res = agent.run(inc["id"], use_guard=use_guard, fault_rate=fault_rate, fault_seed=n, outage=outage)
        rows.append({**score(scoring.for_outage(c, outage) if outage else c, res), "tag": c.get("tag", "untagged")})
        seq = []
        for t in res["trace"]:
            if not seq or seq[-1] != t["tool"]:
                seq.append(t["tool"])
        sequences.append(seq)
    out = {"all": summarize(rows), "cases": len(rows), "tool_choice": tool_choice(sequences)}
    for tag in sorted({r["tag"] for r in rows}):
        out[tag] = summarize([r for r in rows if r["tag"] == tag])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-guard", action="store_true")
    ap.add_argument("--faults", type=float, default=0.0,
                    help="inject tool failures at this rate (e.g. 0.3), guard on; writes results_faults.json")
    ap.add_argument("--outage", choices=[*agent.OUTAGES, "all"],
                    help="one tool down for the whole run, guard on; writes results_outage_<tool>.json")
    a = ap.parse_args()
    conn = db.connect()
    db.init(conn)
    cases = [json.loads(l) for l in open(HERE / "incidents.jsonl")]
    if a.outage:
        for tool in agent.OUTAGES if a.outage == "all" else [a.outage]:
            report = {f"with_guard_outage_{tool}": run_mode(cases, True, a.faults, outage=tool)}
            print(json.dumps(report, indent=2))
            (HERE / f"results_outage_{tool}.json").write_text(json.dumps(report, indent=2))
        return
    if a.faults:
        report = {f"with_guard_faults_{a.faults}": run_mode(cases, True, a.faults)}
        print(json.dumps(report, indent=2))
        (HERE / "results_faults.json").write_text(json.dumps(report, indent=2))
        return
    report = {"baseline_no_guard": run_mode(cases, False)}
    if not a.no_guard:
        report["with_guard"] = run_mode(cases, True)
    print(json.dumps(report, indent=2))
    (HERE / "results.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
