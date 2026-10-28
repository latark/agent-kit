#!/usr/bin/env python3
"""Stop разработчика (DONE-02 карты решений): с непроверенной или красной работой не сдать.

Подключён в ролях dev-opus, dev-sonnet, dev-haiku (поле hooks: Stop — у субагента Claude Code превращает его в
SubagentStop). Основа — stop-verify.sh одного из проектов: ход, закончившийся текстом, — ещё не готовность, а правку
без прогона проверок никто не смотрел.

Хук сам код проекта НЕ запускает: хуки идут вне песочницы, а `.pantheon-verify`, `package.json` и тесты в worktree
разработчик может поменять — запуск их из хука был бы выходом из песочницы (находка проверки безопасности 15.10).
Вместо этого хук читает транскрипт разработчика (agent_transcript_path) и требует, чтобы проверку проекта он прогнал
сам — в своей песочнице, через `heavy` — и чтобы последний её прогон после последней правки был зелёным.

Какая проверка — по версии файлов в точке, от которой ответвилась ветка разработчика (не по его правкам):
  1. первая строка .pantheon-verify в корне репозитория (её кладёт лид или координатор);
  2. иначе скрипт test, а без него check из package.json — менеджером из packageManager или lock-файла;
  3. иначе pytest, если в pyproject.toml есть [tool.pytest] (через uv, если есть uv.lock).
Нечем проверить или правок нет — не держит. Иначе — выход 2 с тем, что запустить; не больше трёх возвратов подряд
на одного разработчика: дальше хук отпускает, а разработчик пишет в отчёте «заблокировано» (лид выносит наверх).

Python 3.11+: хуки запускает hooks/python.sh (metis-0571). Состояние — ~/.local/state/pantheon/ctx/dev-stop/<agent_id>.
"""
import json
import os
import re
import subprocess
import sys

HOME = os.path.expanduser("~")
STATE = os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(HOME, ".local", "state", "pantheon"))
MAX_RETURNS = 3
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Bash, после которого файлы могли поменяться (защита от ошибки, а не от обмана: проверку можно и не запускать)
BASH_WRITES = re.compile(r"(?:^|[;&|]\s*)(?:sed\s+-i|perl\s+-[a-z]*i|mv|cp|rm|tee|touch|patch|truncate|"
                         r"git\s+(?:apply|am|checkout|switch|restore|merge|rebase|cherry-pick|reset|stash|pull|revert)|"
                         r"\S*(?:pnpm|npm|yarn|npx)\s+(?:add|remove|install|i|up|update)|"
                         r"\S*pantheon\s+exec\s+codex)\b"  # Codex правит worktree за роль — это правка
                         r"|[^<>&0-9]>{1,2}\s*[^&\s]")


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=30)
    return r.stdout.strip() if r.returncode == 0 else ""


def own_commits(root):
    """Коммиты, которые есть только на ветке разработчика (worktree ответвилась от ветки эпика)."""
    branch = git(root, "symbolic-ref", "-q", "HEAD")
    if not branch:
        return 0
    short = branch[len("refs/heads/"):]  # для --branches git сравнивает --exclude с коротким именем
    n = git(root, "rev-list", "--count", "HEAD", "--not", f"--exclude={short}", "--branches", "--remotes")
    return int(n) if n.isdigit() else 0


def show(root, rev, name):
    r = subprocess.run(["git", "-C", root, "show", f"{rev}:{name}"], capture_output=True, text=True, timeout=30)
    return r.stdout if r.returncode == 0 else None


def verify_commands(root, base):
    """→ (как назвать, [варианты строки команды]) по файлам из точки ответвления base."""
    text = show(root, base, ".pantheon-verify")
    if text:
        line = next((x.strip() for x in text.splitlines() if x.strip() and not x.startswith("#")), "")
        if line:
            return line, [line]
    pkg = show(root, base, "package.json")
    if pkg:
        try:
            data = json.loads(pkg)
        except ValueError:
            data = {}
        scripts = data.get("scripts") or {}
        script = "test" if "test" in scripts else "check" if "check" in scripts else None
        if script:
            pm = (data.get("packageManager") or "").split("@")[0]
            if not pm:
                pm = "pnpm" if show(root, base, "pnpm-lock.yaml") is not None else \
                    "yarn" if show(root, base, "yarn.lock") is not None else "npm"
            return f"{pm} run {script}", [f"{pm} run {script}", f"{pm} {script}"]
    pyproject = show(root, base, "pyproject.toml")
    if pyproject and re.search(r"^\[tool\.pytest", pyproject, re.M):
        return ("uv run pytest" if show(root, base, "uv.lock") is not None else "python3 -m pytest"), ["pytest"]
    return None, []


def norm(cmd):
    return " ".join(str(cmd).split())


def last_runs(transcript, variants):
    """По транскрипту: (был ли прогон проверки после последней правки, зелёный ли последний такой прогон)."""
    uses, results, order = {}, {}, []
    try:
        fh = open(transcript, encoding="utf-8")
    except OSError:
        return None
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            content = (d.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for x in content:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "tool_use":
                    uses[x.get("id")] = (x.get("name"), x.get("input") or {})
                    order.append(x.get("id"))
                elif x.get("type") == "tool_result":
                    results[x.get("tool_use_id")] = bool(x.get("is_error"))
    last_edit, last_run = -1, None
    for i, uid in enumerate(order):
        name, inp = uses[uid]
        cmd = norm(inp.get("command", "")) if name == "Bash" else ""
        if name == "Bash" and any(v in cmd for v in variants):
            if uid in results:
                last_run = (i, not results[uid])
            continue
        if name in EDIT_TOOLS or (name == "Bash" and BASH_WRITES.search(cmd)):
            last_edit = i
    if last_run is None or last_run[0] < last_edit:
        return False, False
    return True, last_run[1]


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
    if not root:
        return 0
    n_own = own_commits(root)
    dirty = bool(git(root, "status", "--porcelain", "--untracked-files=normal"))
    if not n_own and not dirty:
        return 0
    label, variants = verify_commands(root, f"HEAD~{n_own}" if n_own else "HEAD")
    if not variants:
        return 0
    agent = ev.get("agent_id") or ev.get("session_id") or ""
    seen = last_runs(ev.get("agent_transcript_path") or ev.get("transcript_path") or "", [norm(v) for v in variants])
    if seen is None:
        return 0  # транскрипта нет — проверить нечем, не держим
    ran, green = seen
    if ran and green:
        counter(agent, 0)
        return 0
    n = counter(agent) + 1
    if n > MAX_RETURNS:
        counter(agent, 0)
        print(f"Проверка проекта «{label}» после последней правки {'красная' if ran else 'не прогнана'} — после "
              f"{MAX_RETURNS} возвратов отпускаю. В отчёте статус «заблокировано»: что падает и почему не починить.",
              file=sys.stderr)
        return 0
    counter(agent, n)
    if ran:
        why = (f"последний прогон проверки проекта «{label}» после правок — красный. Работа не сдана, пока проверка не "
               "зелёная: почини и прогони снова.")
    else:
        why = f"после последней правки ты не прогнал проверку проекта. Запусти `heavy {label}` и добейся зелёного результата."
    print(f"СТОП ({n} из {MAX_RETURNS}): {why} Если причина вне твоей задачи — опиши её в отчёте по формату «Находка» "
          "и закончи со статусом «заблокировано».", file=sys.stderr)
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
