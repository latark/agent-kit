#!/bin/sh
# Служба демона хуков guard pantheon.svc.hookd (metis-0330): шаблон launchd/pantheon.svc.hookd.plist.in → plist.
#   /bin/sh hookd-install.sh --print        plist на stdout, ничего не ставит (тесты, будущий плановый проход)
#   /bin/sh hookd-install.sh                собрать клиент, папка сокета 0700, plist в ~/Library/LaunchAgents, bootstrap
#   /bin/sh hookd-install.sh --uninstall    bootout и удалить plist
# Ставит служба владелец своей командой из терминала (README guard, «Демон хуков»), роли — нет: ~/Library/LaunchAgents
# и ~/.cache/pantheon/hookd закрыты protect-config. Дерево — то, где лежит этот скрипт: зовите его из проверенного
# дерева guard (~/.claude/plugins/cache/agent-kit/guard/<версия>/scripts/), а не из рабочей копии.
# Внимание: тик Пантеона (services_sync) снимает любой pantheon.svc.*, которого нет в schedule.toml, — пока он не
# знает hookd, поставленная вручную служба проживёт до ближайшего тика. Установка тиком — следующая часть metis-0330.
# Код 0 — сделано; иначе код не 0 и причина последней строкой.
set -u
h=$(cd "${0%/*}/../hooks" && pwd -P) || { echo "hookd-install: нет папки hooks рядом" >&2; exit 1; }
tmpl=$(cd "${0%/*}/../launchd" && pwd -P)/pantheon.svc.hookd.plist.in
[ -n "${HOME:-}" ] || { echo "hookd-install: HOME пуст" >&2; exit 1; }
[ -f "$tmpl" ] || { echo "hookd-install: нет шаблона $tmpl" >&2; exit 1; }
case "$HOME$h" in
    *'&'*|*'|'*|*'\'*|*'<'*|*'>'*) echo "hookd-install: в пути HOME или hooks знак, который plist не примет" >&2; exit 1 ;;
esac
label=pantheon.svc.hookd
plist=$HOME/Library/LaunchAgents/$label.plist
render() {
    /usr/bin/sed -e "s|@HOME@|$HOME|g" -e "s|@HOOKS@|$h|g" "$tmpl"
}
case "${1:-}" in
    --print)
        render
        exit $?
        ;;
    --uninstall)
        /bin/launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
        /bin/rm -f "$plist" || { echo "hookd-install: $plist не удалить" >&2; exit 1; }
        echo "служба $label снята"
        exit 0
        ;;
    "") ;;
    *) echo "hookd-install: неизвестный ключ $1 (--print, --uninstall)" >&2; exit 64 ;;
esac
sock=$HOME/.cache/pantheon/hookd/hookd.sock
[ ${#sock} -lt 104 ] || { echo "hookd-install: путь сокета длиннее 103 байт: $sock" >&2; exit 1; }
/bin/sh "$h/hookd-build.sh" --force >/dev/null || { echo "hookd-install: клиент не собран (hookd-build.sh)" >&2; exit 1; }
/bin/mkdir -p "$HOME/.cache/pantheon/hookd" "$HOME/.local/state/pantheon/logs" "$HOME/Library/LaunchAgents" \
    && /bin/chmod 700 "$HOME/.cache/pantheon/hookd" || { echo "hookd-install: папки не созданы" >&2; exit 1; }
render >"$plist.new" && /usr/bin/plutil -lint "$plist.new" >/dev/null && /bin/mv -f "$plist.new" "$plist" \
    || { /bin/rm -f "$plist.new"; echo "hookd-install: plist не записан" >&2; exit 1; }
/bin/launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
/bin/launchctl bootstrap "gui/$(id -u)" "$plist" || { echo "hookd-install: launchctl bootstrap не принял $plist" >&2; exit 1; }
echo "служба $label поставлена: сокет $sock; включить в окне — PANTHEON_HOOKD=1 в env его настроек"
