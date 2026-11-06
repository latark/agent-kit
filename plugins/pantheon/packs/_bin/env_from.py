#!/usr/bin/env python3
"""Запуск MCP-сервера пакета окна с ключами из .env-файла репозитория (metis-0933, класс 2 модели угроз).

    python3 -I env_from.py <файл .env> <ИМЯ>[,<ИМЯ>…] -- <команда> […]

Серверы grafana и upstash MorphStream/app запускались скриптами app/scripts/start-*-mcp.sh: они делают `source
.env.local` и `npx -y` без версии. MCP идёт вне песочницы, а app/ окно пишет — правка скрипта или .env.local стала бы
кодом вне песочницы. Здесь .env-файл — только данные: строки `[export ]ИМЯ=значение` (кавычки снимаются, подстановок
нет), в окружение команды идут только названные имена. Файл — обычный, не ссылка, не больше 1 МБ (O_NOFOLLOW, FIFO
не вешает). Нет файла или имени — выход 1 с причиной в stderr; иначе exec команды (код выхода — её)."""
import os
import re
import stat
import sys

LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
LIMIT = 1 << 20


def read_env(p):
    fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
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


def main(argv):
    if "--" not in argv or argv.index("--") != 2 or len(argv) < 4:
        print("env_from.py: нужно <файл .env> <ИМЯ,…> -- <команда>", file=sys.stderr)
        return 1
    envfile, names, cmd = argv[0], [n for n in argv[1].split(",") if n], argv[3:]
    try:
        got = read_env(os.path.expanduser(envfile))
    except OSError as e:
        print(f"env_from.py: {envfile} не прочитан — {e}", file=sys.stderr)
        return 1
    miss = [n for n in names if not got.get(n)]
    if miss:
        print(f"env_from.py: в {envfile} нет {', '.join(miss)}", file=sys.stderr)
        return 1
    env = dict(os.environ, **{n: got[n] for n in names})
    try:
        os.execvpe(cmd[0], cmd, env)
    except OSError as e:
        print(f"env_from.py: {cmd[0]} не запустился — {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
