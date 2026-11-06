#!/usr/bin/env python3
"""Запуск MCP-сервера пакета окна вне папок окна (metis-0933, класс 2 модели угроз).

    python3 -I env_from.py [<файл .env> <ИМЯ>[,<ИМЯ>…]] -- <команда> […]

MCP-сервер идёт вне песочницы, а Claude Code запускает его в папке запуска окна — её окно пишет. npx оттуда взял бы
пакет из `node_modules/<пакет>` папки и настройки из её `.npmrc` (script-shell, registry, node-options): это код
вне песочницы (ревью argus B1 и B2 PR #360). Поэтому команда идёт из SAFE_CWD (корень диска: его не пишет ни одно
окно, выше него нет package.json и .npmrc), без унаследованных npm_config_*, NODE_OPTIONS и NODE_PATH, с кэшем npm
`$HOME/.npm` (вне allowWrite окон).

Необязательная часть — ключи из .env-файла репозитория: серверы grafana и upstash MorphStream/app запускались
скриптами app/scripts/start-*-mcp.sh, они делают `source .env.local`. Здесь .env-файл — только данные: строки
`[export ]ИМЯ=значение` (кавычки снимаются, подстановок нет), в окружение команды идут только названные имена. Файл —
обычный, не больше 1 МБ, и путь к нему без ссылок ниже $HOME (каждое звено — O_NOFOLLOW: подменённая ссылкой папка
не подсунет чужой .env; FIFO не вешает). Нет файла или имени — выход 1 с причиной в stderr; иначе exec команды (код
выхода — её)."""
import os
import re
import stat
import sys

LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
LIMIT = 1 << 20
SAFE_CWD = "/"
DROP_ENV = re.compile(r"(?i)npm_config_.*|NODE_OPTIONS|NODE_PATH")


def open_nofollow(p):
    """fd обычного чтения файла p: звенья ниже $HOME (или ниже первого звена пути вне $HOME) — без ссылок."""
    p = os.path.normpath(os.path.abspath(p))
    home = os.path.abspath(os.environ.get("HOME") or "/")
    for pre in (home, os.path.realpath(home)):
        if p == pre or p.startswith(pre.rstrip("/") + "/"):
            base, rest = os.path.realpath(home), p[len(pre):]
            break
    else:
        top = "/" + p.split("/")[1]
        base, rest = os.path.realpath(top), p[len(top):]
    parts = [x for x in rest.split("/") if x]
    if not parts:
        raise OSError(f"{p}: не файл")
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
        return os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
    finally:
        os.close(fd)


def read_env(p):
    fd = open_nofollow(p)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > LIMIT:
            raise OSError(f"{p}: не обычный файл или больше {LIMIT} байт")
        with os.fdopen(fd, "rb", closefd=False) as fh:
            text = fh.read(LIMIT).decode("utf-8", "replace")
    finally:
        os.close(fd)
    out = {}
    for line in text.splitlines():
        m = LINE.fullmatch(line)
        if not m or line.lstrip().startswith("#"):
            continue
        v = m.group(2)
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        elif " #" in v:
            v = v.split(" #", 1)[0].rstrip()
        out[m.group(1)] = v
    return out


def safe_env(base, extra):
    """Окружение команды: base без DROP_ENV, плюс extra и кэш npm $HOME/.npm."""
    env = {k: v for k, v in base.items() if not DROP_ENV.fullmatch(k)}
    env.update(extra)
    env["npm_config_cache"] = os.path.join(os.path.abspath(base.get("HOME") or "/"), ".npm")
    return env


def main(argv):
    if "--" not in argv or argv.index("--") not in (0, 2) or argv.index("--") == len(argv) - 1:
        print("env_from.py: нужно [<файл .env> <ИМЯ,…>] -- <команда>", file=sys.stderr)
        return 1
    cut = argv.index("--")
    cmd, got = argv[cut + 1:], {}
    if cut == 2:
        envfile, names = argv[0], [n for n in argv[1].split(",") if n]
        try:
            vals = read_env(os.path.expanduser(envfile))
        except OSError as e:
            print(f"env_from.py: {envfile} не прочитан — {e}", file=sys.stderr)
            return 1
        miss = [n for n in names if not vals.get(n)]
        if miss:
            print(f"env_from.py: в {envfile} нет {', '.join(miss)}", file=sys.stderr)
            return 1
        got = {n: vals[n] for n in names}
    env = safe_env(dict(os.environ), got)
    try:
        os.chdir(SAFE_CWD)
        os.execvpe(cmd[0], cmd, env)
    except OSError as e:
        print(f"env_from.py: {cmd[0]} не запустился — {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
