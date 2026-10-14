#!/usr/bin/env python3
"""Stop разработчика (DONE-02 карты решений): с красными проверками работу не сдать.

Подключён в ролях dev-opus, dev-sonnet, dev-haiku (поле hooks: Stop — у субагента Claude Code превращает его в
SubagentStop). Основа — stop-verify.sh BrokerAssistant: ход, закончившийся текстом, — ещё не готовность, а правку
без прогона проверок никто не смотрел.

Что делает. Если в worktree разработчика есть правки (незакоммиченные файлы или коммиты поверх ветки, от которой
она ответвилась), хук сам запускает проверку проекта через общую блокировку тяжёлых команд (`heavy`, MEM-03):
  1. строка из файла .pantheon-verify в корне репозитория (её кладёт лид или координатор);
  2. иначе скрипт test, а без него check из package.json — менеджером из packageManager или lock-файла;
  3. иначе pytest, если в pyproject.toml есть [tool.pytest] (через uv, если есть uv.lock).
Нечем проверить — не держит. Места heavy заняты дольше 5 минут — отпускает с требованием написать «частично,
проверка не запускалась» (очередь — не красная проверка и не возврат). Красная проверка — выход 2 и конец вывода: разработчик чинит и пробует снова. Не
больше трёх возвратов подряд на одного разработчика: дальше хук отпускает с пометкой, а лид пишет в отчёте статус
«заблокировано» и выносит вопрос наверх («ждёт вас» — через координатора и Зевса).

Python 3.9+ (хуки запускает python3 из PATH). Состояние — ~/.local/state/pantheon/ctx/dev-stop/<agent_id>.
"""
import json
import os
import re
import signal
import subprocess
import sys

HOME = os.path.expanduser("~")
STATE = os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(HOME, ".local", "state", "pantheon"))
MAX_RETURNS = 3
WAIT_MAX = int(os.environ.get("PANTHEON_DEV_STOP_WAIT") or 300)  # ждать места heavy; не дождались — «очередь»
TIMEOUT = 840    # всё вместе; хук в роли — 900 с
TAIL = 4000
WAIT_EXIT = 75   # код heavy «места не дождалась»


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=30)
    return r.stdout.strip() if r.returncode == 0 else ""


def changed(root):
    """Незакоммиченные правки или коммиты, которые есть только на этой ветке (worktree ответвилась от ветки эпика:
    её коммиты достижимы и из других веток, а коммиты разработчика — только отсюда)."""
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        return True
    branch = git(root, "symbolic-ref", "-q", "HEAD")
    if not branch:
        return False
    short = branch[len("refs/heads/"):]  # для --branches git сравнивает --exclude с коротким именем
    own = git(root, "rev-list", "--count", "HEAD", "--not", f"--exclude={short}", "--branches", "--remotes")
    return own.isdigit() and int(own) > 0


def verify_command(root):
    p = os.path.join(root, ".pantheon-verify")
    if os.path.isfile(p):
        line = next((x.strip() for x in open(p, encoding="utf-8") if x.strip() and not x.startswith("#")), "")
        if line:
            return line
    pkg = os.path.join(root, "package.json")
    if os.path.isfile(pkg):
        try:
            data = json.load(open(pkg, encoding="utf-8"))
        except ValueError:
            data = {}
        scripts = data.get("scripts") or {}
        script = "test" if "test" in scripts else "check" if "check" in scripts else None
        if script:
            pm = (data.get("packageManager") or "").split("@")[0]
            if not pm:
                pm = "pnpm" if os.path.exists(os.path.join(root, "pnpm-lock.yaml")) else \
                    "yarn" if os.path.exists(os.path.join(root, "yarn.lock")) else "npm"
            return f"{pm} run {script}"
    pyproject = os.path.join(root, "pyproject.toml")
    if os.path.isfile(pyproject) and re.search(r"^\[tool\.pytest", open(pyproject, encoding="utf-8").read(), re.M):
        return "uv run pytest -q" if os.path.exists(os.path.join(root, "uv.lock")) else "python3 -m pytest -q"
    return None


def counter(agent_id, value=None):
    d = os.path.join(STATE, "ctx", "dev-stop")
    p = os.path.join(d, re.sub(r"[^\w-]", "_", agent_id or "none"))
    if value is None:
        try:
            return int(open(p).read().strip() or 0)
        except (OSError, ValueError):
            return 0
    os.makedirs(d, exist_ok=True)
    with open(p, "w") as fh:
        fh.write(str(value))
    return value


def main():
    try:
        ev = json.load(sys.stdin)
    except ValueError:
        return 0
    if os.environ.get("PANTHEON_DEV_STOP_OFF") == "1":
        return 0
    cwd = os.path.realpath(ev.get("cwd") or os.getcwd())
    root = git(cwd, "rev-parse", "--show-toplevel")
    if not root or not changed(root):
        return 0
    cmd = verify_command(root)
    if not cmd:
        return 0
    agent = ev.get("agent_id") or ev.get("session_id") or ""
    heavy = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "heavy")
    argv = [sys.executable, heavy, "/bin/sh", "-c", cmd] if os.path.isfile(heavy) else ["/bin/sh", "-c", cmd]
    env = dict(os.environ, HEAVY_WAIT_MAX=str(WAIT_MAX))
    # своя группа процессов: по таймауту гасим и обёртку, и саму проверку, а не только обёртку
    proc = subprocess.Popen(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=TIMEOUT)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        code, out = 124, f"проверка не уложилась в {TIMEOUT} с\n" + (out or "")
    if code == 0:
        counter(agent, 0)
        return 0
    if code == WAIT_EXIT:
        # места заняты другими тяжёлыми командами: проверку не запускали — это не красная проверка и не возврат
        print(f"Проверка проекта «{cmd}» не запускалась: оба места тяжёлых команд заняты дольше {WAIT_MAX} с "
              "(`heavy --status`). Работа не проверена — так и напиши в отчёте: «Статус: частично, проверка не "
              "запускалась (очередь)».", file=sys.stderr)
        return 0
    n = counter(agent) + 1
    if n > MAX_RETURNS:
        counter(agent, 0)
        print(f"Проверка «{cmd}» красная после {MAX_RETURNS} возвратов — отпускаю. В отчёте статус «заблокировано», "
              "что падает и почему не починить.", file=sys.stderr)
        return 0
    counter(agent, n)
    print(f"СТОП ({n} из {MAX_RETURNS}): проверка проекта красная — «{cmd}» (код {code}). Работа не сдана, пока "
          f"проверка не зелёная. Почини и закончи снова; если причина вне твоей задачи — опиши её в отчёте по формату "
          f"«Находка» и закончи со статусом «заблокировано».\n\nКонец вывода:\n{out[-TAIL:]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # сбой хука не держит разработчика, но остаётся в журнале
        try:
            os.makedirs(os.path.join(STATE, "logs"), exist_ok=True)
            with open(os.path.join(STATE, "logs", "ctx-hooks.log"), "a") as fh:
                fh.write(f"dev-stop-verify\t{type(e).__name__}: {e}\n")
        except OSError:
            pass
        sys.exit(0)
