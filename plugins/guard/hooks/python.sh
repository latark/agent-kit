#!/bin/sh
# Запускатель хуков на Python 3.11+ (metis-0571): /bin/sh python.sh <скрипт.py> [аргументы…] → exec <python> -I <скрипт> ….
# Хуки звали python3 из PATH. В окнах это бывает системный /usr/bin/python3 3.9: без tomllib guard не читал policy.toml,
# и правило corpus-role молча пропускало. Теперь интерпретатор выбирается здесь, одинаково в любом окружении.
#
# Порядок поиска, берётся первый найденный:
#   1. python3.14, 3.13, 3.12, 3.11 (новее — раньше) в /opt/homebrew/bin, /usr/local/bin, у python.org
#      (/Library/Frameworks/Python.framework/Versions/<v>/bin), затем в папках PATH. Имя называет версию, поэтому
#      проверочного запуска нет: хук на каждое действие не платит лишним процессом. Относительные папки PATH пропускаются.
#   2. python3 из PATH, если он 3.11+ (проверочный запуск): для версий новее списка.
# Не нашёл — событие PreToolUse получает код 2 и причину в stderr: действие остановлено, а не пропущено молча.
# Остальные события (PostToolUse, Stop, UserPromptSubmit, SessionStart) — код 0 без вывода: они ничего не защищают,
# а код 2 на Stop или UserPromptSubmit сам мешал бы работе.
#
# Копии файла — plugins/guard/hooks/python.sh и plugins/pantheon/hooks/python.sh: плагины ставятся порознь.
# Тест guard tests/test_hooks_json.py сверяет, что копии одинаковые. Строки FW= и DIRS= тест подменяет.
FW=/Library/Frameworks/Python.framework/Versions
DIRS=/opt/homebrew/bin:/usr/local/bin

py=
old_ifs=$IFS
IFS=:
set -f
for v in 3.14 3.13 3.12 3.11; do
    # слова через пробел: двоеточие делит только раскрытые значения. Через `$DIRS:$FW…:$PATH` dash склеивал места
    # списка в одно слово (metis-0194)
    for d in $DIRS $FW/$v/bin $PATH; do
        case $d in
            /*) ;;
            *) continue ;;
        esac
        if [ -f "$d/python$v" ] && [ -x "$d/python$v" ]; then
            py=$d/python$v
            break 2
        fi
    done
done
set +f
IFS=$old_ifs

if [ -z "$py" ]; then
    p=$(command -v python3 2>/dev/null)
    case $p in
        /*) "$p" -I -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1 && py=$p ;;
    esac
fi

if [ -z "$py" ]; then
    if /usr/bin/grep -Eq '"hook_event_name"[[:space:]]*:[[:space:]]*"PreToolUse"'; then
        printf '%s\n' "хук ${1##*/}: нужен Python 3.11+, а его нет (python3.14…3.11 в /opt/homebrew/bin, /usr/local/bin, python.org и PATH; python3 из PATH старше 3.11). Действие остановлено. Поставить: brew install python@3.14. Системный /usr/bin/python3 на macOS — 3.9, он не подходит." >&2
        exit 2
    fi
    exit 0
fi
exec "$py" -I "$@"
