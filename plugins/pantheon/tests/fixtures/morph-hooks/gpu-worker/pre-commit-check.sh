#!/bin/bash
# Полная проверка gpu-worker перед коммитом. Блокирует коммит при нарушениях.
#
# Ruff (format + lint) уже покрыт .pre-commit-config.yaml (нативный git pre-commit).
# Этот скрипт — про правило #1 проекта, которое ruff не ловит: CUDA + fork() safety
# (CLAUDE.md → "CUDA + fork() SAFETY"). Проектно-специфичный архитектурный gate,
# по аналогии с FSD-проверкой в pre-commit-check.sh основного App.
set -e

# Вырезает # комментарии и triple-quoted docstrings — иначе греп ловит NOTE/CRITICAL
# пояснения, объясняющие почему так делать НЕЛЬЗЯ.
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

echo "🔍 CUDA + fork() safety: поиск get_available_providers() в app/..."

VIOLATIONS=0
while IFS= read -r f; do
  if strip_noncode "$f" | grep -qE 'get_available_providers[[:space:]]*\('; then
    echo "❌ $f — вызов get_available_providers() (инициализирует CUDA до возможного fork)"
    VIOLATIONS=$((VIOLATIONS + 1))
  fi
done < <(find app -name "*.py" 2>/dev/null | grep -v __pycache__)

if [ "$VIOLATIONS" -gt 0 ]; then
  echo ""
  echo "BLOCK: Найдено $VIOLATIONS нарушений CUDA + fork() safety."
  echo "get_available_providers() вызывает cudaGetDeviceCount() → инициализирует CUDA."
  echo "В parent-процессе до mp.fork() это роняет GPU subprocess в CPU mode (0.3 FPS)."
  echo "Используй onnxruntime.get_all_providers(). См. CLAUDE.md → CUDA + fork() SAFETY."
  exit 1
fi
echo "✓ CUDA + fork() safety OK"

echo ""
echo "✅ Все проверки пройдены"
