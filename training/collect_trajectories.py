"""Run Lightning on the practice tasks and keep the runs that score perfectly, as fine-tuning data.

    python training/collect_trajectories.py                   # 2 samples per task, on the GPU box
    python training/collect_trajectories.py --samples 4 --temperature 0.8
    STORMDESK_MOCK_LLM=1 python training/collect_trajectories.py --limit 10   # laptop smoke test

For every task in training/agent_tasks.jsonl (made by gen_agent_tasks.py, never the eval cases):
the report goes through intake, then the agent runs with the guard on, and stormdesk/scoring.py
grades the run exactly as the eval and the NeMo Gym environment do. A run is kept only if it is
resolved (every check passed) with no guard blocks and no tool errors.

Writes to training/data_agent/:
  sft.jsonl      kept runs, one per line: {"messages": [...], "tools": [...], "tag", "reward"}
  summary.json   before numbers on the practice tasks (first sample of each) and how many runs were kept
Runs against a copy of the cache (data/train.db), so nothing lands in the demo queue.
"""
import argparse
import json
import os
import shutil
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if "STORMDESK_DB" not in os.environ:
    src, dst = ROOT / "data" / "stormdesk.db", ROOT / "data" / "train.db"
    if src.exists():
        shutil.copy(src, dst)
    os.environ["STORMDESK_DB"] = str(dst)

sys.path.insert(0, str(ROOT))
from stormdesk import agent, db, scoring  # noqa: E402
from stormdesk.tool_schemas import TOOLS  # noqa: E402
from stormdesk.triage import ingest  # noqa: E402


def attempt(task, temperature):
    try:
        inc = ingest(task["text"], "train")
        res = agent.run(inc["id"], use_guard=True, temperature=temperature)
    except Exception as e:  # a failed run is just not kept
        return {"error": f"{type(e).__name__}: {e}"}
    checks = scoring.score(task, res["trace"], res["drafted"])
    clean = checks["guard_blocks"] == 0 and checks["tool_errors"] == 0
    return {"checks": checks, "reward": scoring.reward(checks), "keep": scoring.resolved(checks) and clean,
            "messages": res["messages"], "seconds": res["seconds"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "training" / "agent_tasks.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "training" / "data_agent"))
    ap.add_argument("--samples", type=int, default=2, help="runs per task")
    ap.add_argument("--temperature", type=float, default=0.7, help="above the app's 0.2, for varied runs")
    ap.add_argument("--workers", type=int, default=6, help="parallel runs (vLLM batches them)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N tasks")
    a = ap.parse_args()

    conn = db.connect()
    db.init(conn)
    conn.execute("PRAGMA journal_mode=WAL")  # parallel runs read while one writes (train.db only)
    from stormdesk import tools
    tools._graph(), tools._node_index()  # load the road graph once, before the threads start
    tasks = [json.loads(line) for line in open(a.tasks, encoding="utf-8")]
    if a.limit:
        tasks = tasks[:a.limit]
    jobs = [(i, s) for i in range(len(tasks)) for s in range(a.samples)]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    results = {}
    with ThreadPoolExecutor(a.workers) as pool:
        futures = {pool.submit(attempt, tasks[i], a.temperature): (i, s) for i, s in jobs}
        for n, fut in enumerate(futures, 1):
            results[futures[fut]] = fut.result()
            if n % 20 == 0 or n == len(jobs):
                kept = sum(r.get("keep", False) for r in results.values())
                print(f"{n}/{len(jobs)} runs, {kept} kept", flush=True)

    kept, seen = [], set()
    with open(out / "sft.jsonl", "w", encoding="utf-8") as f:
        for (i, s), r in sorted(results.items()):
            if not r.get("keep"):
                continue
            calls = json.dumps([m.get("tool_calls") for m in r["messages"]], sort_keys=True)
            if (i, calls) in seen:  # identical tool sequence for the same task adds nothing
                continue
            seen.add((i, calls))
            kept.append(tasks[i]["tag"])
            f.write(json.dumps({"messages": r["messages"], "tools": TOOLS, "tag": tasks[i]["tag"],
                                "reward": r["reward"]}) + "\n")

    first = [results[(i, 0)] for i in range(len(tasks))]
    ok = [r for r in first if "checks" in r]

    def mean(vals):
        return round(statistics.mean(vals), 3) if vals else None

    by_tag = {}
    for i, r in enumerate(first):
        if "checks" in r:
            by_tag.setdefault(tasks[i]["tag"], []).append(r["reward"])
    summary = {
        "tasks": len(tasks), "samples_per_task": a.samples, "temperature": a.temperature,
        "before_on_practice_tasks": {
            "reward": mean([r["reward"] for r in ok]),
            "resolved": mean([float(r["checks"] and scoring.resolved(r["checks"])) for r in ok]),
            "guard_blocks": mean([r["checks"]["guard_blocks"] for r in ok]),
            "seconds": mean([r["seconds"] for r in ok]),
            "by_tag": {t: mean(v) for t, v in sorted(by_tag.items())},
        },
        "failed_runs": sum("error" in r for r in results.values()),
        "kept": len(kept),
        "kept_by_tag": {t: kept.count(t) for t in sorted(set(kept))},
        "tasks_with_a_kept_run": len({i for i, _ in seen}),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
