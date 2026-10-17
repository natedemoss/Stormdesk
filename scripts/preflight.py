"""Check that everything the demo needs is ready, with a fix for anything that isn't.

    python scripts/preflight.py                # full check on the GPU box
    python scripts/preflight.py --skip-models  # laptop / mock mode: skip the vLLM checks

Only talks to local services (the two vLLM servers and the console). Exit code 1 if anything FAILs.
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS = []


def report(status, what, detail="", fix=""):
    RESULTS.append(status)
    mark = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL", "INFO": "    "}[status]
    print(f"[{mark}] {what}" + (f": {detail}" if detail else ""))
    if fix and status in ("WARN", "FAIL"):
        print(f"       fix: {fix}")


def hours_since(ts):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def check_python():
    missing = []
    for mod in ("openai", "osmnx", "networkx", "fastapi", "uvicorn", "jsonschema", "yaml", "dotenv"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        report("FAIL", "Python packages", "missing " + ", ".join(missing), "pip install -r requirements.txt")
    else:
        report("PASS", "Python packages")


def check_data():
    from stormdesk.config import DB_PATH, MOCK_LLM, ROAD_GRAPH
    if not DB_PATH.exists():
        report("FAIL", "Offline cache", f"{DB_PATH} missing",
               "python -m stormdesk.db --init --load-samples, then the sync/ scripts (see README)")
        return
    c = sqlite3.connect(DB_PATH)
    count = lambda t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
    places, closures, shelters = count("places"), count("closures"), count("shelters")
    if places < 100:
        report("FAIL", "Gazetteer", f"only {places} places (samples, not the real counties)",
               "python sync/sync_all.py")
    else:
        counties = [r[0] for r in c.execute("SELECT DISTINCT county FROM places WHERE county != ''")]
        report("PASS", "Gazetteer", f"{places} places and roads in {len(counties)} counties")
    report("PASS" if shelters else "FAIL", "Shelters", f"{shelters}", "python sync/sync_shelters.py")
    report("PASS" if closures else "WARN", "Closures", f"{closures}", "python sync/sync_ncdot.py")
    for source, script in (("ncdot", "sync/sync_ncdot.py"), ("noaa", "sync/sync_noaa.py"),
                           ("shelters", "sync/sync_shelters.py")):
        row = c.execute("SELECT last_success FROM sync_log WHERE source=?", (source,)).fetchone()
        age = hours_since(row[0]) if row else None
        if age is None:
            report("WARN", f"Sync {source}", "never synced", f"python {script}")
        else:
            report("PASS" if age < 24 else "WARN", f"Sync {source}", f"{age:.0f} h old", f"python {script}")
    demo = count("incidents")
    report("INFO", "Demo queue", f"{demo} reports (reset with python scripts/reset_demo.py)")
    if not ROAD_GRAPH.exists():
        report("FAIL", "Road graph", f"{ROAD_GRAPH} missing", "python sync/sync_all.py")
    else:
        t = time.time()
        from stormdesk import tools
        g = tools._graph()
        report("PASS", "Road graph", f"{len(g.nodes)} nodes, loaded in {time.time() - t:.1f} s")
    if not os.getenv("DRIVENC_API_KEY"):
        report("WARN", "DriveNC key", "not set (only needed to re-sync closures)", "add DRIVENC_API_KEY=... to .env")
    if MOCK_LLM:
        report("WARN", "Mock mode", "STORMDESK_MOCK_LLM=1, so the scripted agent runs, not Lightning",
               "unset STORMDESK_MOCK_LLM (or set it to 0) for the real demo")


def check_models():
    from openai import OpenAI
    from stormdesk.agent import SYSTEM
    from stormdesk.config import AGENT_BASE_URL, AGENT_MODEL, TRIAGE_BASE_URL, TRIAGE_MODEL
    from stormdesk.tool_schemas import TOOLS
    from stormdesk.triage import CATEGORIES, SCHEMA
    from stormdesk.triage import SYSTEM as TRIAGE_SYSTEM

    for name, url, model, serve in (("Lightning (agent)", AGENT_BASE_URL, AGENT_MODEL, "bash scripts/serve_lightning.sh"),
                                    ("Triage", TRIAGE_BASE_URL, TRIAGE_MODEL, "bash scripts/serve_triage.sh")):
        try:
            ids = [m.id for m in OpenAI(base_url=url, api_key="local", timeout=10).models.list().data]
        except Exception as e:
            report("FAIL", f"{name} server", f"{url} not answering ({type(e).__name__})", serve)
            continue
        if model in ids:
            report("PASS", f"{name} server", f"{url} serves {model}")
        else:
            report("FAIL", f"{name} server", f"{url} serves {ids}, expected {model}",
                   "fix AGENT_MODEL / TRIAGE_MODEL in .env, or the --served-model-name flag")

    # Triage: one real classification with the app's exact request
    try:
        t = time.time()
        r = OpenAI(base_url=TRIAGE_BASE_URL, api_key="local", timeout=30).chat.completions.create(
            model=TRIAGE_MODEL, temperature=0, max_tokens=40,
            messages=[{"role": "system", "content": TRIAGE_SYSTEM},
                      {"role": "user", "content": "my dad is 81 and trapped upstairs, water rising fast"}],
            response_format={"type": "json_schema", "json_schema": {"name": "triage", "schema": SCHEMA}},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        cat = json.loads(r.choices[0].message.content)["category"]
        ok = cat in CATEGORIES
        report("PASS" if ok else "FAIL", "Triage classification", f"{cat} in {(time.time() - t) * 1000:.0f} ms",
               "check the served model is ndemoss28/stormdesks-triage")
    except Exception as e:
        report("FAIL", "Triage classification", f"{type(e).__name__}: {str(e)[:120]}", "see the triage vLLM log")

    # Lightning's second opinion on intake: a report no keyword rule catches must come back at_risk
    from stormdesk import triage
    t = time.time()
    op = triage.second_opinion("my husband's lips are turning blue")
    ms = (time.time() - t) * 1000
    if op is None:
        report("FAIL", "Second opinion", "no answer from Lightning (intake falls back to keyword rules)",
                "check the Lightning server; see 'second opinion unavailable' in the console log")
    elif op["at_risk"]:
        report("PASS" if ms < 5000 else "WARN", "Second opinion", f"at_risk in {ms:.0f} ms ({op['reason']})",
               "slow: every incoming report waits for it; lower --max-model-len or check GPU load")
    else:
        report("WARN", "Second opinion", f"said not at risk for blue lips ({op['reason']})",
               "review SECOND_OPINION_SYSTEM in stormdesk/triage.py")

    # Lightning: does it call a tool for a clear report?
    try:
        t = time.time()
        r = OpenAI(base_url=AGENT_BASE_URL, api_key="local", timeout=120).chat.completions.create(
            model=AGENT_MODEL, temperature=0.2, tools=TOOLS, tool_choice="auto",
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": "Incident #0 (category requests_or_urgent_needs, urgency 5/5): "
                                                  "family trapped by rising water in Nebo"}])
        calls = r.choices[0].message.tool_calls or []
        ms = (time.time() - t) * 1000
        if calls and calls[0].function.name == "geocode_location":
            report("PASS", "Lightning tool calling", f"called geocode_location in {ms:.0f} ms")
        elif calls:
            report("WARN", "Lightning tool calling", f"first call was {calls[0].function.name}, expected geocode_location")
        else:
            report("FAIL", "Lightning tool calling", "no tool call returned",
                   "serve with --enable-auto-tool-choice --tool-call-parser qwen3_coder (scripts/serve_lightning.sh)")
    except Exception as e:
        report("FAIL", "Lightning tool calling", f"{type(e).__name__}: {str(e)[:120]}", "see the Lightning vLLM log")


def check_gpu():
    if not shutil.which("nvidia-smi"):
        report("INFO", "GPU", "nvidia-smi not found (fine on a laptop in mock mode)")
        return
    out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader"],
                         capture_output=True, text=True).stdout.strip()
    report("INFO", "GPU", out or "no GPU reported")


def check_openshell():
    if not shutil.which("openshell"):
        report("WARN", "OpenShell", "CLI not installed (needed for the sandbox part of the demo)",
               "curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh")
        return
    report("PASS", "OpenShell", "CLI installed")
    if shutil.which("openshell-prover"):
        r = subprocess.run(["openshell-prover", "check", "openshell/policy.yaml", "--boundary", "openshell/boundary.yaml"],
                           capture_output=True, text=True, cwd=ROOT)
        ok = "within_boundary" in r.stdout
        report("PASS" if ok else "FAIL", "Policy prover", r.stdout.strip().splitlines()[0] if r.stdout else r.stderr[:120],
               "fix openshell/policy.yaml until it is within_boundary")
    else:
        report("WARN", "Policy prover", "openshell-prover not installed", "see openshell/POLICY.md")


def check_console(url):
    import urllib.request
    try:
        with urllib.request.urlopen(f"{url}/api/state", timeout=5) as r:
            state = json.load(r)
        report("PASS", "Console", f"{url} up, {len(state['incidents'])} reports in the queue, mode {state['mode']}")
    except Exception:
        report("WARN", "Console", f"{url} not answering",
               "python ui/server.py (or scripts/openshell_up.sh for the sandboxed demo)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-models", action="store_true", help="skip the vLLM checks (laptop, mock mode)")
    ap.add_argument("--console", default="http://localhost:8080")
    a = ap.parse_args()
    print("StormDesk preflight\n")
    check_python()
    check_data()
    if not a.skip_models:
        check_models()
    check_gpu()
    check_openshell()
    check_console(a.console)
    fails, warns = RESULTS.count("FAIL"), RESULTS.count("WARN")
    print(f"\n{fails} failed, {warns} warnings" + ("" if fails else ". Ready to demo." if not warns else "."))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
