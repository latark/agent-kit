#!/bin/sh
# Служба демона хуков guard pantheon.svc.hookd (metis-0330, metis-0811): шаблон launchd/pantheon.svc.hookd.plist.in → plist.
#   /bin/sh hookd-install.sh --print        plist на stdout, ничего не ставит (тесты, будущий плановый проход)
#   /bin/sh hookd-install.sh                собрать клиент и pantheon-hookd, папка сокета 0700, plist в
#                                           ~/Library/LaunchAgents, bootstrap, затем запрос доступа к папкам (ниже)
#   /bin/sh hookd-install.sh --check        ничего не ставит и не правит: стоит ли служба, есть ли у неё доступ к
#                                           Desktop, Documents, Downloads и iCloud Drive и как его дать, не открыта ли
#                                           папка демона окнам ролей (F7), доля откатов и canary-diff за сутки (F9)
#   /bin/sh hookd-install.sh --uninstall    bootout и удалить plist
# Службу ставит владелец своей командой из терминала (README guard, «Демон хуков»), роли — нет: ~/Library/LaunchAgents
# и ~/.cache/pantheon/hookd закрыты protect-config. Дерево — то, где лежит этот скрипт: зовите его из проверенного
# дерева guard (~/.claude/plugins/cache/agent-kit/guard/<версия>/scripts/), а не из рабочей копии.
#
# Запрос доступа (решение владельца 04.11). Первый процесс службы — ~/.cache/pantheon/hookd/bin/pantheon-hookd
# (hooks/hookd-svc.c): путь постоянный, macOS спрашивает и помнит доступ к папкам для него, а не для Python.app с
# версией в пути. Сразу после bootstrap скрипт ставит разовое задание launchd pantheon.hookd.probe (шаблон
# launchd/pantheon.hookd.probe.plist.in) с тем же pantheon-hookd: `daemon.py --tcc-probe` читает каждую папку, и окна
# macOS «разрешить доступ» появляются сейчас, пока владелец у терминала, а не из фона в случайный миг. Скрипт ждёт
# итога до PANTHEON_HOOKD_PROBE_WAIT секунд (по умолчанию 300), снимает задание и печатает, где доступ есть, где нет и
# как его дать (scripts/hookd-check.py tcc). --check делает ту же пробу: macOS ещё не спрашивала — спросит; отказ
# уже записан — второй раз не спросит, и вывод даёт команду, которая открывает «Файлы и папки», и перезапуск службы.
# Без доступа служба безопасна: демон отвечает «F perm», и вызов идёт медленным путём с правами окна (metis-0811 ч. 1).
#
# Внимание: плановый проход Пантеона (services_sync) снимает любой pantheon.svc.*, которого нет в schedule.toml, —
# пока он не знает hookd, поставленная вручную служба проживёт до ближайшего прохода. Установка плановым проходом —
# следующая часть metis-0330.
# PANTHEON_HOOKD_LAUNCHCTL — только тестам (подменённый launchctl); владельцу не нужен.
# Код 0 — сделано (установка: служба стоит, даже если доступа к папкам нет — это видно в выводе; --check: всё в
# порядке); иначе код не 0 и причина последней строкой.
set -u
h=$(cd "${0%/*}/../hooks" && pwd -P) || { echo "hookd-install: нет папки hooks рядом" >&2; exit 1; }
here=$(cd "${0%/*}" && pwd -P) || { echo "hookd-install: папка скрипта не открывается" >&2; exit 1; }
tdir=$(cd "${0%/*}/../launchd" && pwd -P) || { echo "hookd-install: нет папки launchd рядом" >&2; exit 1; }
tmpl=$tdir/pantheon.svc.hookd.plist.in
ptmpl=$tdir/pantheon.hookd.probe.plist.in
[ -n "${HOME:-}" ] || { echo "hookd-install: HOME пуст" >&2; exit 1; }
[ -f "$tmpl" ] && [ -f "$ptmpl" ] || { echo "hookd-install: нет шаблона в $tdir" >&2; exit 1; }
case "$HOME$h" in
    *'&'*|*'|'*|*'\'*|*'<'*|*'>'*) echo "hookd-install: в пути HOME или hooks знак, который plist не примет" >&2; exit 1 ;;
esac
label=pantheon.svc.hookd
plabel=pantheon.hookd.probe
plist=$HOME/Library/LaunchAgents/$label.plist
top=$HOME/.cache/pantheon/hookd
svc=$top/bin/pantheon-hookd
pdir=$top/probe
lctl=${PANTHEON_HOOKD_LAUNCHCTL:-/bin/launchctl}
wait_s=${PANTHEON_HOOKD_PROBE_WAIT:-300}
case $wait_s in
    ''|*[!0-9]*) wait_s=300 ;;
esac
uid=$(/usr/bin/id -u)
render() {
    /usr/bin/sed -e "s|@HOME@|$HOME|g" -e "s|@HOOKS@|$h|g" -e "s|@SVC@|$svc|g" "$tmpl"
}
render_probe() {
    /usr/bin/sed -e "s|@HOME@|$HOME|g" -e "s|@HOOKS@|$h|g" -e "s|@SVC@|$svc|g" -e "s|@OUT@|$pdir/result.json|g" "$ptmpl"
}
py() {
    /bin/sh "$h/python.sh" "$@"
}

# Проба доступа под launchd: разовое задание с pantheon-hookd, итог — $pdir/result.json. Код 0 — итог есть; иначе
# причина строкой в stdout, а сбой ли это — решает вызывающий
probe() {
    /bin/mkdir -p "$pdir" "$HOME/.local/state/pantheon/logs" && /bin/chmod 700 "$pdir" \
        || { echo "проба: папка $pdir не создаётся"; return 1; }
    /bin/rm -f "$pdir/result.json" "$pdir/result.json.tmp"
    render_probe >"$pdir/probe.plist" && /usr/bin/plutil -lint "$pdir/probe.plist" >/dev/null \
        || { /bin/rm -f "$pdir/probe.plist"; echo "проба: plist задания не записан"; return 1; }
    "$lctl" bootout "gui/$uid/$plabel" >/dev/null 2>&1
    if ! "$lctl" bootstrap "gui/$uid" "$pdir/probe.plist"; then
        /bin/rm -f "$pdir/probe.plist"
        echo "проба: launchctl bootstrap не принял задание $plabel"
        return 1
    fi
    echo "Проба доступа к Desktop, Documents, Downloads и iCloud Drive: если macOS спросит про pantheon-hookd —"
    echo "ответьте «Разрешить» (жду до $wait_s с)."
    i=0
    while ! [ -f "$pdir/result.json" ] && [ "$i" -lt $((wait_s * 5)) ]; do
        /bin/sleep 0.2
        i=$((i + 1))
    done
    "$lctl" bootout "gui/$uid/$plabel" >/dev/null 2>&1
    /bin/rm -f "$pdir/probe.plist"
    [ -f "$pdir/result.json" ] || { echo "проба: итога нет за $wait_s с (окно macOS без ответа?) — ответьте на окна и повторите --check"; return 1; }
    return 0
}

case "${1:-}" in
    --print)
        render
        exit $?
        ;;
    --uninstall)
        "$lctl" bootout "gui/$uid/$label" 2>/dev/null
        /bin/rm -f "$plist" || { echo "hookd-install: $plist не удалить" >&2; exit 1; }
        echo "служба $label снята"
        exit 0
        ;;
    --check)
        bad=
        if ! [ -f "$plist" ]; then
            echo "служба $label не поставлена: нет $plist — поставить: /bin/sh $here/hookd-install.sh"
            bad="служба не поставлена"
        else
            first=$(/usr/bin/plutil -extract ProgramArguments.0 raw -o - "$plist" 2>/dev/null)
            if [ "$first" != "$svc" ]; then
                echo "служба поставлена старой командой: первый процесс ${first:-?}, а не $svc — разрешение macOS"
                echo "достаётся не тому процессу. Переставить: /bin/sh $here/hookd-install.sh"
                bad="служба старой установки"
            fi
            if "$lctl" print "gui/$uid/$label" >/dev/null 2>&1; then
                echo "служба $label загружена (сокет $top/hookd.sock)"
            else
                echo "служба $label не загружена в launchd — поставить заново: /bin/sh $here/hookd-install.sh"
                bad="${bad:+$bad; }служба не загружена"
            fi
        fi
        if [ -x "$svc" ]; then
            if probe; then
                py "$here/hookd-check.py" tcc "$pdir/result.json" "$svc" || bad="${bad:+$bad; }нет доступа к папкам"
            else
                bad="${bad:+$bad; }проба доступа не прошла"
            fi
        else
            echo "нет $svc — доступ к папкам не проверить (поставить службу: /bin/sh $here/hookd-install.sh)"
            bad="${bad:+$bad; }нет pantheon-hookd"
        fi
        py "$here/hookd-check.py" windows || bad="${bad:+$bad; }папка демона открыта окнам"
        py "$here/hookd-stats.py"
        [ $? -eq 3 ] && bad="${bad:+$bad; }canary-diff"
        if [ -n "$bad" ]; then
            echo "hookd-install --check: есть что исправить — $bad"
            exit 1
        fi
        echo "hookd-install --check: всё в порядке"
        exit 0
        ;;
    "") ;;
    *) echo "hookd-install: неизвестный ключ $1 (--print, --check, --uninstall)" >&2; exit 64 ;;
esac
sock=$top/hookd.sock
[ ${#sock} -lt 104 ] || { echo "hookd-install: путь сокета длиннее 103 байт: $sock" >&2; exit 1; }
/bin/sh "$h/hookd-build.sh" --force >/dev/null || { echo "hookd-install: клиент не собран (hookd-build.sh)" >&2; exit 1; }
/bin/sh "$h/hookd-build.sh" --svc >/dev/null || { echo "hookd-install: pantheon-hookd не собран (hookd-build.sh --svc)" >&2; exit 1; }
/bin/mkdir -p "$top" "$HOME/.local/state/pantheon/logs" "$HOME/Library/LaunchAgents" \
    && /bin/chmod 700 "$top" || { echo "hookd-install: папки не созданы" >&2; exit 1; }
render >"$plist.new" && /usr/bin/plutil -lint "$plist.new" >/dev/null && /bin/mv -f "$plist.new" "$plist" \
    || { /bin/rm -f "$plist.new"; echo "hookd-install: plist не записан" >&2; exit 1; }
"$lctl" bootout "gui/$uid/$label" 2>/dev/null
"$lctl" bootstrap "gui/$uid" "$plist" || { echo "hookd-install: launchctl bootstrap не принял $plist" >&2; exit 1; }
echo "служба $label поставлена: сокет $sock, первый процесс $svc"
if probe; then
    py "$here/hookd-check.py" tcc "$pdir/result.json" "$svc"
else
    echo "доступ к папкам не проверен — повторить: /bin/sh $here/hookd-install.sh --check"
fi
echo "включить в окне — PANTHEON_HOOKD=1 в env его настроек"
