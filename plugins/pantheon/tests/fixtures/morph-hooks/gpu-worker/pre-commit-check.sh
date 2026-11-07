#!/bin/bash
# Full gpu-worker check before commit. Blocks the commit on violations.
#
# Ruff (format + lint) is already covered by .pre-commit-config.yaml (native git pre-commit).
# This script is about project rule #1 that ruff does not catch: CUDA + fork() safety
# (CLAUDE.md -> "CUDA + fork() SAFETY"). A project-specific architecture gate,
# like the FSD check in pre-commit-check.sh of the main App.
set -e

# Strips # comments and triple-quoted docstrings, otherwise grep catches NOTE/CRITICAL
# explanations of why this must NOT be done.
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

echo ">> CUDA + fork() safety: looking for get_available_providers() in app/..."

VIOLATIONS=0
while IFS= read -r f; do
  if strip_noncode "$f" | grep -qE 'get_available_providers[[:space:]]*\('; then
    echo "[FAIL] $f - call to get_available_providers() (initializes CUDA before a possible fork)"
    VIOLATIONS=$((VIOLATIONS + 1))
  fi
done < <(find app -name "*.py" 2>/dev/null | grep -v __pycache__)

if [ "$VIOLATIONS" -gt 0 ]; then
  echo ""
  echo "BLOCK: Found $VIOLATIONS CUDA + fork() safety violations."
  echo "get_available_providers() calls cudaGetDeviceCount() -> initializes CUDA."
  echo "In the parent process before mp.fork() this drops the GPU subprocess to CPU mode (0.3 FPS)."
  echo "Use onnxruntime.get_all_providers(). See CLAUDE.md -> CUDA + fork() SAFETY."
  exit 1
fi
echo "[OK] CUDA + fork() safety OK"

echo ""
echo "[OK] All checks passed"
