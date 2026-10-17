"""Turn HumAID into chat-format JSONL for fine-tuning the triage model.

    python training/prepare_humaid.py --max-per-class 3000
Outputs training/data/{train,val,test}.jsonl
"""
import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stormdesk.triage import CATEGORIES, SYSTEM  # noqa: E402

OUT = Path(__file__).resolve().parent / "data"


def norm(label: str) -> str:
    s = re.sub(r"[^a-z]+", "_", label.lower()).strip("_")
    s = s.replace("don_t", "dont").replace("can_t", "cant")
    return s


def to_example(text: str, label: str) -> dict:
    return {"messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": text},
        {"role": "assistant", "content": json.dumps({"category": label})},
    ], "label": label}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-class", type=int, default=3000, help="cap to balance classes")
    ap.add_argument("--min-per-class", type=int, default=1000,
                    help="repeat examples of smaller classes in train up to this many")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(OUT), help="output folder (default training/data)")
    a = ap.parse_args()
    from datasets import load_dataset
    # The dataset card lists a "dev" split the files do not have; skip that metadata check.
    ds = load_dataset("QCRI/HumAID-all", verification_mode="no_checks")
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    random.seed(a.seed)

    for split, name in [("train", "train"), ("validation", "val"), ("test", "test")]:
        rows = ds[split]
        by_cls = defaultdict(list)
        for r in rows:
            lab = norm(r["class_label"])
            if lab not in CATEGORIES:
                print(f"warning: unexpected label {r['class_label']!r} -> {lab}")
                continue
            by_cls[lab].append(r["tweet_text"])
        out = []
        for lab, texts in by_cls.items():
            random.shuffle(texts)
            cap = a.max_per_class if name == "train" else len(texts)
            picked = texts[:cap]
            if name == "train" and len(picked) < a.min_per_class:
                # e.g. missing_or_found_people has ~250: repeat it so the model sees it enough
                picked = picked + random.choices(picked, k=a.min_per_class - len(picked))
            out += [to_example(t, lab) for t in picked]
        random.shuffle(out)
        with open(out_dir / f"{name}.jsonl", "w") as f:
            for ex in out:
                f.write(json.dumps(ex) + "\n")
        print(name, len(out), Counter(e["label"] for e in out).most_common())


if __name__ == "__main__":
    main()
