#!/usr/bin/env bash
# LoRA fine-tune Lightning on the kept dispatch runs, inside NVIDIA's NeMo AutoModel container.
# Stop both vLLM servers first: training needs the whole GPU.
#   pkill -f "vllm serve"
#   bash training/train_lightning_lora.sh
# IMAGE picks the container; Lightning LoRA support landed in AutoModel in August 2026, so use
# 26.08 or newer (check the tags at catalog.ngc.nvidia.com, "nemo-automodel").
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=${IMAGE:-nvcr.io/nvidia/nemo-automodel:26.08.00}
test -s training/data_agent/sft.jsonl || { echo "no training/data_agent/sft.jsonl: run training/collect_trajectories.py first"; exit 1; }
mkdir -p training/outputs logs
docker run --gpus all --rm --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
  -v "$PWD":/work -v "$HOME/.cache/huggingface":/root/.cache/huggingface -w /work \
  "$IMAGE" automodel training/lightning_lora.yaml --nproc-per-node 1 2>&1 | tee logs/lightning_lora.log
