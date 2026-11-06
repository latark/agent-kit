#!/bin/bash
# PostToolUse hook: проверяет синхронность триады .env-файлов.
# Правило (память проекта): .env.example / .env.local / .env.production должны иметь
# идентичную структуру — одинаковые ключи в одинаковом порядке и идентичные комментарии.
# Отличаться могут ТОЛЬКО значения справа от `=`.
# Хук неблокирующий — только репортит дельту в транскрипт.
set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

# Реагируем только на правки файлов из триады
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
    echo "ℹ️ .env-sync: файл $(basename "$f") отсутствует — проверку пропускаю"
    exit 0
  fi
done

# Нормализация: и активное `KEY=value`, и закомментированное `#KEY=value` → `KEY=`
# (закомментирован ключ или нет + его значение — это env-специфика, её игнорируем).
# Prose-комментарии (`# текст`) и пустые строки остаются как есть — они должны совпадать.
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
  report+=$'\n--- .env.example (<) ↔ .env.local (>) ---\n'
  report+=$(diff "$tmp_ex" "$tmp_lo" || true)
  report+=$'\n'
fi

if ! diff -q "$tmp_ex" "$tmp_pr" >/dev/null; then
  drift=1
  report+=$'\n--- .env.example (<) ↔ .env.production (>) ---\n'
  report+=$(diff "$tmp_ex" "$tmp_pr" || true)
  report+=$'\n'
fi

if [ "$drift" -eq 1 ]; then
  echo "⚠️ .env-sync: структура .env-файлов рассинхронизирована."
  echo "   Ключи, их порядок и комментарии должны совпадать во всех трёх файлах — отличаться могут только значения."
  echo "$report"
  echo "Приведи файлы к идентичной структуре (см. память проекта: .env files sync)."
fi

exit 0
