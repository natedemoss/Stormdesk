"""StormDesk dispatcher console (web).

    python ui/server.py            # then open http://localhost:8080

Serves ui/static and a small JSON API over the same agent, tools and SQLite
cache. Everything is local: no CDN, no outside calls, so it keeps working with
the network unplugged. STORMDESK_MOCK_LLM=1 runs it without a GPU.
"""
import json
import queue
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import yaml  # noqa: E402

from stormdesk import agent, audit, db, demo, redteam, tools  # noqa: E402
from stormdesk.config import AGENT_MODEL, COUNTIES, IN_SANDBOX, MOCK_LLM, ROAD_GRAPH, ROOT, TRIAGE_MODEL  # noqa: E402
from stormdesk.tool_schemas import STAGING  # noqa: E402
from stormdesk.triage import HIDDEN_CATEGORIES, ingest  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
MOCK_STEP_DELAY = 0.7  # seconds between tool calls in mock mode, so the trace visibly streams
def hidden(incident) -> bool:
    """Filtered categories leave the queue, unless a safety rule flagged the report."""
    return incident["category"] in HIDDEN_CATEGORIES and not incident.get("flag")
MAX_ROAD_SEGMENTS = 40000

app = FastAPI(title="StormDesk")
db.init(db.connect())


@app.middleware("http")
async def no_stale_assets(request, call_next):
    """Make browsers revalidate the console's files, so an update shows on a normal reload."""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def get_conn():
    """One connection per request; FastAPI runs handlers on a thread pool."""
    return db.connect()


def rows(sql, *args):
    c = get_conn()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def state():
    """Everything the console polls: queue, map layers, data freshness."""
    c = get_conn()
    sync = {s: db.last_synced(c, s) for s in ("ncdot", "noaa", "shelters", "gazetteer", "sample")}
    c.close()
    incidents = rows(
        "SELECT i.*, (SELECT status FROM dispatch_queue d WHERE d.incident_id=i.id "
        "ORDER BY d.id DESC LIMIT 1) AS draft_status FROM incidents i ORDER BY i.id")
    return {
        "mode": "mock" if MOCK_LLM else "vllm",
        "models": {"agent": AGENT_MODEL, "triage": TRIAGE_MODEL},
        "staging": STAGING,
        "staging_points": list(tools.staging_points()),
        "stations": list(tools._stations()),
        "counties": COUNTIES,
        "sync": sync,
        "road_graph": ROAD_GRAPH.exists(),
        "incidents": [i for i in incidents if not hidden(i)],
        "filtered_out": sum(hidden(i) for i in incidents),
        "closures": rows("SELECT id, road, lat, lon, lat2, lon2, description, source, verified, "
                         "reported_at FROM closures"),
        "shelters": rows("SELECT * FROM shelters"),
        "alerts": rows("SELECT event, severity, area, headline, expires FROM alerts"),
    }


MAJOR = {"motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"}
MID = {"secondary", "tertiary", "secondary_link", "tertiary_link"}


def road_class(G, u, v):
    """0 = major (interstate, US/NC routes), 1 = collector, 2 = local. Drives line weight."""
    hw = next(iter(G.get_edge_data(u, v).values())).get("highway", "")
    hw = set(hw if isinstance(hw, list) else [hw])
    return 0 if hw & MAJOR else 1 if hw & MID else 2


@lru_cache(maxsize=1)
def road_table():
    """Every road segment once (one direction), as arrays: x1, y1, x2, y2, class."""
    import numpy as np
    G = tools._graph()
    rows, seen = [], set()
    for u, v in G.edges():
        if (v, u) in seen or (u, v) in seen:
            continue
        seen.add((u, v))
        a, b = G.nodes[u], G.nodes[v]
        rows.append((a["x"], a["y"], b["x"], b["y"], road_class(G, u, v)))
    return np.array(rows)


@app.get("/api/roads")
def roads(minlon: float, minlat: float, maxlon: float, maxlat: float):
    """Road segments inside a bounding box, from the cached OSM graph. Like any map, a wide
    view leaves out local streets; they show below about 0.3 degrees (30 km) across."""
    import numpy as np
    if tools._graph() is None:
        return {"segments": [], "graph": False}
    t = road_table()
    span = max(maxlon - minlon, maxlat - minlat)
    max_class = 2 if span < 0.3 else 1
    in_a = (t[:, 0] >= minlon) & (t[:, 0] <= maxlon) & (t[:, 1] >= minlat) & (t[:, 1] <= maxlat)
    in_b = (t[:, 2] >= minlon) & (t[:, 2] <= maxlon) & (t[:, 3] >= minlat) & (t[:, 3] <= maxlat)
    rows = t[(in_a | in_b) & (t[:, 4] <= max_class)]
    rows = rows[np.argsort(rows[:, 4], kind="stable")][:MAX_ROAD_SEGMENTS]  # major roads first
    segs = [[round(r[0], 5), round(r[1], 5), round(r[2], 5), round(r[3], 5), int(r[4])] for r in rows]
    return {"segments": segs, "graph": True}


@app.get("/api/incidents/{iid}")
def incident(iid: int):
    conn = get_conn()
    inc = conn.execute("SELECT * FROM incidents WHERE id=?", (iid,)).fetchone()
    if not inc:
        raise HTTPException(404, "no such incident")
    d = conn.execute("SELECT * FROM dispatch_queue WHERE incident_id=? ORDER BY id DESC LIMIT 1",
                     (iid,)).fetchone()
    draft = None
    if d:
        draft = {"id": d["id"], "status": d["status"], "created_at": d["created_at"],
                 "plan": json.loads(d["plan_json"])}
    return {"incident": dict(inc), "draft": draft,
            "trace": json.loads(d["trace_json"]) if d else []}


@app.post("/api/incidents/{iid}/run")
def run_agent(iid: int, guard: bool = True, faults: float = 0.0, outage: str = ""):
    """Runs the agent and streams one JSON line per tool call, then a done line.
    faults: share of tool calls to fail on purpose (the console's Faults switch), to show recovery.
    outage: a tool that is down for the whole run (the console's Outage menu), to show fallback."""
    faults = min(max(faults, 0.0), 0.5)
    if outage and outage not in agent.OUTAGES:
        raise HTTPException(400, f"outage must be one of {list(agent.OUTAGES)}")
    q = queue.Queue()

    def on_step(entry):
        q.put({"type": "step", "entry": entry})
        if MOCK_LLM:
            time.sleep(MOCK_STEP_DELAY)

    def work():
        try:
            res = agent.run(iid, use_guard=guard, on_step=on_step, fault_rate=faults, outage=outage or None)
            q.put({"type": "done", "final": res["final"], "seconds": res["seconds"],
                   "drafted": res["drafted"], "calls": len(res["trace"])})
        except Exception as e:  # surface it in the console instead of a dead stream
            q.put({"type": "error", "error": f"{type(e).__name__}: {e}"})
        q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while (msg := q.get()) is not None:
            yield json.dumps(msg) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class Report(BaseModel):
    text: str
    channel: str = "sms"


@app.post("/api/reports")
def add_report(r: Report):
    if not r.text.strip():
        raise HTTPException(400, "empty report")
    return ingest(r.text.strip(), r.channel)


@app.post("/api/demo/reset")
def reset_demo(empty: bool = False):
    """Same as scripts/reset_demo.py: clear reports, drafts and learned closures, then reload
    the demo reports through triage. Works inside the sandbox, where the live DB is in /tmp."""
    return demo.reset(load_reports=not empty)


@app.post("/api/drafts/{did}/{decision}")
def decide(did: int, decision: str):
    """Human approval. Approving only changes a status; nothing is sent anywhere."""
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    status = "approved" if decision == "approve" else "rejected"
    conn = get_conn()
    d = conn.execute("SELECT incident_id FROM dispatch_queue WHERE id=?", (did,)).fetchone()
    if not d:
        raise HTTPException(404, "no such draft")
    conn.execute("UPDATE dispatch_queue SET status=? WHERE id=?", (status, did))
    conn.execute("UPDATE incidents SET status=? WHERE id=?", (status, d["incident_id"]))
    conn.commit()
    return {"id": did, "status": status}


def policy_summary():
    """The OpenShell policy this build ships with, flattened for display."""
    p = yaml.safe_load((ROOT / "openshell" / "policy.yaml").read_text())
    fs = p.get("filesystem_policy", {})
    net = []
    for key, rule in (p.get("network_policies") or {}).items():
        for ep in rule.get("endpoints", []):
            ports = ep.get("ports") or [ep.get("port")]
            allows = [f"{r['allow']['method']} {r['allow']['path']}" for r in ep.get("rules", [])] or [ep.get("access", "")]
            net.append({"rule": key, "host": ep.get("host"), "ports": ports, "allows": allows,
                        "enforcement": ep.get("enforcement", "audit"),
                        "binaries": [b["path"] for b in rule.get("binaries", [])]})
    return {"read_only": fs.get("read_only", []), "read_write": fs.get("read_write", []),
            "landlock": (p.get("landlock") or {}).get("compatibility"),
            "run_as": (p.get("process") or {}).get("run_as_user"), "network": net}


def prover_results():
    """Output of openshell-prover saved by scripts/openshell_up.sh, if it ran."""
    out = {}
    for key in ("policy", "bad-policy"):
        f = ROOT / "openshell" / f"prover-{key}.txt"
        if f.exists():
            out[key] = f.read_text(encoding="utf-8-sig", errors="replace").strip()
    return out


@app.get("/api/sandbox")
def sandbox():
    events, source = audit.tail()
    return {"in_sandbox": IN_SANDBOX, "policy": policy_summary(), "prover": prover_results(),
            "audit": events, "audit_source": source}


@app.post("/api/redteam")
def run_redteam():
    return redteam.run()


app.mount("/static", StaticFiles(directory=STATIC), name="static")

# The six-county road graph takes ~10 s to load. Start now, so the first agent run and the
# first map draw don't wait for it.
threading.Thread(target=lambda: tools._graph() is not None and (tools._node_index(), road_table()),
                 daemon=True).start()

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
