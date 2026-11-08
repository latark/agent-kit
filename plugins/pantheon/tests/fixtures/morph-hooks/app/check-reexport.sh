#!/bin/bash
# Check and automatically create the re-export file for an API route
# Usage: bash check-reexport.sh <file_path>

FILE_PATH="$1"

# Check that this is a file in src/app/api/**/route.ts
if ! echo "$FILE_PATH" | grep -qE 'src/app/api/.*/route\.ts$'; then
    exit 0
fi

# Extract the path relative to src/app/api/
# Handle both absolute and relative paths
REL_PATH=$(echo "$FILE_PATH" | sed -E 's|^.*/src/app/api/||; s|^src/app/api/||')
APP_FILE="app/api/$REL_PATH"

# If the re-export file already exists, check that it is up to date
if [ -f "$APP_FILE" ]; then
    # Extract exports from the source file
    SRC_EXPORTS=$(grep -oE 'export (async )?function (GET|POST|PUT|PATCH|DELETE|OPTIONS)' "$FILE_PATH" 2>/dev/null | grep -oE '(GET|POST|PUT|PATCH|DELETE|OPTIONS)' | sort -u | tr '\n' ' ' | sed 's/ $//')

    # Check that all exports are in the re-export file
    MISSING=""
    for EXPORT in $SRC_EXPORTS; do
        if ! grep -q "$EXPORT" "$APP_FILE" 2>/dev/null; then
            MISSING="$MISSING $EXPORT"
        fi
    done

    if [ -n "$MISSING" ]; then
        echo "[WARN] Re-export is stale: $APP_FILE"
        echo "   Missing:$MISSING"
        # Recreate the file
        IMPORT_PATH="@/app/api/$(echo "$REL_PATH" | sed 's|/route.ts||')/route"
        EXPORTS_LIST=$(echo "$SRC_EXPORTS" | tr ' ' ', ')
        echo "export { $EXPORTS_LIST } from '$IMPORT_PATH'" > "$APP_FILE"
        echo "[OK] Updated re-export: $APP_FILE"
    fi
    exit 0
fi

# Create the directory if needed
mkdir -p "$(dirname "$APP_FILE")"

# Extract exports from the source file
EXPORTS=$(grep -oE 'export (async )?function (GET|POST|PUT|PATCH|DELETE|OPTIONS)' "$FILE_PATH" 2>/dev/null | grep -oE '(GET|POST|PUT|PATCH|DELETE|OPTIONS)' | sort -u | tr '\n' ', ' | sed 's/,$//')

if [ -z "$EXPORTS" ]; then
    echo "[WARN] No HTTP methods in $FILE_PATH"
    exit 0
fi

# Build the import path
IMPORT_PATH="@/app/api/$(echo "$REL_PATH" | sed 's|/route.ts||')/route"

# Create the re-export file
echo "export { $EXPORTS } from '$IMPORT_PATH'" > "$APP_FILE"
echo "[OK] Created re-export: $APP_FILE"
