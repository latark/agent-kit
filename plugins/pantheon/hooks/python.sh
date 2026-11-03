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
# Остальные события (PostToolUse, Stop, UserPromptSubmit, SessionStart) — код 0 без вывода: код 2 на Stop или
# UserPromptSubmit сам мешал бы работе. Защитой из них служат только Stop-хуки ролей (проверка перед сдачей, DONE-02):
# без скрипта они отпускают разработчика без проверки, и след остаётся только строкой в журнале (ниже).
# Так же — пропавший файл скрипта (metis-0330 F3: переименовали, удалили, сломанный кэш плагина). Python на нём
# выходит с кодом 2, а Claude Code читает 2 как запрет: Stop не давал бы закончить ход, UserPromptSubmit глотал бы
# сообщения владельца — во всех окнах сразу. Теперь до запуска: нет файла <…>.py, он пустой (обрезанный кэш: пустой
# скрипт Python выполнил бы молча с кодом 0 — проверки не было бы) или не читается — PreToolUse код 2 с причиной,
# остальные события код 0. Событие узнаётся по "hook_event_name" в stdin; пустой или
# мусорный stdin считается не-PreToolUse (код 0): Claude Code это поле шлёт всегда. Хук отключают правкой записи
# в hooks.json, а не переименованием файла.
# Каждый такой отказ — строка «время<TAB>launcher<TAB>событие<TAB>что» в ~/.local/state/pantheon/logs/guard-failures.log
# (без текста события): её считает сводка планового прохода. Журнал недоступен (нет HOME, папка не пишется) — код 0
# остальных событий идёт со строкой причины в stderr хука (видна в `claude --debug`), а сводка его не увидит.
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

# Отказ запускателя: причина $1 (для журнала), текст для PreToolUse $2. stdin читает только здесь — exec ниже
# получает его нетронутым.
fail() {
    ev=other
    if /usr/bin/grep -Eq '"hook_event_name"[[:space:]]*:[[:space:]]*"PreToolUse"'; then
        ev=PreToolUse
    fi
    logged=
    if [ -n "$HOME" ]; then
        log=$HOME/.local/state/pantheon/logs
        { /bin/mkdir -p "$log" && printf '%s\tlauncher\t%s\t%s\n' "$(/bin/date +%Y-%m-%dT%H:%M:%S)" "$ev" "$1" \
            >>"$log/guard-failures.log"; } 2>/dev/null && logged=1
    fi
    if [ "$ev" = PreToolUse ]; then
        printf '%s\n' "$2" >&2
        exit 2
    fi
    if [ -z "$logged" ]; then
        printf 'python.sh: %s — код 0 без проверки, а строку в guard-failures.log записать не удалось\n' "$1" >&2
    fi
    exit 0
}

if [ -z "$py" ]; then
    fail "no-python ${1##*/}" "хук ${1##*/}: нужен Python 3.11+, а его нет (python3.14…3.11 в /opt/homebrew/bin, /usr/local/bin, python.org и PATH; python3 из PATH старше 3.11). Действие остановлено. Поставить: brew install python@3.14. Системный /usr/bin/python3 на macOS — 3.9, он не подходит."
fi
case $1 in
    *.py)
        if ! [ -f "$1" ] || ! [ -r "$1" ] || ! [ -s "$1" ]; then
            fail "no-script ${1##*/}" "хук ${1##*/}: файла скрипта нет, он пустой или не читается ($1). Действие остановлено: защита не запустилась. Переустановить плагин: claude plugin update <плагин>@agent-kit; хук отключают правкой hooks.json, а не переименованием файла."
        fi
        ;;
esac
exec "$py" -I "$@"
