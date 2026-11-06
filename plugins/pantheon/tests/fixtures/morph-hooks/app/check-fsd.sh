#!/bin/bash
# Проверка FSD архитектуры для одного файла
# Использование: bash check-fsd.sh <file_path>

FILE_PATH="$1"
VIOLATIONS=0

# Определяем слой файла
get_layer() {
    echo "$1" | sed -n 's|.*/src/\(shared\|entities\|features\|widgets\|pages\|app\)/.*|\1|p'
}

LAYER=$(get_layer "$FILE_PATH")

# Если файл не в FSD слое, пропускаем
if [ -z "$LAYER" ]; then
    exit 0
fi

# Проверка shared — не может импортировать из верхних слоёв
if [ "$LAYER" = "shared" ]; then
    WRONG_IMPORTS=$(grep -nE "from ['\"]@/(entities|features|widgets|pages|app)/" "$FILE_PATH" 2>/dev/null)
    if [ -n "$WRONG_IMPORTS" ]; then
        echo "⚠️ FSD: shared не может импортировать из верхних слоёв"
        echo "$WRONG_IMPORTS" | head -5
        VIOLATIONS=$((VIOLATIONS+1))
    fi
fi

# Проверка entities — не может импортировать из features/widgets/pages/app
if [ "$LAYER" = "entities" ]; then
    WRONG_IMPORTS=$(grep -nE "from ['\"]@/(features|widgets|pages|app)/" "$FILE_PATH" 2>/dev/null)
    if [ -n "$WRONG_IMPORTS" ]; then
        echo "⚠️ FSD: entities не может импортировать из features/widgets/pages/app"
        echo "$WRONG_IMPORTS" | head -5
        VIOLATIONS=$((VIOLATIONS+1))
    fi
fi

# Проверка features — не может импортировать из widgets/pages
# Исключение: @/app/actions/ разрешено для Server Actions
if [ "$LAYER" = "features" ]; then
    WRONG_IMPORTS=$(grep -nE "from ['\"]@/(widgets|pages)/" "$FILE_PATH" 2>/dev/null)
    if [ -n "$WRONG_IMPORTS" ]; then
        echo "⚠️ FSD: features не может импортировать из widgets/pages"
        echo "$WRONG_IMPORTS" | head -5
        VIOLATIONS=$((VIOLATIONS+1))
    fi

    # Проверка cross-feature imports
    CURRENT_FEATURE=$(echo "$FILE_PATH" | sed -n 's|.*/src/features/\([^/]*\)/.*|\1|p')
    if [ -n "$CURRENT_FEATURE" ]; then
        # Ищем импорты из других features (но не из текущей)
        OTHER_FEATURE_IMPORTS=$(grep -nE "from ['\"]@/features/" "$FILE_PATH" 2>/dev/null | grep -v "@/features/$CURRENT_FEATURE")
        if [ -n "$OTHER_FEATURE_IMPORTS" ]; then
            echo "⚠️ FSD: features не может импортировать другие features"
            echo "$OTHER_FEATURE_IMPORTS" | head -5
            VIOLATIONS=$((VIOLATIONS+1))
        fi
    fi
fi

# Проверка widgets — не может импортировать из pages
if [ "$LAYER" = "widgets" ]; then
    WRONG_IMPORTS=$(grep -nE "from ['\"]@/pages/" "$FILE_PATH" 2>/dev/null)
    if [ -n "$WRONG_IMPORTS" ]; then
        echo "⚠️ FSD: widgets не может импортировать из pages"
        echo "$WRONG_IMPORTS" | head -5
        VIOLATIONS=$((VIOLATIONS+1))
    fi
fi

if [ $VIOLATIONS -eq 0 ]; then
    exit 0
fi

exit 0  # Не блокируем, только предупреждаем