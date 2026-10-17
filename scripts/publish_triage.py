"""Copy the trained triage model to its public Hugging Face repo, with training/MODEL_CARD.md as its card.

    pip install -U huggingface_hub
    hf auth login                       # a token with write access; you type it, it is never stored in the repo
    python scripts/publish_triage.py

The weights are copied from the earlier private repo; nothing is retrained.
"""
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

SOURCE = "ndemoss28/stormdesk-triage"
TARGET = "ndemoss28/stormdesks-triage"
CARD = Path(__file__).resolve().parent.parent / "training" / "MODEL_CARD.md"

api = HfApi()
print(f"Downloading {SOURCE} (about 3.5 GB)")
src = snapshot_download(SOURCE)
api.create_repo(TARGET, private=False, exist_ok=True)
print(f"Uploading to {TARGET}")
api.upload_folder(folder_path=src, repo_id=TARGET, ignore_patterns=["README.md", ".gitattributes"],
                  commit_message="StormDesk's triage: Qwen3-1.7B fine-tuned on HumAID")
api.upload_file(path_or_fileobj=str(CARD), path_in_repo="README.md", repo_id=TARGET,
                commit_message="Model card")
print(f"Done: https://huggingface.co/{TARGET}")
