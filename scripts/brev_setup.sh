#!/usr/bin/env bash
# One-shot setup on a fresh Brev GPU box (pick "VM Mode", not Docker or Kubernetes).
#   bash scripts/brev_setup.sh           # serving: system packages, CUDA toolkit, vLLM, weights, offline data
#   bash scripts/brev_setup.sh --train   # also the Unsloth env + HumAID data (only to retrain triage)
#
# Tested on a Brev L4 VM (2026-10-13). What a fresh Brev VM was missing:
#   - build-essential, python3-dev: Triton and torch.compile build kernels on first start
#   - the CUDA toolkit (nvcc): FlashInfer compiles kernels on first use; the VM has only the driver
# Weight downloads start in the background first, since Lightning (~60 GB) takes longest.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
TRAIN=0; [ "${1:-}" = "--train" ] && TRAIN=1

echo "== GPU"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv

echo "== System packages"
sudo apt-get update -q
sudo apt-get install -y -q build-essential python3-dev python3-venv wget

echo "== Serving env (.venv-serve)"
python3 -m venv .venv-serve
.venv-serve/bin/pip install -q -U pip
.venv-serve/bin/pip install -q "vllm>=0.27.1" -r requirements.txt "huggingface_hub[cli]"

echo "== Weight downloads (background, logs/download_*.log)"
dl() { nohup .venv-serve/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('$1')" \
  > "logs/download_$2.log" 2>&1 & }
dl nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16 lightning
dl ndemoss28/stormdesks-triage triage

echo "== CUDA toolkit matching vLLM's torch build"
CUDA_VER=$(.venv-serve/bin/python -c "import torch; print(torch.version.cuda)")
if ls -d /usr/local/cuda-"$CUDA_VER" >/dev/null 2>&1; then
  echo "already installed: /usr/local/cuda-$CUDA_VER"
else
  wget -q -O /tmp/cuda-keyring.deb \
    https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
  sudo dpkg -i /tmp/cuda-keyring.deb
  sudo apt-get update -q
  sudo apt-get install -y -q "cuda-toolkit-${CUDA_VER/./-}"
fi
export CUDA_HOME=/usr/local/cuda-$CUDA_VER
"$CUDA_HOME/bin/nvcc" --version | tail -1

echo "== Offline data (counties in stormdesk/config.py COUNTIES)"
.venv-serve/bin/python -m stormdesk.db --init --load-samples
# Roads, gazetteer, shelters, alerts; DriveNC closures too when DRIVENC_API_KEY is in .env
.venv-serve/bin/python sync/sync_all.py

if [ "$TRAIN" = 1 ]; then
  echo "== Training env (.venv-train) + HumAID"
  python3 -m venv .venv-train
  .venv-train/bin/pip install -q -U pip
  .venv-train/bin/pip install -q unsloth trl "datasets>=2.18" scikit-learn openai python-dotenv requests pydantic jsonschema
  .venv-train/bin/python training/prepare_humaid.py --max-per-class 3000
fi

echo "== Waiting for weight downloads"
wait
du -sh ~/.cache/huggingface/hub/* 2>/dev/null || true

cat <<'EOF'

Setup done. Next (see BREV_DAY.md):
  1. Serve:      source .venv-serve/bin/activate
                 nohup bash scripts/serve_lightning.sh > logs/lightning.log 2>&1 &
                 nohup bash scripts/serve_triage.sh > logs/triage.log 2>&1 &
                 The first start of each compiles kernels: allow 5 to 10 minutes.
  2. Check:      python scripts/preflight.py
  3. Demo queue: python scripts/reset_demo.py
  4. Sandbox:    bash scripts/openshell_up.sh
EOF
