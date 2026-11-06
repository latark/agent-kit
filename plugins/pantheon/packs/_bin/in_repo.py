#!/usr/bin/env python3
"""Хук репозитория в пакете окна направления (metis-0933, схема А).

    python3 -I in_repo.py <репозиторий> [--file-arg] [--always] [--ok] [--cmd-prefix=<начало>] [--plain=<папки>]
        -- <команда> […]

Только с -I (metis-0933, класс 2): хук идёт вне песочницы, и PYTHONPATH или sitecustomize из окружения исполнили бы
чужой код. Скрипт хука — аргумент `.claude/hooks/<имя>`: эту папку песочница окна закрывает на запись (EXEC_DIRS ядра).

Окно направления запущено в одной папке, а хуки вложенных проектов (MorphStream/app, gpu-worker, mailkeeper) писались
под запуск в своём репозитории: относительный путь `.claude/hooks/…`, путь файла аргументом. Обёртка читает вход хука
(JSON на stdin) и, если цель инструмента — файл внутри <репозитория> (tool_input.file_path, notebook_path или path;
без них — cwd входа), запускает команду в папке репозитория с тем же stdin. Код выхода и вывод команды — как есть
(2 блокирует инструмент).

Хук идёт вне песочницы, а окно пишет папки репозитория и его родителя: между проверкой пути строкой и действием по той
же строке оно может подменить звено ссылкой на чужую папку (класс 2, ревью argus C1, C2 и D2 PR #360: из 300 запусков
2 раза исполнился чужой скрипт). Поэтому обёртка действует не по пути, а по открытым дескрипторам (fd):
- корень репозитория открывается по звеньям от realpath($HOME) (вне $HOME — от realpath первого звена): openat с
  O_NOFOLLOW, звено-ссылка — отказ; дальше обёртка держит этот fd;
- .claude, .claude/hooks и скрипт `.claude/hooks/<имя>` — openat от fd корня с O_NOFOLLOW; скрипт — обычный файл,
  команда получает его как /dev/fd/N (bash /dev/fd/N, python3 -I /dev/fd/N), а не по пути;
- папка команды — fchdir(fd корня); fd корня передаётся ребёнку (номер — в REPO_FD_ENV), и repo_hooks.py открывает
  файлы от него, путь CLAUDE_PROJECT_DIR заново не разрешает (CLAUDE_PROJECT_DIR — только строка для сообщений).

  --always    запускать и для целей вне репозитория (хук сам смотрит tool_name — protect-db.sh, guard_bash.py)
  --file-arg  дописать путь файла последним аргументом (repo_hooks.py <хук> <файл>)
  --ok        как `… 2>/dev/null || true` исходной строки: stderr — в никуда, выход 0
  --cmd-prefix=<начало>  только Bash, чья tool_input.command начинается с <начало>: matcher `Bash(git commit *)`
              исходных настроек — не формат matcher хука, там он срабатывал бы на каждую команду Bash
  --plain=<папка>[,<папка>…]  папки репозитория, которые хук читает целиком своими путями (grep -r, find, [ -f ]):
              если на их звеньях или внутри есть ссылка — до запуска или после него (окно подложило ссылку во время
              прогона) — вывод хука выброшен, выход 2 с причиной (pre-commit-check.sh)

Цель вне репозитория без --always — выход 0 молча. Нет папки репозитория — выход 0 со строкой в stderr: хук пакета не
должен ронять инструменты окна. Нет скрипта `.claude/hooks/<имя>` или команда не запустилась — выход 1 со строкой в
stderr (ошибка хука; onFailure: block её блокирует). Звено пути репозитория ниже $HOME, .claude, .claude/hooks или
скрипт — ссылка или не то, чем должно быть (окно подменило) — выход 2 с причиной: хук из чужой папки не запускается,
инструмент блокируется. Python 3.9+ (системный python3 macOS)."""
import json
import os
import stat
import subprocess
import sys

DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
HOOKS = ".claude/hooks/"
REPO_FD_ENV = "PANTHEON_REPO_FD"


class Linked(OSError):
    """Звено — ссылка или не папка (не обычный файл): окно подменило путь."""


def open_root(given):
    """(fd, путь) папки given: от realpath($HOME) (given вне $HOME — от realpath первого звена) по звеньям openat с
    O_NOFOLLOW. FileNotFoundError — звена нет, Linked — звено ссылка или не папка. Путь — строка без ссылок для
    сравнения и сообщений; действовать — только по fd."""
    p = os.path.normpath(os.path.abspath(given))
    home = os.path.abspath(os.environ.get("HOME") or "/")
    for pre in (home, os.path.realpath(home)):
        if p == pre or p.startswith(pre.rstrip("/") + "/"):
            base, rest = os.path.realpath(home), p[len(pre):]
            break
    else:
        top = "/" + p.split("/")[1]
        base, rest = os.path.realpath(top), p[len(top):]
    fd, cur = os.open(base, os.O_RDONLY | os.O_DIRECTORY), base
    try:
        for part in [x for x in rest.split("/") if x]:
            cur = os.path.join(cur, part)
            fd = _step(fd, part, cur)
    except BaseException:
        os.close(fd)
        raise
    return fd, cur


def _step(fd, part, shown):
    """openat(fd, part) папкой без перехода по ссылке; старый fd закрыт."""
    try:
        nfd = os.open(part, DIR, dir_fd=fd)
    except FileNotFoundError:
        raise
    except OSError as e:
        raise Linked(f"{shown}: ссылка или не папка ({e.strerror})")
    os.close(fd)
    return nfd


def open_sub(root, rel):
    """fd папки rel внутри root (по звеньям, O_NOFOLLOW); FileNotFoundError, Linked."""
    fd, cur = os.dup(root), ""
    try:
        for part in [x for x in rel.split("/") if x]:
            if part in (".", ".."):
                raise Linked(f"{rel}: «.» и «..» не звенья")
            cur = os.path.join(cur, part)
            fd = _step(fd, part, cur)
    except BaseException:
        os.close(fd)
        raise
    return fd


def links_under(root, rel):
    """Ссылки на звеньях root/rel и внутри этой папки — по fd, по ссылкам не ходит; нет папки — пусто."""
    try:
        top = open_sub(root, rel)
    except FileNotFoundError:
        return []
    except Linked as e:
        return [str(e)]
    out = []
    try:
        for dp, dns, fns, dfd in os.fwalk(".", dir_fd=top, follow_symlinks=False):
            for n in dns + fns:
                try:
                    if stat.S_ISLNK(os.stat(n, dir_fd=dfd, follow_symlinks=False).st_mode):
                        out.append(os.path.normpath(os.path.join(rel, dp, n)))
                except FileNotFoundError:
                    pass
    finally:
        os.close(top)
    return out


def open_script(hooks, name):
    """fd скрипта .claude/hooks/<name>: обычный файл, openat от fd папки hooks с O_NOFOLLOW."""
    if hooks is None:
        raise FileNotFoundError(f"{HOOKS}{name}: нет папки .claude/hooks")
    if not name or "/" in name or name in (".", ".."):
        raise Linked(f"{HOOKS}{name}: не имя файла в .claude/hooks")
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=hooks)
    except FileNotFoundError:
        raise FileNotFoundError(f"{HOOKS}{name}: нет файла")
    except OSError as e:
        raise Linked(f"{HOOKS}{name}: ссылка или не файл ({e.strerror})")
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise Linked(f"{HOOKS}{name}: не обычный файл")
    os.set_blocking(fd, True)
    return fd


def main(argv):
    if "--" not in argv or argv.index("--") < 1 or argv.index("--") == len(argv) - 1:
        print("in_repo.py: нужно <репозиторий> [флаги] -- <команда>", file=sys.stderr)
        return 0
    cut = argv.index("--")
    given, flags, cmd = os.path.abspath(os.path.expanduser(argv[0])), set(argv[1:cut]), argv[cut + 1:]
    raw = sys.stdin.buffer.read()
    try:
        root, repo = open_root(given)
    except FileNotFoundError:
        print(f"in_repo.py: нет папки {given} — хук пропущен", file=sys.stderr)
        return 0
    except OSError as e:
        print(f"in_repo.py: {given}: {e} — хук из чужой папки не запускаю", file=sys.stderr)
        return 2
    try:
        hooks = open_sub(root, ".claude/hooks")
    except FileNotFoundError:
        hooks = None
    except OSError as e:
        print(f"in_repo.py: {repo}: {e} — хук из чужой папки не запускаю", file=sys.stderr)
        return 2
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    target = next((ti[k] for k in ("file_path", "notebook_path", "path") if isinstance(ti.get(k), str) and ti[k]), "")
    base = data.get("cwd") if isinstance(data.get("cwd"), str) else os.getcwd()
    # решение «внутри ли цель» — по строке realpath; действие хука — от fd корня (repo_hooks.py), так что подмена
    # звена после этой проверки не уводит его из репозитория
    where = os.path.realpath(os.path.join(base, os.path.expanduser(target)) if target else base)
    inside = where == repo or where.startswith(repo.rstrip("/") + "/")
    if not inside and "--always" not in flags:
        return 0
    prefix = next((f.split("=", 1)[1] for f in flags if f.startswith("--cmd-prefix=")), None)
    if prefix is not None:
        command = ti.get("command") if isinstance(ti.get("command"), str) else ""
        if not (command.strip() + " ").startswith(prefix.strip() + " "):
            return 0
    plain = [x for f in sorted(flags) if f.startswith("--plain=") for x in f.split("=", 1)[1].split(",") if x]
    bad = [x for rel in plain for x in links_under(root, rel)]
    if bad:
        print(f"in_repo.py: в {repo} ссылка ({', '.join(bad[:5])}) — хук читает эти папки вне песочницы, "
              "не запускаю; убери ссылку", file=sys.stderr)
        return 2
    fds, cmd = [root], list(cmd)
    try:
        for i, a in enumerate(cmd):
            if a.startswith(HOOKS):
                sfd = open_script(hooks, a[len(HOOKS):])
                fds.append(sfd)
                cmd[i] = f"/dev/fd/{sfd}"
    except FileNotFoundError as e:
        print(f"in_repo.py: {repo}: {e} — хук не запущен", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"in_repo.py: {repo}: {e} — хук из чужой папки не запускаю", file=sys.stderr)
        return 2
    env = dict(os.environ, CLAUDE_PROJECT_DIR=repo, CLAUDE_FILE_PATH=where if target else "")
    env[REPO_FD_ENV] = str(root)
    if "--file-arg" in flags:
        cmd = cmd + [where if target else ""]
    os.fchdir(root)
    keep = subprocess.PIPE if plain else None
    try:
        r = subprocess.run(cmd, env=env, input=raw, pass_fds=fds, stdout=keep,
                           stderr=subprocess.DEVNULL if "--ok" in flags else keep)
    except OSError as e:
        print(f"in_repo.py: {cmd[0]} не запустился — {e}", file=sys.stderr)
        return 1
    if plain:
        bad = [x for rel in plain for x in links_under(root, rel)]
        if bad:
            print(f"in_repo.py: в {repo} во время хука появилась ссылка ({', '.join(bad[:5])}) — вывод хука выброшен:"
                  " он мог прочитать чужое; убери ссылку", file=sys.stderr)
            return 2
        sys.stdout.buffer.write(r.stdout or b"")
        sys.stdout.flush()
        sys.stderr.buffer.write(r.stderr or b"")
    return 0 if "--ok" in flags else r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
