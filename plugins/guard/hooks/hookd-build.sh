#!/bin/sh
# Сборка клиента демона хуков (metis-0330): hookd-client.c этого дерева → ~/.cache/pantheon/hookd/bin/client-<SRC>.
#   /bin/sh hookd-build.sh [--force]
#   /bin/sh hookd-build.sh --svc     исполняемый файл службы ~/.cache/pantheon/hookd/bin/pantheon-hookd из hookd-svc.c
#                                    (зовёт только hookd-install.sh; подробно — ветка --svc ниже и шапка hookd-svc.c)
# Зовут: оболочка hookd.sh в фоне, когда клиента своей версии нет или он не совпал с меткой, и команда установки
# службы (README guard, «Демон хуков»). Бинарник не кладётся в дерево плагина: дерево сверяет verified.json, а
# собранный файл в нём нарушил бы сверку и выпуск. Имя — по SHA-256 исходника (строка SRC в hookd.sh): у каждой версии
# исходника свой файл, старый клиент новым не подменяется, а сессии старой версии плагина берут свой. Исходник не
# совпал с SRC — сборки нет. Рядом с клиентом — метка client-<SRC>.sum, SHA-256 собранного файла: hookd.sh сверяет с
# ней клиент перед каждым запуском. Папка ~/.cache/pantheon/hookd — 0700: её проверяет клиент; роли её не правят
# (protect-config).
# Окружение окна сборке не доверяется: сборку зовёт хук, а PATH, CPATH, SDKROOT, CFLAGS, DYLD_* и прочее у него — от
# сессии. Подменённый cc или заголовок дали бы клиент, который отвечает «пропустить» на всё. Поэтому PATH —
# только системный, команды — по абсолютным путям, а cc идёт через env -i: окружение пустое, кроме HOME, PATH и
# TMPDIR — своей папки внутри закрытого кэша.
# Один сборщик за раз — замок client-<SRC>.lock (старше 2 мин — брошен, снимается). Неудача — метка
# client-<SRC>.failed с причиной: фон hookd.sh больше не запускает сборку, повтор — --force. На macOS без
# инструментов командной строки (xcode-select -p) cc не зовётся: заглушка /usr/bin/cc открыла бы окно установки.
# Код 0 и путь к клиенту — собран или уже был; иначе код 1 и причина последней строкой.
set -u
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
unset CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH OBJC_INCLUDE_PATH LIBRARY_PATH SDKROOT COMPILER_PATH \
    CCC_OVERRIDE_OPTIONS CFLAGS CPPFLAGS LDFLAGS CC DEVELOPER_DIR TOOLCHAINS MACOSX_DEPLOYMENT_TARGET \
    DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH DYLD_FALLBACK_LIBRARY_PATH \
    DYLD_FALLBACK_FRAMEWORK_PATH LD_PRELOAD LD_LIBRARY_PATH 2>/dev/null
force= svc=
case "${1:-}" in
    --force) force=1 ;;
    --svc) svc=1 ;;
esac
h=$(cd "${0%/*}" && pwd -P) || { echo "hookd-build: папка скрипта не открывается" >&2; exit 1; }
src=$h/hookd-client.c
want=$(/usr/bin/sed -n 's/^SRC=\([0-9a-f]\{16\}\)$/\1/p' "$h/hookd.sh")
if [ -z "${HOME:-}" ] || [ -z "$want" ]; then
    echo "hookd-build: нет HOME или строки SRC в hookd.sh" >&2
    exit 1
fi
# SHA-256 файла: /sbin/sha256 (macOS 14+), иначе sha256sum (Linux) или shasum — всё по абсолютным путям
sum() {
    if [ -x /sbin/sha256 ]; then
        /sbin/sha256 -q "$1" 2>/dev/null
    elif [ -x /usr/bin/sha256sum ]; then
        /usr/bin/sha256sum "$1" 2>/dev/null | /usr/bin/cut -d' ' -f1
    else
        /usr/bin/shasum -a 256 "$1" 2>/dev/null | /usr/bin/cut -d' ' -f1
    fi
}
top=$HOME/.cache/pantheon/hookd
d=$top/bin
/bin/mkdir -p "$d" && /bin/chmod 700 "$top" "$d" || { echo "hookd-build: папка $d не создаётся" >&2; exit 1; }
if [ -n "$svc" ]; then
    # исполняемый файл службы pantheon-hookd (hookd-svc.c, metis-0811): путь постоянный, пересборка — только при
    # правке исходника (метка .src — его SHA-256) или если в подписи нет hardened runtime: иначе macOS заново
    # спрашивала бы доступ к папкам. Собирается под своим именем во временной папке — подпись ad-hoc берёт имя файла,
    # и тот же исходник даёт тот же файл. Только macOS: служба launchd — там.
    # Защита от внедрения кода (Б1 argus #320): без неё dyld до main выполнил бы DYLD_INSERT_LIBRARIES того, кто
    # запускает файл, и чужой код работал бы с разрешением TCC службы. Два слоя, каждый сам закрывает DYLD_*: сегмент
    # __RESTRICT от компоновщика и подпись ad-hoc с hardened runtime (codesign -o runtime). Подпись не прошла или в
    # ней нет runtime — отказ: неподписанный файл не ставится. Метка .sum — от подписанного файла
    ssrc=$h/hookd-svc.c
    bin=$d/pantheon-hookd
    runtime() {  # подпись файла $1 с hardened runtime: «flags=0x10002(adhoc,runtime)»
        /usr/bin/codesign -dv "$1" 2>&1 | /usr/bin/grep -q '^CodeDirectory .*flags=0x[0-9a-f]*([^)]*runtime'
    }
    s_src=$(sum "$ssrc")
    [ ${#s_src} -eq 64 ] || { echo "hookd-build: не посчитать SHA-256 $ssrc" >&2; exit 1; }
    if [ -f "$bin" ] && [ -x "$bin" ] && [ "$(/usr/bin/head -c 64 "$bin.src" 2>/dev/null)" = "$s_src" ] \
        && [ "$(sum "$bin")" = "$(/usr/bin/head -c 64 "$bin.sum" 2>/dev/null)" ] && runtime "$bin"; then
        echo "$bin"
        exit 0
    fi
    [ "$(/usr/bin/uname -s)" = Darwin ] || { echo "hookd-build: pantheon-hookd — только для macOS" >&2; exit 1; }
    /usr/bin/xcode-select -p >/dev/null 2>&1 || { echo "hookd-build: нет инструментов командной строки Xcode (xcode-select -p)" >&2; exit 1; }
    [ -x /usr/bin/cc ] || { echo "hookd-build: нет компилятора /usr/bin/cc" >&2; exit 1; }
    lock=$bin.lock
    /bin/rm -rf "$lock" 2>/dev/null  # собирает только hookd-install.sh из терминала владельца, не фон хука
    /bin/mkdir "$lock" || { echo "hookd-build: папка $lock не создаётся" >&2; exit 1; }
    trap '/bin/rm -rf "$lock" 2>/dev/null' EXIT
    cd "$h" && /usr/bin/env -i HOME="$HOME" PATH="$PATH" TMPDIR="$lock" /usr/bin/cc -O2 \
        -Wl,-sectcreate,__RESTRICT,__restrict,/dev/null -o "$lock/pantheon-hookd" "$ssrc" 2>"$lock/cc.log" \
        || { echo "hookd-build: cc: $(/usr/bin/tail -n 1 "$lock/cc.log")" >&2; exit 1; }
    /usr/bin/env -i HOME="$HOME" PATH="$PATH" TMPDIR="$lock" /usr/bin/codesign -s - -f -o runtime \
        -i pantheon-hookd "$lock/pantheon-hookd" >"$lock/cs.log" 2>&1 \
        || { echo "hookd-build: codesign -o runtime не прошёл: $(/usr/bin/tail -n 1 "$lock/cs.log")" >&2; exit 1; }
    runtime "$lock/pantheon-hookd" || { echo "hookd-build: codesign: в подписи нет hardened runtime" >&2; exit 1; }
    s=$(sum "$lock/pantheon-hookd")
    [ ${#s} -eq 64 ] || { echo "hookd-build: не посчитать SHA-256 собранного pantheon-hookd" >&2; exit 1; }
    printf '%s\n' "$s" >"$bin.sum" && printf '%s\n' "$s_src" >"$bin.src" && /bin/chmod 755 "$lock/pantheon-hookd" \
        && /bin/mv -f "$lock/pantheon-hookd" "$bin" || { echo "hookd-build: не переложить pantheon-hookd в $bin" >&2; exit 1; }
    echo "$bin"
    exit 0
fi
bin=$d/client-$want
if [ -z "$force" ] && [ -f "$bin" ] && [ -x "$bin" ] && [ -f "$bin.sum" ] \
    && [ "$(sum "$bin")" = "$(/usr/bin/head -c 64 "$bin.sum")" ]; then
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
        /bin/rm -rf "$lock" 2>/dev/null
        /bin/mkdir "$lock" 2>/dev/null || { echo "hookd-build: сборка уже идёт" >&2; exit 1; }
    else
        echo "hookd-build: сборка уже идёт" >&2
        exit 1
    fi
fi
trap '/bin/rm -rf "$lock" 2>/dev/null' EXIT
fail() {
    printf '%s\n' "$1" >"$bin.failed"
    echo "hookd-build: $1" >&2
    exit 1
}
have=$(sum "$src" | /usr/bin/cut -c1-16)
[ "$have" = "$want" ] || fail "исходник $src не совпал с SRC в hookd.sh ($have ≠ $want)"
if [ "$(/usr/bin/uname -s)" = Darwin ] && ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
    fail "нет инструментов командной строки Xcode (xcode-select -p) — cc не зовётся"
fi
[ -x /usr/bin/cc ] || fail "нет компилятора /usr/bin/cc"
tmp=$bin.tmp.$$
# временные файлы cc — в замке: он внутри закрытого кэша и убирается при выходе
cd "$h" && /usr/bin/env -i HOME="$HOME" PATH="$PATH" TMPDIR="$lock" /usr/bin/cc -O2 -o "$tmp" "$src" 2>"$tmp.log"
rc=$?
if [ "$rc" -ne 0 ]; then
    why=$(/usr/bin/tail -n 1 "$tmp.log" 2>/dev/null)
    /bin/rm -f "$tmp" "$tmp.log"
    fail "cc: ${why:-ошибка сборки (код $rc)}"
fi
/bin/rm -f "$tmp.log" "$bin.failed"
s=$(sum "$tmp")
[ ${#s} -eq 64 ] || { /bin/rm -f "$tmp"; fail "не посчитать SHA-256 собранного клиента"; }
# между двумя mv метка и клиент не совпадают — оболочка в этот миг идёт медленным путём (client-sum)
printf '%s\n' "$s" >"$bin.sum.$$" && /bin/mv -f "$bin.sum.$$" "$bin.sum" \
    && /bin/chmod 755 "$tmp" && /bin/mv -f "$tmp" "$bin" || fail "не переложить $tmp → $bin"
# клиенты других версий исходника — пока ими могут пользоваться сессии старой версии плагина; старше 30 дней — нет
/usr/bin/find "$d" -maxdepth 1 -name 'client-*' ! -name "client-$want*" -mtime +30 -exec /bin/rm -f {} + 2>/dev/null
echo "$bin"
