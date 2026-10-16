# Поиск Python 3.11+ для bin/pantheon и bin/pantheon-tick (подключается через `.`, сама ничего не запускает).
# Системный /usr/bin/python3 на macOS — 3.9: у него нет tomllib, pantheon на нём падал трассой.
# Порядок: PANTHEON_PYTHON (его ставит родитель — дочерние pantheon идут тем же интерпретатором), python3 из PATH,
# python3.14…3.11 из PATH, затем каталоги PANTHEON_PY_DIRS (по умолчанию Homebrew и python.org).
_py_ok() {
    [ -n "$1" ] && [ -x "$1" ] && "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

find_python() {
    if _py_ok "$PANTHEON_PYTHON"; then
        printf '%s\n' "$PANTHEON_PYTHON"
        return 0
    fi
    p=$(command -v python3 2>/dev/null)
    if _py_ok "$p"; then
        printf '%s\n' "$p"
        return 0
    fi
    for v in 3.14 3.13 3.12 3.11; do
        p=$(command -v "python$v" 2>/dev/null)
        if _py_ok "$p"; then
            printf '%s\n' "$p"
            return 0
        fi
    done
    dirs=${PANTHEON_PY_DIRS:-"/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/*/bin"}
    old_ifs=$IFS
    IFS=:
    set -f
    for pat in $dirs; do
        set +f
        IFS=$old_ifs
        for d in $pat; do
            for v in 3.14 3.13 3.12 3.11; do
                if _py_ok "$d/python$v"; then
                    printf '%s\n' "$d/python$v"
                    return 0
                fi
            done
        done
        IFS=:
        set -f
    done
    set +f
    IFS=$old_ifs
    return 1
}

NO_PYTHON_MSG="pantheon: нужен Python 3.11+ (его нет в PATH и в стандартных местах). Поставить: brew install python@3.14 или python.org/downloads; системный /usr/bin/python3 на macOS — 3.9, он не подходит."
