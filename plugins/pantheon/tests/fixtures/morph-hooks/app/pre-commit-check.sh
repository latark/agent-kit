#!/bin/bash
# Полная проверка проекта перед коммитом
# Блокирует коммит при нарушениях

set -e

echo "🔍 Проверка re-exports..."

MISSING_REEXPORTS=0
for SRC in $(find src/app/api -name 'route.ts' 2>/dev/null); do
    REL=$(echo "$SRC" | sed 's|src/app/api/||')
    APP="app/api/$REL"
    if [ ! -f "$APP" ]; then
        echo "❌ Отсутствует: $APP"
        MISSING_REEXPORTS=$((MISSING_REEXPORTS+1))
    fi
done

if [ $MISSING_REEXPORTS -gt 0 ]; then
    echo ""
    echo "BLOCK: Найдено $MISSING_REEXPORTS отсутствующих re-exports."
    echo "Создайте их командой: bash .claude/hooks/check-reexport.sh <путь_к_route.ts>"
    exit 1
fi
echo "✓ Все re-exports на месте"

echo ""
echo "🔍 Проверка FSD архитектуры..."

FSD_VIOLATIONS=0

# shared не импортирует из верхних слоёв
if grep -rqE "from ['\"]@/(entities|features|widgets|pages|app)/" src/shared/ 2>/dev/null; then
    echo "❌ shared импортирует из верхних слоёв:"
    grep -rnE "from ['\"]@/(entities|features|widgets|pages|app)/" src/shared/ 2>/dev/null | head -5
    FSD_VIOLATIONS=$((FSD_VIOLATIONS+1))
fi

# entities не импортирует из features/widgets/pages/app
if grep -rqE "from ['\"]@/(features|widgets|pages|app)/" src/entities/ 2>/dev/null; then
    echo "❌ entities импортирует из верхних слоёв:"
    grep -rnE "from ['\"]@/(features|widgets|pages|app)/" src/entities/ 2>/dev/null | head -5
    FSD_VIOLATIONS=$((FSD_VIOLATIONS+1))
fi

# features не импортирует из widgets/pages
if grep -rqE "from ['\"]@/(widgets|pages)/" src/features/ 2>/dev/null; then
    echo "❌ features импортирует из widgets/pages:"
    grep -rnE "from ['\"]@/(widgets|pages)/" src/features/ 2>/dev/null | head -5
    FSD_VIOLATIONS=$((FSD_VIOLATIONS+1))
fi

# widgets не импортирует из pages
if grep -rqE "from ['\"]@/pages/" src/widgets/ 2>/dev/null; then
    echo "❌ widgets импортирует из pages:"
    grep -rnE "from ['\"]@/pages/" src/widgets/ 2>/dev/null | head -5
    FSD_VIOLATIONS=$((FSD_VIOLATIONS+1))
fi

if [ $FSD_VIOLATIONS -gt 0 ]; then
    echo ""
    echo "BLOCK: Найдено $FSD_VIOLATIONS FSD нарушений. Исправьте перед коммитом."
    exit 1
fi
echo "✓ FSD архитектура валидна"

echo ""
echo "✅ Все проверки пройдены"