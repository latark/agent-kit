#!/bin/sh
# Оболочка хука guard для демона хуков (metis-0330, этап 2, ступень 2):
#   /bin/sh hookd.sh guard [--managed|--strict]       событие — на stdin, как у guard.py
#
# Без PANTHEON_HOOKD=1 — сразу медленный путь `/bin/sh python.sh guard.py <режим>`: поведение то же, что до демона.
# С флагом — нативный клиент ~/.cache/pantheon/hookd/bin/client-$SRC спрашивает демон (сокет
# ~/.cache/pantheon/hookd/hookd.sock, служба launchd pantheon.svc.hookd) и при любом его сбое сам идёт медленным путём
# (hookd-client.c). Клиент не делает exec: мусорный файл с +x под exec дал бы код 126, то есть отказ во всех окнах.
# Клиента нет, он не исполняется или не запустился (код 126 или 127: файл не тот) — медленный путь здесь, с нетронутым
# stdin: клиент, который не запустился, его не читал. Перед запуском клиент сверяется с меткой client-$SRC.sum
# (SHA-256 собранного файла, её пишет hookd-build.sh в той же закрытой папке): нет метки или файл другой — клиент не
# запускается, медленный путь и пересборка в фоне. Подменённый клиент отвечал бы «пропустить» на всё. Каждый такой
# откат — строка «время<TAB>причина» (no-client, client-sum, client-exec, env) в
# ~/.local/state/pantheon/logs/hookd-fallback.log, без текста события.
# Клиент собирается не в дереве плагина (его сверяет verified.json, бинарника там нет), а в кэше: hookd-build.sh
# из hookd-client.c этого дерева, имя — по SHA-256 исходника (строка SRC ниже; тест test_hookd сверяет её с файлом).
# Клиента этой версии нет — сборка в фоне, этот вызов идёт медленным путём; неудачная сборка оставляет метку
# client-$SRC.failed, и фон больше не запускается (повтор — hookd-build.sh --force).
# Обработчик не guard — медленный путь python.sh <обработчик>.py: демон пока судит только guard.
SRC=9b4e2e0250ee322e

h=${0%/*}
case $h in
    /*) ;;
    *) h=$PWD/$h ;;
esac
handler=$1
shift
if [ "$handler" != guard ]; then
    exec /bin/sh "$h/python.sh" "$h/$handler.py" "$@"
fi
if [ "${PANTHEON_HOOKD:-}" != 1 ]; then
    exec /bin/sh "$h/python.sh" "$h/guard.py" "$@"
fi

why=env
if [ -n "${HOME:-}" ]; then
    d=$HOME/.cache/pantheon/hookd
    c=$d/bin/client-$SRC
    if [ -f "$c" ] && [ -x "$c" ]; then
        want= have=
        { IFS= read -r want <"$c.sum"; } 2>/dev/null
        if [ -x /sbin/sha256 ]; then
            have=$(/sbin/sha256 -q "$c" 2>/dev/null)
        elif [ -x /usr/bin/sha256sum ]; then
            have=$(/usr/bin/sha256sum "$c" 2>/dev/null)
            have=${have%% *}
        fi
        if [ ${#have} -eq 64 ] && [ "$have" = "$want" ]; then
            "$c" "$d/hookd.sock" "$h" "$@"
            rc=$?
            case $rc in
                126|127) why=client-exec ;;
                *) exit $rc ;;
            esac
        else
            why=client-sum
        fi
    else
        why=no-client
    fi
    if [ "$why" != client-exec ]; then
        if ! [ -e "$c.failed" ] && ! [ -e "$c.lock" ]; then
            /bin/sh "$h/hookd-build.sh" </dev/null >/dev/null 2>&1 &
        fi
    fi
    log=$HOME/.local/state/pantheon/logs
    { /bin/mkdir -p "$log" && printf '%s\t%s\n' "$(/bin/date +%Y-%m-%dT%H:%M:%S)" "$why" >>"$log/hookd-fallback.log"; } \
        2>/dev/null || printf 'hookd: %s — строку в hookd-fallback.log записать не удалось\n' "$why" >&2
else
    printf 'hookd: env — HOME пуст, строку в hookd-fallback.log не записать\n' >&2
fi
exec /bin/sh "$h/python.sh" "$h/guard.py" "$@"
