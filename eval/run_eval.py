"""Agent benchmark: run every test incident with and without the guard.

    python eval/run_eval.py              # both modes
    python eval/run_eval.py --no-guard   # baseline only

Metrics per run:
  tool_recall     share of expected tools the agent actually called successfully
  guard_blocks    tool calls the guard rejected (and the model then had to fix)
  tool_errors     tool calls that crashed
  unit_ok         drafted unit type is one of the acceptable ones
  asked_location  for vague reports, agent did NOT draft and asked for location
  rerouted        for cases marked expect_reroute, plan_route detoured around a closure
  pets_ok         for expect_shelter_pets, find_shelters was called with has_pets
  medical_ok      for expect_shelter_medical, find_shelters was called with needs_medical
  no_draft_ok     for expect_no_draft (noise, injected instructions), nothing was drafted
  priority_ok     for expect_priority_min, the draft's priority is at least that
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


def run_mode(cases, use_guard):
    rows = []
    for c in cases:
        inc = ingest(c["text"], "eval")
        res = agent.run(inc["id"], use_guard=use_guard)
        rows.append({**score(c, res), "tag": c.get("tag", "untagged")})
    out = {"all": summarize(rows), "cases": len(rows)}
    for tag in sorted({r["tag"] for r in rows}):
        out[tag] = summarize([r for r in rows if r["tag"] == tag])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-guard", action="store_true")
    a = ap.parse_args()
    conn = db.connect()
    db.init(conn)
    cases = [json.loads(l) for l in open(HERE / "incidents.jsonl")]
    report = {"baseline_no_guard": run_mode(cases, False)}
    if not a.no_guard:
        report["with_guard"] = run_mode(cases, True)
    print(json.dumps(report, indent=2))
    (HERE / "results.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
