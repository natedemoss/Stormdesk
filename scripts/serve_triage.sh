#!/usr/bin/env bash
# Fine-tuned triage model (~1.7B) on the same GPU, small memory slice.
# Defaults to the published fine-tune (v2, macro F1 0.755 on HumAID; see training/MODEL_CARD.md).
# To serve a locally retrained copy instead: MODEL=training/outputs/stormdesk-triage bash scripts/serve_triage.sh
# GPU_UTIL is a fraction of the whole GPU: 0.12 is about 10 GB on an 80 GB card. On a 24 GB card
# (L4, A10) 0.12 is too small for the 3.4 GB of weights, so use GPU_UTIL=0.5 there.
source "$(dirname "$0")/cuda_env.sh"
MODEL=${MODEL:-ndemoss28/stormdesks-triage}
vllm serve "$MODEL" \
  --port 8001 \
  --served-model-name stormdesk-triage \
  --gpu-memory-utilization "${GPU_UTIL:-0.12}" \
  --max-model-len 1024
