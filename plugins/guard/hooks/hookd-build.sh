#!/bin/sh
# Сборка клиента демона хуков (metis-0330): hookd-client.c этого дерева → ~/.cache/pantheon/hookd/bin/client-<SRC>.
#   /bin/sh hookd-build.sh [--force]
# Зовут: оболочка hookd.sh в фоне, когда клиента своей версии нет, и команда установки службы (README guard, «Демон
# хуков»). Бинарник не кладётся в дерево плагина: дерево сверяет verified.json, а собранный файл в нём нарушил бы
# сверку и выпуск. Имя — по SHA-256 исходника (строка SRC в hookd.sh): у каждой версии исходника свой файл, старый
# клиент новым не подменяется, а сессии старой версии плагина берут свой. Исходник не совпал с SRC — сборки нет.
# Папка ~/.cache/pantheon/hookd — 0700: её проверяет клиент; роли её не правят (protect-config).
# Один сборщик за раз — замок client-<SRC>.lock (старше 2 мин — брошен, снимается). Неудача — метка
# client-<SRC>.failed с причиной: фон hookd.sh больше не запускает сборку, повтор — --force. На macOS без
# инструментов командной строки (xcode-select -p) cc не зовётся: заглушка /usr/bin/cc открыла бы окно установки.
# Код 0 и путь к клиенту — собран или уже был; иначе код 1 и причина последней строкой.
set -u
force=
[ "${1:-}" = --force ] && force=1
h=$(cd "${0%/*}" && pwd -P) || { echo "hookd-build: папка скрипта не открывается" >&2; exit 1; }
src=$h/hookd-client.c
want=$(/usr/bin/sed -n 's/^SRC=\([0-9a-f]\{16\}\)$/\1/p' "$h/hookd.sh")
if [ -z "${HOME:-}" ] || [ -z "$want" ]; then
    echo "hookd-build: нет HOME или строки SRC в hookd.sh" >&2
    exit 1
fi
top=$HOME/.cache/pantheon/hookd
d=$top/bin
/bin/mkdir -p "$d" && /bin/chmod 700 "$top" "$d" || { echo "hookd-build: папка $d не создаётся" >&2; exit 1; }
bin=$d/client-$want
if [ -z "$force" ] && [ -f "$bin" ] && [ -x "$bin" ]; then
    echo "$bin"
    exit 0
fi
if [ -z "$force" ] && [ -e "$bin.failed" ]; then
    echo "hookd-build: прошлая сборка не удалась ($(/usr/bin/head -c 200 "$bin.failed")); повтор — --force" >&2
    exit 1
fi
lock=$bin.lock
if ! /bin/mkdir "$lock" 2>/dev/null; then
    if [ -n "$(/usr/bin/find "$lock" -maxdepth 0 -mmin +2 2>/dev/null)" ]; then
        /bin/rmdir "$lock" 2>/dev/null
        /bin/mkdir "$lock" 2>/dev/null || { echo "hookd-build: сборка уже идёт" >&2; exit 1; }
    else
        echo "hookd-build: сборка уже идёт" >&2
        exit 1
    fi
fi
trap '/bin/rmdir "$lock" 2>/dev/null' EXIT
fail() {
    printf '%s\n' "$1" >"$bin.failed"
    echo "hookd-build: $1" >&2
    exit 1
}
if command -v shasum >/dev/null 2>&1; then
    have=$(shasum -a 256 "$src" 2>/dev/null | /usr/bin/cut -c1-16)
else
    have=$(sha256sum "$src" 2>/dev/null | /usr/bin/cut -c1-16)
fi
[ "$have" = "$want" ] || fail "исходник $src не совпал с SRC в hookd.sh ($have ≠ $want)"
if [ "$(uname -s)" = Darwin ] && ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
    fail "нет инструментов командной строки Xcode (xcode-select -p) — cc не зовётся"
fi
command -v cc >/dev/null 2>&1 || fail "нет компилятора cc"
tmp=$bin.tmp.$$
if ! cc -O2 -o "$tmp" "$src" 2>"$tmp.log"; then
    why=$(/usr/bin/tail -n 1 "$tmp.log")
    /bin/rm -f "$tmp" "$tmp.log"
    fail "cc: ${why:-ошибка сборки}"
fi
/bin/rm -f "$tmp.log" "$bin.failed"
/bin/chmod 755 "$tmp" && /bin/mv -f "$tmp" "$bin" || fail "не переложить $tmp → $bin"
# клиенты других версий исходника — пока ими могут пользоваться сессии старой версии плагина; старше 30 дней — нет
/usr/bin/find "$d" -maxdepth 1 -name 'client-*' ! -name "client-$want*" -mtime +30 -exec /bin/rm -f {} + 2>/dev/null
echo "$bin"
