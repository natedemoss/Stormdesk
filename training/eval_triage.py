"""Score a triage model served by vLLM on the HumAID test split.

    # fine-tuned model
    python training/eval_triage.py --url http://localhost:8001/v1 --model stormdesk-triage
    # untuned base for comparison (serve it on another port)
    python training/eval_triage.py --url http://localhost:8002/v1 --model Qwen/Qwen3-1.7B
"""
import argparse
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk.triage import CATEGORIES, SCHEMA, SYSTEM  # noqa: E402

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8001/v1")
    ap.add_argument("--model", default="stormdesk-triage")
    ap.add_argument("--n", type=int, default=2000)
    a = ap.parse_args()
    from openai import OpenAI
    from sklearn.metrics import classification_report, f1_score

    rows = [json.loads(l) for l in open(HERE / "data/test.jsonl")]
    random.seed(0)
    rows = random.sample(rows, min(a.n, len(rows)))
    client = OpenAI(base_url=a.url, api_key="local")

    def predict(r):
        text = r["messages"][1]["content"]
        try:
            out = client.chat.completions.create(
                model=a.model, temperature=0, max_tokens=40,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
                response_format={"type": "json_schema", "json_schema": {"name": "triage", "schema": SCHEMA}},
                extra_body={"chat_template_kwargs": {"enable_thinking": False}})  # same format as training
            return json.loads(out.choices[0].message.content)["category"]
        except Exception:
            return "dont_know_cant_judge"

    with ThreadPoolExecutor(32) as ex:   # vLLM batches these
        preds = list(ex.map(predict, rows))
    gold = [r["label"] for r in rows]
    print(classification_report(gold, preds, labels=CATEGORIES, zero_division=0))
    print(f"macro F1: {f1_score(gold, preds, average='macro', labels=CATEGORIES, zero_division=0):.3f}")


if __name__ == "__main__":
    main()
