#!/bin/bash
# FSD architecture check for one file
# Usage: bash check-fsd.sh <file_path>

FILE_PATH="$1"
VIOLATIONS=0

# Find the layer of the file
get_layer() {
    echo "$1" | sed -n 's|.*/src/\(shared\|entities\|features\|widgets\|pages\|app\)/.*|\1|p'
}

LAYER=$(get_layer "$FILE_PATH")

# If the file is not in an FSD layer, skip it
if [ -z "$LAYER" ]; then
    exit 0
fi

# shared check - cannot import from upper layers
if [ "$LAYER" = "shared" ]; then
    WRONG_IMPORTS=$(grep -nE "from ['\"]@/(entities|features|widgets|pages|app)/" "$FILE_PATH" 2>/dev/null)
    if [ -n "$WRONG_IMPORTS" ]; then
        echo "[WARN] FSD: shared cannot import from upper layers"
        echo "$WRONG_IMPORTS" | head -5
        VIOLATIONS=$((VIOLATIONS+1))
    fi
fi

# entities check - cannot import from features/widgets/pages/app
if [ "$LAYER" = "entities" ]; then
    WRONG_IMPORTS=$(grep -nE "from ['\"]@/(features|widgets|pages|app)/" "$FILE_PATH" 2>/dev/null)
    if [ -n "$WRONG_IMPORTS" ]; then
        echo "[WARN] FSD: entities cannot import from features/widgets/pages/app"
        echo "$WRONG_IMPORTS" | head -5
        VIOLATIONS=$((VIOLATIONS+1))
    fi
fi

# features check - cannot import from widgets/pages
# Exception: @/app/actions/ is allowed for Server Actions
if [ "$LAYER" = "features" ]; then
    WRONG_IMPORTS=$(grep -nE "from ['\"]@/(widgets|pages)/" "$FILE_PATH" 2>/dev/null)
    if [ -n "$WRONG_IMPORTS" ]; then
        echo "[WARN] FSD: features cannot import from widgets/pages"
        echo "$WRONG_IMPORTS" | head -5
        VIOLATIONS=$((VIOLATIONS+1))
    fi

    # cross-feature imports check
    CURRENT_FEATURE=$(echo "$FILE_PATH" | sed -n 's|.*/src/features/\([^/]*\)/.*|\1|p')
    if [ -n "$CURRENT_FEATURE" ]; then
        # Look for imports from other features (but not from the current one)
        OTHER_FEATURE_IMPORTS=$(grep -nE "from ['\"]@/features/" "$FILE_PATH" 2>/dev/null | grep -v "@/features/$CURRENT_FEATURE")
        if [ -n "$OTHER_FEATURE_IMPORTS" ]; then
            echo "[WARN] FSD: features cannot import other features"
            echo "$OTHER_FEATURE_IMPORTS" | head -5
            VIOLATIONS=$((VIOLATIONS+1))
        fi
    fi
fi

# widgets check - cannot import from pages
if [ "$LAYER" = "widgets" ]; then
    WRONG_IMPORTS=$(grep -nE "from ['\"]@/pages/" "$FILE_PATH" 2>/dev/null)
    if [ -n "$WRONG_IMPORTS" ]; then
        echo "[WARN] FSD: widgets cannot import from pages"
        echo "$WRONG_IMPORTS" | head -5
        VIOLATIONS=$((VIOLATIONS+1))
    fi
fi

if [ $VIOLATIONS -eq 0 ]; then
    exit 0
fi

exit 0  # Do not block, warn only
