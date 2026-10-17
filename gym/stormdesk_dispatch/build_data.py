"""Build the Gym task files from eval/incidents.jsonl.

    python gym/stormdesk_dispatch/build_data.py

Writes data/validation.jsonl (all cases) and data/example.jsonl (one per tag, for smoke tests).
Each task carries the same system prompt, tools and first message the StormDesk app gives
Lightning. The category and urgency in that message come from the triage keyword rules,
so the tasks do not depend on the triage model being served.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from stormdesk.agent import SYSTEM  # noqa: E402
from stormdesk.tool_schemas import TOOLS  # noqa: E402
from stormdesk.triage import _mock_category, urgency  # noqa: E402

# Responses API function tools (Gym's format), converted from the app's chat-completions tools.
RESPONSES_TOOLS = [{"type": "function", "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "parameters": t["function"]["parameters"], "strict": False} for t in TOOLS]


def task(i: int, case: dict) -> dict:
    cat = _mock_category(case["text"])
    first = f"Incident #{i} (category {cat}, urgency {urgency(cat, case['text'])}/5): {case['text']}"
    return {
        "id": i,
        "responses_create_params": {
            "input": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": first}],
            "tools": RESPONSES_TOOLS,
        },
        **case,
    }


def main():
    cases = [json.loads(line) for line in open(ROOT / "eval" / "incidents.jsonl", encoding="utf-8")]
    tasks = [task(i, c) for i, c in enumerate(cases, start=1)]
    (HERE / "data").mkdir(exist_ok=True)
    with open(HERE / "data" / "validation.jsonl", "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t) + "\n")
    seen, examples = set(), []
    for t in tasks:
        if t.get("tag") not in seen:
            seen.add(t.get("tag"))
            examples.append(t)
    with open(HERE / "data" / "example.jsonl", "w", encoding="utf-8") as f:
        for t in examples:
            f.write(json.dumps(t) + "\n")
    print(f"wrote {len(tasks)} validation tasks and {len(examples)} examples")


if __name__ == "__main__":
    main()
