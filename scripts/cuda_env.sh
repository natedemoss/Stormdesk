# Sourced by the serve scripts. vLLM's FlashInfer kernels compile on first use and need
# nvcc; Brev VMs ship the driver but no CUDA toolkit (found on the 2026-10-13 L4 test).
# brev_setup.sh installs the toolkit; this points vLLM at it.
if [ -z "${CUDA_HOME:-}" ]; then
  for d in /usr/local/cuda $(ls -d /usr/local/cuda-* 2>/dev/null | sort -V -r); do
    if [ -x "$d/bin/nvcc" ]; then export CUDA_HOME="$d"; break; fi
  done
fi
if [ -n "${CUDA_HOME:-}" ]; then
  export PATH="$CUDA_HOME/bin:$PATH"
else
  echo "warning: no nvcc found; vLLM will fail when FlashInfer compiles. Run scripts/brev_setup.sh" >&2
fi
