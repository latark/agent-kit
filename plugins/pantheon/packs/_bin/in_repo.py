#!/usr/bin/env python3
"""Хук репозитория в пакете окна направления (metis-0933, схема А).

    python3 -I in_repo.py <репозиторий> [--file-arg] [--always] [--ok] [--cmd-prefix=<начало>] -- <команда> […]

Только с -I (metis-0933, класс 2): хук идёт вне песочницы, и PYTHONPATH или sitecustomize из окружения исполнили бы
чужой код. Команда — из <репозиторий>/.claude/hooks: эту папку песочница окна закрывает на запись (EXEC_DIRS ядра).

Окно направления запущено в одной папке, а хуки вложенных проектов (MorphStream/app, gpu-worker) писались под
запуск в своём репозитории: относительный путь `.claude/hooks/…`, `$CLAUDE_PROJECT_DIR`, путь файла аргументом.
Обёртка читает вход хука (JSON на stdin) и, если цель инструмента — файл внутри <репозитория> (tool_input.file_path,
notebook_path или path; без них — cwd входа), запускает команду с cwd=<репозиторий>, CLAUDE_PROJECT_DIR=<репозиторий>,
CLAUDE_FILE_PATH=<путь файла> и тем же stdin. Код выхода и вывод команды — как есть (2 блокирует инструмент).

  --always    запускать и для целей вне репозитория (хук сам смотрит tool_name — protect-db.sh)
  --file-arg  дописать путь файла последним аргументом (check-fsd.sh "$CLAUDE_FILE_PATH")
  --ok        как `… 2>/dev/null || true` исходной строки: stderr — в никуда, выход 0
  --cmd-prefix=<начало>  только Bash, чья tool_input.command начинается с <начало>: matcher `Bash(git commit *)`
              исходных настроек — не формат matcher хука, там он срабатывал бы на каждую команду Bash

Цель вне репозитория без --always — выход 0 молча. Нет папки репозитория или команды — выход 0 со строкой в stderr:
хук пакета не должен ронять инструменты окна. Путь к репозиторию ниже $HOME, его .claude или .claude/hooks — ссылка
(окно подменило папку, metis-0933) — выход 2 с причиной в stderr: хук из чужой папки не запускается, инструмент
блокируется. Python 3.9+ (системный python3 macOS)."""
import json
import os
import subprocess
import sys


def linked(p):
    """Звенья пути p ниже $HOME (вне $HOME — ниже первого звена), которые — ссылки: окно пишет папку-родителя
    репозитория и могло подменить его (или звено выше) ссылкой на папку, где .claude/hooks не под запретом записи."""
    home = os.path.abspath(os.environ.get("HOME") or "/")
    top = home if p == home or p.startswith(home.rstrip("/") + "/") else "/" + p.split("/")[1]
    out, cur = [], top
    for part in [x for x in p[len(top):].split("/") if x]:
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            out.append(cur)
    return out


def main(argv):
    if "--" not in argv or argv.index("--") < 1 or argv.index("--") == len(argv) - 1:
        print("in_repo.py: нужно <репозиторий> [флаги] -- <команда>", file=sys.stderr)
        return 0
    cut = argv.index("--")
    given, flags, cmd = os.path.abspath(os.path.expanduser(argv[0])), set(argv[1:cut]), argv[cut + 1:]
    repo = os.path.realpath(given)
    raw = sys.stdin.buffer.read()
    if not os.path.isdir(repo):
        print(f"in_repo.py: нет папки {repo} — хук пропущен", file=sys.stderr)
        return 0
    links = linked(given) + [x for x in (".claude", ".claude/hooks") if os.path.islink(os.path.join(given, x))]
    if links:
        print(f"in_repo.py: {given}: ссылка вместо папки ({', '.join(links)}) — хук из чужой папки не запускаю",
              file=sys.stderr)
        return 2
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    target = next((ti[k] for k in ("file_path", "notebook_path", "path") if isinstance(ti.get(k), str) and ti[k]), "")
    base = data.get("cwd") if isinstance(data.get("cwd"), str) else os.getcwd()
    where = os.path.realpath(os.path.join(base, os.path.expanduser(target)) if target else base)
    inside = where == repo or where.startswith(repo.rstrip("/") + "/")
    if not inside and "--always" not in flags:
        return 0
    prefix = next((f.split("=", 1)[1] for f in flags if f.startswith("--cmd-prefix=")), None)
    if prefix is not None:
        command = ti.get("command") if isinstance(ti.get("command"), str) else ""
        if not (command.strip() + " ").startswith(prefix.strip() + " "):
            return 0
    env = dict(os.environ, CLAUDE_PROJECT_DIR=repo, CLAUDE_FILE_PATH=where if target else "")
    if "--file-arg" in flags:
        cmd = cmd + [where if target else ""]
    try:
        r = subprocess.run(cmd, cwd=repo, env=env, input=raw,
                           stderr=subprocess.DEVNULL if "--ok" in flags else None)
    except OSError as e:
        print(f"in_repo.py: {cmd[0]} не запустился — {e}", file=sys.stderr)
        return 0
    return 0 if "--ok" in flags else r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
