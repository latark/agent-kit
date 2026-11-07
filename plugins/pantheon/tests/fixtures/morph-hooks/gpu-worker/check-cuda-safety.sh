#!/bin/bash
# PostToolUse hook: warns about CUDA-before-fork dangerous patterns in Python files.
#
# Context (CLAUDE.md -> "CUDA + fork() SAFETY"): initializing CUDA in the parent process
# BEFORE mp.fork() silently drops the GPU subprocess to CPUExecutionProvider - 0.3 FPS instead of 24+,
# without a single error. Known UNSAFE calls: onnxruntime.get_available_providers()
# (calls cudaGetDeviceCount), av.CodecContext.open() with GPU codecs.
#
# The hook does NOT block - warning only: these patterns are legitimate in a child subprocess and in main
# after fork, the parent-pre-fork path cannot be told apart statically. The decision is for cuda-safety-reviewer.
#
# torch.cuda.* is DELIBERATELY not checked - it is in ~8 files of legitimate code (cuda_stream,
# torch_io_binding etc., all in the GPU subprocess after fork), grep on it = pure noise.
set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

case "$file_path" in
  *.py) ;;
  *) exit 0 ;;
esac

[ -f "$file_path" ] || exit 0

# Strip # comments and triple-quoted docstrings - the code has many NOTE/CRITICAL explanations
# of why this must NOT be done; without this the hook fires on safe files.
strip_noncode() {
  awk '
  {
    line = $0
    sub(/#.*/, "", line)
    n = gsub(/"""/, "&", line)
    if (indoc) { if (n % 2 == 1) indoc = 0; next }
    if (n % 2 == 1) { indoc = 1; next }
    print line
  }' "$1"
}

code=$(strip_noncode "$file_path")
base=$(basename "$file_path")
warned=0

if echo "$code" | grep -qE 'get_available_providers[[:space:]]*\('; then
  echo "[WARN] CUDA-safety: call to get_available_providers() in $base"
  echo "   It calls cudaGetDeviceCount() -> initializes CUDA. If the file runs in"
  echo "   the parent process BEFORE mp.fork(), the GPU subprocess falls to CPU mode (0.3 FPS instead of 24+)."
  echo "   Safe alternative: onnxruntime.get_all_providers()."
  warned=1
fi

if echo "$code" | grep -qE 'CodecContext.*\.open[[:space:]]*\(' \
  || echo "$code" | grep -qE 'h264_nvenc.*\.open[[:space:]]*\('; then
  echo "[WARN] CUDA-safety: CodecContext.open() with a GPU codec in $base"
  echo "   open() on an NVENC codec initializes CUDA. Use the deferred-init pattern"
  echo "   (isolated subprocess probe), as in patches/aiortc_h264_nvenc.py."
  warned=1
fi

if [ "$warned" -eq 1 ]; then
  echo ""
  echo "-> Run the cuda-safety-reviewer agent - make sure the pattern is not on the parent pre-fork path."
  echo "  Details: CLAUDE.md -> \"CUDA + fork() SAFETY\"."
fi

exit 0
