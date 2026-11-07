#!/bin/bash
# PostToolUse hook: checks that the triad of .env files is in sync.
# Rule (project memory): .env.example / .env.local / .env.production must have
# identical structure - the same keys in the same order and identical comments.
# ONLY the values to the right of `=` may differ.
# The hook does not block - it only reports the delta to the transcript.
set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

# React only to edits of files from the triad
case "$(basename "$file_path")" in
  .env.example | .env.local | .env.production) ;;
  *) exit 0 ;;
esac

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
EXAMPLE="$PROJECT_DIR/.env.example"
LOCAL="$PROJECT_DIR/.env.local"
PROD="$PROJECT_DIR/.env.production"

for f in "$EXAMPLE" "$LOCAL" "$PROD"; do
  if [ ! -f "$f" ]; then
    echo "[INFO] .env-sync: file $(basename "$f") is missing - skipping the check"
    exit 0
  fi
done

# Normalization: both active `KEY=value` and commented `#KEY=value` -> `KEY=`
# (whether the key is commented out, plus its value, is env-specific and ignored).
# Prose comments (`# text`) and empty lines stay as they are - they must match.
normalize() {
  sed -E 's/^([[:space:]]*)#?[[:space:]]*((export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=).*/\1\2/' "$1"
}

tmp_ex=$(mktemp)
tmp_lo=$(mktemp)
tmp_pr=$(mktemp)
trap 'rm -f "$tmp_ex" "$tmp_lo" "$tmp_pr"' EXIT

normalize "$EXAMPLE" >"$tmp_ex"
normalize "$LOCAL" >"$tmp_lo"
normalize "$PROD" >"$tmp_pr"

drift=0
report=""

if ! diff -q "$tmp_ex" "$tmp_lo" >/dev/null; then
  drift=1
  report+=$'\n--- .env.example (<) <-> .env.local (>) ---\n'
  report+=$(diff "$tmp_ex" "$tmp_lo" || true)
  report+=$'\n'
fi

if ! diff -q "$tmp_ex" "$tmp_pr" >/dev/null; then
  drift=1
  report+=$'\n--- .env.example (<) <-> .env.production (>) ---\n'
  report+=$(diff "$tmp_ex" "$tmp_pr" || true)
  report+=$'\n'
fi

if [ "$drift" -eq 1 ]; then
  echo "[WARN] .env-sync: the structure of the .env files is out of sync."
  echo "   Keys, their order and comments must match in all three files - only values may differ."
  echo "$report"
  echo "Bring the files to identical structure (see project memory: .env files sync)."
fi

exit 0
