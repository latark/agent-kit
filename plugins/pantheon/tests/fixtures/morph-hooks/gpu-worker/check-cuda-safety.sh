#!/bin/bash
# PostToolUse hook: предупреждает о CUDA-before-fork опасных паттернах в Python-файлах.
#
# Контекст (CLAUDE.md → "CUDA + fork() SAFETY"): инициализация CUDA в parent-процессе
# ДО mp.fork() тихо роняет GPU subprocess в CPUExecutionProvider — 0.3 FPS вместо 24+,
# без единой ошибки. Известные UNSAFE-вызовы: onnxruntime.get_available_providers()
# (вызывает cudaGetDeviceCount), av.CodecContext.open() с GPU-кодеками.
#
# Хук НЕ блокирует — только warning: эти паттерны легитимны в child-subprocess и в main
# после fork, статически отличить parent-pre-fork путь нельзя. Решение — за cuda-safety-reviewer.
#
# torch.cuda.* СОЗНАТЕЛЬНО не проверяется — он в ~8 файлах легитимного кода (cuda_stream,
# torch_io_binding и т.д., все в GPU subprocess после fork), греп по нему = сплошной шум.
set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

case "$file_path" in
  *.py) ;;
  *) exit 0 ;;
esac

[ -f "$file_path" ] || exit 0

# Вырезаем # комментарии и triple-quoted docstrings — в коде много NOTE/CRITICAL пояснений,
# объясняющих почему так делать НЕЛЬЗЯ; без этого хук сработает на безопасных файлах.
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
  echo "⚠️ CUDA-safety: вызов get_available_providers() в $base"
  echo "   Он вызывает cudaGetDeviceCount() → инициализирует CUDA. Если файл исполняется в"
  echo "   parent-процессе ДО mp.fork() — GPU subprocess упадёт в CPU mode (0.3 FPS вместо 24+)."
  echo "   Safe-альтернатива: onnxruntime.get_all_providers()."
  warned=1
fi

if echo "$code" | grep -qE 'CodecContext.*\.open[[:space:]]*\(' \
  || echo "$code" | grep -qE 'h264_nvenc.*\.open[[:space:]]*\('; then
  echo "⚠️ CUDA-safety: CodecContext.open() с GPU-кодеком в $base"
  echo "   open() на NVENC-кодеке инициализирует CUDA. Используй deferred-init pattern"
  echo "   (изолированный subprocess probe), как в patches/aiortc_h264_nvenc.py."
  warned=1
fi

if [ "$warned" -eq 1 ]; then
  echo ""
  echo "→ Прогони агент cuda-safety-reviewer — убедись, что паттерн не в parent pre-fork пути."
  echo "  Детали: CLAUDE.md → \"CUDA + fork() SAFETY\"."
fi

exit 0
