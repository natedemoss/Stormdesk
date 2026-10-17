"""NeMo Gym resources server: StormDesk disaster dispatch.

The agent gets a field report from a county emergency operations center and must use
StormDesk's offline tools (geocode, closures, weather, shelters, routing) to draft a
dispatch plan, or decline when the report is too vague, is noise, or carries injected
instructions. The verifier scores the tool-call trace with the same rules as
eval/run_eval.py (stormdesk/scoring.py).

Every rollout gets its own in-memory copy of the StormDesk cache, so report_closure and
draft_dispatch never leak between rollouts. The StormDesk guard (schema + ordering checks)
runs before each tool call, as in the app; turn it off with `use_guard: false` in the config
to measure the agent without it.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field

from nemo_gym.base_resources_server import (
    BaseResourcesServerConfig,
    BaseRunRequest,
    BaseSeedSessionRequest,
    BaseSeedSessionResponse,
    BaseVerifyRequest,
    BaseVerifyResponse,
    SimpleResourcesServer,
)
from nemo_gym.reward_profile import Stat
from nemo_gym.server_utils import SESSION_ID_KEY

# The StormDesk repo: STORMDESK_ROOT, else the repo this file lives in (symlinks resolved).
STORMDESK_ROOT = Path(os.getenv("STORMDESK_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(STORMDESK_ROOT))

from stormdesk import scoring, tools  # noqa: E402
from stormdesk.agent import Guard, for_model  # noqa: E402

TOOL_NAMES = list(tools.REGISTRY)


class StormDeskDispatchConfig(BaseResourcesServerConfig):
    # Synced StormDesk cache to copy per rollout (python -m stormdesk.db --init --load-samples, then sync/).
    db_path: str = str(STORMDESK_ROOT / "data" / "stormdesk.db")
    use_guard: bool = True


class StormDeskRunRequest(BaseRunRequest):
    """One eval case. Fields mirror eval/incidents.jsonl."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: int = 0
    tag: str = ""
    text: str = ""
    expect_tools: List[str] = Field(default_factory=list)
    expect_unit: Optional[List[str]] = None
    expect_ask_for_location: bool = False
    expect_reroute: bool = False
    expect_shelter_pets: bool = False
    expect_shelter_medical: bool = False
    expect_no_draft: bool = False
    expect_priority_min: Optional[int] = None


class StormDeskVerifyRequest(StormDeskRunRequest, BaseVerifyRequest):
    pass


class StormDeskVerifyResponse(BaseVerifyResponse):
    model_config = ConfigDict(extra="allow")

    resolved: bool
    tool_recall: float
    tool_calls: int
    guard_blocks: int
    tool_errors: int
    drafted: bool
    # Each check is None when it does not apply to the case; Gym's metrics skip None.
    unit_ok: Optional[bool] = None
    asked_location: Optional[bool] = None
    rerouted: Optional[bool] = None
    pets_ok: Optional[bool] = None
    medical_ok: Optional[bool] = None
    no_draft_ok: Optional[bool] = None
    priority_ok: Optional[bool] = None


class _Session:
    def __init__(self, db_path: str):
        src = sqlite3.connect(db_path)
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        src.backup(self.conn)
        src.close()
        self.conn.row_factory = sqlite3.Row
        self.guard = Guard()


def trace_from_output(output: List[Any]) -> List[Dict[str, Any]]:
    """Pair function_call items with their function_call_output into StormDesk trace entries."""
    def get(item, key):
        return item.get(key) if isinstance(item, dict) else getattr(item, key, None)

    results = {get(o, "call_id"): get(o, "output") for o in output if get(o, "type") == "function_call_output"}
    trace = []
    for o in output:
        if get(o, "type") != "function_call":
            continue
        try:
            args = json.loads(get(o, "arguments") or "{}")
        except json.JSONDecodeError:
            args = {"__unparseable__": get(o, "arguments")}
        raw = results.get(get(o, "call_id"))
        try:
            result = json.loads(raw) if raw is not None else {"error": "no tool output"}
        except json.JSONDecodeError:
            result = {"error": f"non-JSON tool output: {str(raw)[:200]}"}
        if not isinstance(result, dict):
            result = {"error": "tool output was not an object"}
        trace.append({"tool": get(o, "name"), "args": args, "result": result})
    return trace


class StormDeskDispatchResourcesServer(SimpleResourcesServer):
    ray_enabled = False
    config: StormDeskDispatchConfig
    sessions: Dict[str, Any] = Field(default_factory=dict)  # session id -> _Session

    def setup_webserver(self) -> FastAPI:
        app = super().setup_webserver()
        for name in TOOL_NAMES:
            app.post(f"/{name}")(self._tool_endpoint(name))
        return app

    def _session(self, request: Request) -> _Session:
        sid = request.session[SESSION_ID_KEY]
        if sid not in self.sessions:
            self.sessions[sid] = _Session(self.config.db_path)
        return self.sessions[sid]

    def _tool_endpoint(self, name: str):
        async def endpoint(request: Request) -> Dict[str, Any]:
            try:
                args = await request.json()
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}
            sess = self._session(request)
            if self.config.use_guard:
                err = sess.guard.check(name, args)
                if err:
                    return {"error": err, "blocked_by": "guard"}
            # tools.* read the module-level connection. Swapping it and calling the tool with no
            # await in between keeps each call on its own rollout's copy of the cache.
            tools._conn = sess.conn
            try:
                out = tools.REGISTRY[name](**args)
            except Exception as e:  # tool failures go back to the model, as in the app
                return {"error": f"{type(e).__name__}: {e}"}
            sess.guard.called.append(name)
            return for_model(out)

        endpoint.__name__ = name
        return endpoint

    async def seed_session(self, request: Request, body: BaseSeedSessionRequest) -> BaseSeedSessionResponse:
        self._session(request)
        return BaseSeedSessionResponse()

    async def verify(self, request: Request, body: StormDeskVerifyRequest) -> StormDeskVerifyResponse:
        trace = trace_from_output(body.response.output)
        drafted = any(t["tool"] == "draft_dispatch" and "error" not in t["result"] for t in trace)
        checks = scoring.score(body.model_dump(), trace, drafted)
        self.sessions.pop(request.session.get(SESSION_ID_KEY), None)  # rollout is over
        return StormDeskVerifyResponse(
            **body.model_dump(),
            **checks,
            reward=scoring.reward(checks),
            resolved=scoring.resolved(checks),
            tool_calls=len(trace),
            drafted=drafted,
        )

    def get_key_metrics(self, agent_metrics: Dict[str, Any]) -> Dict[str, Any]:
        cols = ("reward", "resolved", "unit_ok", "asked_location", "no_draft_ok", "guard_blocks")
        keys = [f"{Stat.MEAN.prefix}{c}" for c in cols]
        return {k: agent_metrics[k] for k in keys if k in agent_metrics}


if __name__ == "__main__":
    StormDeskDispatchResourcesServer.run_webserver()
