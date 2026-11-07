#!/bin/bash
# Проверка и автоматическое создание re-export файла для API route
# Использование: bash check-reexport.sh <file_path>

FILE_PATH="$1"

# Проверяем, что это файл в src/app/api/**/route.ts
if ! echo "$FILE_PATH" | grep -qE 'src/app/api/.*/route\.ts$'; then
    exit 0
fi

# Извлекаем относительный путь от src/app/api/
# Обрабатываем как абсолютные, так и относительные пути
REL_PATH=$(echo "$FILE_PATH" | sed -E 's|^.*/src/app/api/||; s|^src/app/api/||')
APP_FILE="app/api/$REL_PATH"

# Если re-export файл уже существует, проверяем актуальность
if [ -f "$APP_FILE" ]; then
    # Извлекаем экспорты из исходного файла
    SRC_EXPORTS=$(grep -oE 'export (async )?function (GET|POST|PUT|PATCH|DELETE|OPTIONS)' "$FILE_PATH" 2>/dev/null | grep -oE '(GET|POST|PUT|PATCH|DELETE|OPTIONS)' | sort -u | tr '\n' ' ' | sed 's/ $//')

    # Проверяем, что все экспорты есть в re-export файле
    MISSING=""
    for EXPORT in $SRC_EXPORTS; do
        if ! grep -q "$EXPORT" "$APP_FILE" 2>/dev/null; then
            MISSING="$MISSING $EXPORT"
        fi
    done

    if [ -n "$MISSING" ]; then
        echo "⚠ Re-export устарел: $APP_FILE"
        echo "   Отсутствуют:$MISSING"
        # Пересоздаём файл
        IMPORT_PATH="@/app/api/$(echo "$REL_PATH" | sed 's|/route.ts||')/route"
        EXPORTS_LIST=$(echo "$SRC_EXPORTS" | tr ' ' ', ')
        echo "export { $EXPORTS_LIST } from '$IMPORT_PATH'" > "$APP_FILE"
        echo "✓ Обновлён re-export: $APP_FILE"
    fi
    exit 0
fi

# Создаём директорию если нужно
mkdir -p "$(dirname "$APP_FILE")"

# Извлекаем экспорты из исходного файла
EXPORTS=$(grep -oE 'export (async )?function (GET|POST|PUT|PATCH|DELETE|OPTIONS)' "$FILE_PATH" 2>/dev/null | grep -oE '(GET|POST|PUT|PATCH|DELETE|OPTIONS)' | sort -u | tr '\n' ', ' | sed 's/,$//')

if [ -z "$EXPORTS" ]; then
    echo "⚠ Нет HTTP методов в $FILE_PATH"
    exit 0
fi

# Формируем import path
IMPORT_PATH="@/app/api/$(echo "$REL_PATH" | sed 's|/route.ts||')/route"

# Создаём re-export файл
echo "export { $EXPORTS } from '$IMPORT_PATH'" > "$APP_FILE"
echo "✓ Создан re-export: $APP_FILE"