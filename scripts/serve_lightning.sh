#!/usr/bin/env bash
# Nemotron 3.5 Lightning on vLLM (needs vLLM >= 0.27.1, 80GB GPU).
# Flags from the model card. Lower --max-model-len / GPU_UTIL if the triage model doesn't fit next to it.
# GPU_UTIL is a fraction of the whole GPU: 0.82 is about 66 GB on 80 GB. On an H200 (141 GB) use
# GPU_UTIL=0.55 (about 78 GB), which leaves room for triage and a later LoRA run.
# The first start compiles FlashInfer kernels and can take several minutes; later starts use the cache.
source "$(dirname "$0")/cuda_env.sh"
vllm serve nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16 \
  --port 8000 \
  --gpu-memory-utilization "${GPU_UTIL:-0.82}" \
  --max-model-len 32768 \
  --enable-prefix-caching \
  --async-scheduling \
  --mamba-backend flashinfer \
  --mamba-ssm-cache-dtype float16 \
  --reasoning-parser nemotron_v3 \
  --tool-call-parser qwen3_coder \
  --enable-auto-tool-choice
