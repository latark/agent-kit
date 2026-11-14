#!/usr/bin/env python3
"""Запуск MCP-сервера пакета окна вне папок окна (metis-0933, класс 2 модели угроз).

    python3 -I env_from.py [--chdir <папка>] [<файл .env> <ИМЯ>[,<ИМЯ>…]] -- <команда> […]

MCP-сервер идёт вне песочницы, а Claude Code запускает его в папке запуска окна — её окно пишет. npx оттуда взял бы
пакет из `node_modules/<пакет>` папки и настройки из её `.npmrc` (script-shell, registry, node-options): это код
вне песочницы (ревью argus B1 и B2 PR #360). Поэтому команда идёт из SAFE_CWD (корень диска: его не пишет ни одно
окно, выше него нет package.json и .npmrc), без унаследованных npm_config_*, NODE_OPTIONS и NODE_PATH, с кэшем npm
`$HOME/.npm` (вне allowWrite окон).

Необязательная часть — ключи из .env-файла репозитория: серверы проекта (например, метрики и очередь в app) запускались
скриптами app/scripts/start-*-mcp.sh, они делают `source .env.local`. Здесь .env-файл — только данные: строки
`[export ]ИМЯ=значение` (кавычки снимаются, подстановок нет), в окружение команды идут только названные имена. Файл —
обычный, без других жёстких ссылок, не больше 1 МБ, и путь к нему без ссылок ниже $HOME (каждое звено — openat с
O_NOFOLLOW от fd предыдущего, файл читается по своему fd: подменённая ссылкой папка не подсунет чужой .env ни до, ни
во время чтения; FIFO не вешает). Нет файла или имени — выход 1 с причиной в stderr; иначе exec команды (код
выхода — её).

`--chdir <папка>` (metis-0949) — серверу нужна папка проекта как рабочая: shadcn MCP читает components.json из
process.cwd(), а его `--cwd` только загружает .env. Команда тогда — ровно `npx -y <пакет>@<версия> [аргументы]`: пакет
разрешается как без ключа — `npx -y -p <пакет>@<версия> -c 'command -v <bin>'` из SAFE_CWD с тем же окружением (ни
node_modules, ни .npmrc папки проекта npx не видит), путь бинарника (realpath) — только внутри $HOME/.npm/_npx; затем
chdir в папку и exec `node <путь> [аргументы]`: node по абсолютному пути берёт модули рядом со скриптом, не из папки;
PATH — без относительных звеньев (иначе node нашёлся бы в папке проекта). Данные папки сервер читает сам: shadcn
грузит её .env* (dotenvx) — переменные, в том числе NODE_OPTIONS, задаёт окно; кода из папки он не исполняет (как и с
прежним `--cwd`). Поэтому --chdir не сочетается с .env-файлом: адреса и заголовки реестров (`${ИМЯ}`) задаёт
components.json, который пишет окно, и ключи .env ушли бы туда. Имя bin — последняя часть имени пакета (`@scope/x` →
`x`); пакет с другим именем bin с --chdir не запускается (выход 1)."""
import os
import re
import stat
import subprocess
import sys

LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
LIMIT = 1 << 20
SAFE_CWD = "/"
DROP_ENV = re.compile(r"(?i)npm_config_.*|NODE_OPTIONS|NODE_PATH")
NPX_SPEC = re.compile(r"((?:@[a-z0-9._-]+/)?([a-z0-9._-]+))@[0-9][0-9A-Za-z.+-]*")
RESOLVE_TIMEOUT = 300


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
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > LIMIT:
            raise OSError(f"{p}: не обычный файл, с другими жёсткими ссылками или больше {LIMIT} байт")
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
    """Окружение команды: base без DROP_ENV, плюс extra и кэш npm $HOME/.npm; в PATH — только абсолютные звенья:
    относительное (`.`, `./node_modules/.bin`, пустое) после --chdir нашло бы node и прочее в папке проекта."""
    env = {k: v for k, v in base.items() if not DROP_ENV.fullmatch(k)}
    env.update(extra)
    if "PATH" in env:
        env["PATH"] = os.pathsep.join(d for d in env["PATH"].split(os.pathsep) if os.path.isabs(d))
    env["npm_config_cache"] = os.path.join(os.path.abspath(base.get("HOME") or "/"), ".npm")
    return env


def npx_bin(cmd, env):
    """Абсолютный путь бинарника пакета команды `npx -y <пакет>@<версия> …` из кэша $HOME/.npm/_npx (разрешение — из
    SAFE_CWD) и аргументы после пакета; не та форма команды или путь вне кэша — OSError с причиной."""
    if len(cmd) < 3 or cmd[0] != "npx" or cmd[1] not in ("-y", "--yes") or not NPX_SPEC.fullmatch(cmd[2]):
        raise OSError("с --chdir команда — `npx -y <пакет>@<точная версия> [аргументы]`")
    spec, name = cmd[2], NPX_SPEC.fullmatch(cmd[2]).group(2)
    r = subprocess.run(["npx", "-y", "-p", spec, "-c", f"command -v {name}"], cwd=SAFE_CWD, env=env,
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True, timeout=RESOLVE_TIMEOUT)
    lines = (r.stdout or "").strip().splitlines()
    if r.returncode != 0 or not lines:
        raise OSError(f"npx не нашёл бинарник {name} пакета {spec} (код {r.returncode})")
    path = os.path.realpath(lines[-1].strip())
    cache = os.path.realpath(os.path.join(env["npm_config_cache"], "_npx"))
    if not path.startswith(cache + "/") or not os.path.isfile(path):
        raise OSError(f"бинарник {name} — {path}, не в кэше npx {cache}")
    return path, cmd[3:]


def main(argv):
    chdir = None
    if argv[:1] == ["--chdir"]:
        if len(argv) < 2:
            print("env_from.py: --chdir без папки", file=sys.stderr)
            return 1
        chdir, argv = os.path.realpath(os.path.expanduser(argv[1])), argv[2:]
        if not os.path.isdir(chdir):
            print(f"env_from.py: --chdir {chdir} — не папка", file=sys.stderr)
            return 1
    if "--" not in argv or argv.index("--") not in (0, 2) or argv.index("--") == len(argv) - 1:
        print("env_from.py: нужно [<файл .env> <ИМЯ,…>] -- <команда>", file=sys.stderr)
        return 1
    cut = argv.index("--")
    cmd, got = argv[cut + 1:], {}
    if chdir is not None and cut == 2:
        print("env_from.py: --chdir без .env-файла — сервер в папке проекта раскрывает ${ИМЯ} из её конфигов "
              "(заголовки реестров shadcn), ключи .env ушли бы на адрес, который задаёт окно", file=sys.stderr)
        return 1
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
        if chdir is not None:
            path, rest = npx_bin(cmd, env)
            os.chdir(chdir)
            cmd = ["node", path, *rest]
        os.execvpe(cmd[0], cmd, env)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"env_from.py: {cmd[0]} не запустился — {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
