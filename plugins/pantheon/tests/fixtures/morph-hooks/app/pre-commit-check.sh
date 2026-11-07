#!/bin/bash
# Full project check before commit
# Blocks the commit on violations

set -e

echo ">> Checking re-exports..."

MISSING_REEXPORTS=0
for SRC in $(find src/app/api -name 'route.ts' 2>/dev/null); do
    REL=$(echo "$SRC" | sed 's|src/app/api/||')
    APP="app/api/$REL"
    if [ ! -f "$APP" ]; then
        echo "[FAIL] Missing: $APP"
        MISSING_REEXPORTS=$((MISSING_REEXPORTS+1))
    fi
done

if [ $MISSING_REEXPORTS -gt 0 ]; then
    echo ""
    echo "BLOCK: Found $MISSING_REEXPORTS missing re-exports."
    echo "Create them with: bash .claude/hooks/check-reexport.sh <path_to_route.ts>"
    exit 1
fi
echo "[OK] All re-exports in place"

echo ""
echo ">> Checking FSD architecture..."

FSD_VIOLATIONS=0

# shared does not import from upper layers
if grep -rqE "from ['\"]@/(entities|features|widgets|pages|app)/" src/shared/ 2>/dev/null; then
    echo "[FAIL] shared imports from upper layers:"
    grep -rnE "from ['\"]@/(entities|features|widgets|pages|app)/" src/shared/ 2>/dev/null | head -5
    FSD_VIOLATIONS=$((FSD_VIOLATIONS+1))
fi

# entities does not import from features/widgets/pages/app
if grep -rqE "from ['\"]@/(features|widgets|pages|app)/" src/entities/ 2>/dev/null; then
    echo "[FAIL] entities imports from upper layers:"
    grep -rnE "from ['\"]@/(features|widgets|pages|app)/" src/entities/ 2>/dev/null | head -5
    FSD_VIOLATIONS=$((FSD_VIOLATIONS+1))
fi

# features does not import from widgets/pages
if grep -rqE "from ['\"]@/(widgets|pages)/" src/features/ 2>/dev/null; then
    echo "[FAIL] features imports from widgets/pages:"
    grep -rnE "from ['\"]@/(widgets|pages)/" src/features/ 2>/dev/null | head -5
    FSD_VIOLATIONS=$((FSD_VIOLATIONS+1))
fi

# widgets does not import from pages
if grep -rqE "from ['\"]@/pages/" src/widgets/ 2>/dev/null; then
    echo "[FAIL] widgets imports from pages:"
    grep -rnE "from ['\"]@/pages/" src/widgets/ 2>/dev/null | head -5
    FSD_VIOLATIONS=$((FSD_VIOLATIONS+1))
fi

if [ $FSD_VIOLATIONS -gt 0 ]; then
    echo ""
    echo "BLOCK: Found $FSD_VIOLATIONS FSD violations. Fix them before commit."
    exit 1
fi
echo "[OK] FSD architecture is valid"

echo ""
echo "[OK] All checks passed"
