"""End-to-end smoke test: StormDesk's scripted mock agent plays every task through this server.

It stands in for the model so the whole loop (task -> tool endpoints -> response output ->
verify) runs without a GPU. The mean reward should match eval/run_eval.py in mock mode,
since both score with stormdesk/scoring.py.
"""
import json
import statistics
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resources_servers.stormdesk_dispatch.app import StormDeskVerifyRequest
from resources_servers.stormdesk_dispatch.tests.test_app import _server, _verify_body
from stormdesk.agent import _mock_turn

DATA = Path(__file__).resolve().parents[1] / "data" / "validation.jsonl"


def _rollout(client, task):
    first = task["responses_create_params"]["input"][1]["content"]
    urgency = int(first.split("urgency ")[1].split("/")[0])
    incident = {"id": task["id"], "raw_text": task["text"], "urgency": urgency}
    cookies, results, steps = None, {}, []
    for step in range(12):
        nxt = _mock_turn(step, incident, results)
        if nxt is None or nxt[0] == "__final__":
            break
        name, args = nxt
        r = client.post(f"/{name}", json=args, cookies=cookies)
        cookies = cookies or r.cookies
        out = r.json()
        if "error" not in out:
            results[name] = out
        steps.append((name, args, out))
    return steps


@pytest.mark.asyncio
async def test_mock_agent_over_all_tasks():
    tasks = [json.loads(line) for line in open(DATA, encoding="utf-8")]
    server, client = _server()
    rewards = []
    for task in tasks:
        steps = _rollout(client, task)
        case = {k: v for k, v in task.items() if k != "responses_create_params"}
        req = MagicMock(); req.session = {}
        res = await server.verify(req, StormDeskVerifyRequest.model_validate(_verify_body(case, steps)))
        rewards.append(res.reward)
    mean = statistics.mean(rewards)
    print(f"mock agent: {len(tasks)} tasks, mean reward {mean:.3f}")
    assert len(tasks) >= 55 and 0.0 < mean <= 1.0
