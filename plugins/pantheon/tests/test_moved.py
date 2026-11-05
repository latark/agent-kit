#!/usr/bin/env python3
"""pantheon migrate-paths и check --moved (metis-0899): одна таблица переносов, временный HOME.
Старые пути в тесте собраны из частей: так файл сам не попадает под check --moved."""
import hashlib
import json
import os
import re
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile
import atexit as _atexit
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="moved-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

RUN_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "run.py")
results = []
P = "projects"
AK, WS, FIN = f"{P}/agent-kit", f"{P}/workshop", f"{P}/other/finances"   # старые пути от HOME


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def write(p, text, mode="w"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
        fh.write(text)


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def snapshot(root):
    out = {}
    for d, dirs, names in os.walk(root):
        for x in names + [y for y in dirs if os.path.islink(os.path.join(d, y))]:
            p = os.path.join(d, x)
            out[os.path.relpath(p, root)] = (hashlib.sha256(open(p, "rb").read()).hexdigest()
                                             if os.path.isfile(p) and not os.path.islink(p) else "dir")
        for x in dirs:
            out.setdefault(os.path.relpath(os.path.join(d, x), root), "dir")
    return out


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="moved-test-"))
    key = lambda rel: re.sub(r"[^A-Za-z0-9]", "-", tmp + "/" + rel)   # ключ истории Claude Code
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": os.path.join(tmp, "ai", "pantheon"),
           "PANTHEON_STATE": os.path.join(tmp, "state"), "PANTHEON_NO_NOTIFY": "1"}
    run = lambda *a: subprocess.run([PY311, "-I", RUN_PY, *a], env=env, capture_output=True, text=True)

    # старые папки на месте; файлы со старыми путями во всех видах
    for rel in (AK, f"{WS}/avito", FIN):
        os.makedirs(os.path.join(tmp, rel))
    task = os.path.join(tmp, "ai", "pantheon", "directions", "metis-pantheon", "tasks", "metis-0001.md")
    write(task, f"---\nstatus: done\ntouches: [~/{AK}/plugins/x.py]\n---\nсм. ~/{AK}. И $HOME/{WS}/avito, "
                f"/Users/someone/{FIN}/a.csv и {tmp}/{AK}/README.md.\nНе путь: ~/{AK}-old, ~/{AK}.git, ~/{P}/workshopx\n")
    agent = os.path.join(tmp, ".claude", "agents", "x.md")
    write(agent, f"папка ~/{WS}/<задача>\n")
    mem_dir = os.path.join(tmp, ".claude", "projects", key(AK), "memory")
    write(os.path.join(mem_dir, "MEMORY.md"), f"история — ~/.claude/projects/{key(AK)}/; worktree — "
                                              f"{key(AK)}--claude-worktrees-a1\n")
    transcript = os.path.join(tmp, ".claude", "projects", key(AK), "s1.jsonl")
    write(transcript, json.dumps({"cwd": f"{tmp}/{AK}"}) + "\n")
    wt_hist = os.path.join(tmp, ".claude", "projects", key(AK) + "--claude-worktrees-a1", "s2.jsonl")
    write(wt_hist, "{}\n")
    ws_hist = os.path.join(tmp, ".claude", "projects", key(f"{WS}/avito"), "s3.jsonl")
    write(ws_hist, "{}\n")
    write(os.path.join(tmp, ".claude", "history.jsonl"), f'{{"project": "{tmp}/{AK}"}}\n')
    write(os.path.join(tmp, ".claude", "plugins", "cache", "c.py"), f"~/{AK}\n")
    gitf = os.path.join(tmp, "ai", "pantheon", ".git", "COMMIT_EDITMSG")
    write(gitf, f"~/{AK}\n")
    personal = os.path.join(tmp, "ai", "knowledge", "Areas", "money.md")
    write(personal, f"~/{FIN}\n")
    binary = os.path.join(tmp, "ai", "bin.dat")
    write(binary, b"\0" + f"~/{AK}".encode(), "wb")
    code = os.path.join(tmp, AK, "README.md")
    write(code, f"код: ~/{WS}\n")
    wt_code = os.path.join(tmp, AK, ".claude", "worktrees", "a1", "README.md")
    write(wt_code, f"код: ~/{WS}\n")
    cj = os.path.join(tmp, ".claude.json")
    write(cj, json.dumps({"projects": {f"{tmp}/{AK}": {"hasTrustDialogAccepted": True, "allowedTools": ["x"]},
                                       f"{tmp}/{WS}/avito": {"hasTrustDialogAccepted": True},
                                       "/other": {"lastCwd": f"{tmp}/{FIN}/sub"}}, "n": 1}, indent=2))

    r = run("migrate-paths")
    check("migrate-paths без переноса — код 2, подсказка", r.returncode == 2 and "agent-kit|workshop|finances" in r.stderr)
    r = run("migrate-paths", "nope", "--dry-run")
    check("migrate-paths с неизвестным переносом — код 2", r.returncode == 2 and "nope" in r.stderr)
    r = run("migrate-paths", "agent-kit", "--bogus")
    check("migrate-paths с неизвестным флагом — код 2", r.returncode == 2 and "--bogus" in r.stderr)

    before = snapshot(tmp)
    r = run("migrate-paths", "agent-kit", "workshop", "finances", "--dry-run")
    out = r.stdout
    check("--dry-run до переноса: код 0, план есть, «внимание» про старую папку",
          r.returncode == 0 and "внимание agent-kit: старая папка ещё на месте" in out and "итог: файлов" in out
          and "--dry-run, ничего не изменено" in out)
    check("--dry-run: в плане карточка (закрытая), роль, автопамять, код agent-kit, история, ~/.claude.json",
          "~/ai/pantheon/directions/metis-pantheon/tasks/metis-0001.md: 5" in out and "~/.claude/agents/x.md: 1" in out
          and f"MEMORY.md: 1" in out and f"~/{AK}/README.md: 1" in out
          and f"история {key(AK)} → {key('ai/agent-kit')}" in out and "~/.claude.json: 3" in out
          and f"история {key(f'{WS}/avito')} → {key('ai/workshop/avito')}" in out)
    check("--dry-run: транскрипты, history.jsonl, .git, плагины, worktree, личное, двоичное — вне плана",
          "s1.jsonl" not in out and "history.jsonl" not in out and ".git" not in out and "plugins" not in out
          and "worktrees/a1" not in out and "money.md" not in out and "bin.dat" not in out
          and "--claude-worktrees-a1 →" not in out)
    check("--dry-run ничего не меняет на диске", snapshot(tmp) == before)
    r = run("migrate-paths", "agent-kit")
    check("без --dry-run до переноса — отказ, код 1, ничего не изменено",
          r.returncode == 1 and "отказ   agent-kit: старая папка ещё на месте" in r.stdout and snapshot(tmp) == before)

    r = run("check", "--moved")
    check("check --moved до переноса: старые пути не ищет, код 0",
          r.returncode == 0 and "перенос agent-kit ещё не сделан" in r.stdout and "старых путей нет" in r.stdout)

    # перенос папок (его делает плановый проход), затем check и migrate
    os.makedirs(os.path.join(tmp, "ai", "life"))
    os.rename(os.path.join(tmp, AK), os.path.join(tmp, "ai", "agent-kit"))
    os.rename(os.path.join(tmp, WS), os.path.join(tmp, "ai", "workshop"))
    os.rename(os.path.join(tmp, FIN), os.path.join(tmp, "ai", "life", "finances"))
    code, wt_code = (p.replace(f"/{AK}/", "/ai/agent-kit/") for p in (code, wt_code))
    r = run("check", "--moved")
    check("check --moved после переноса: файлы со старыми путями — предупреждение, код 1; личное тоже",
          r.returncode == 1 and "предупреждение · старый путь · ~/ai/pantheon/directions" in r.stdout
          and "~/.claude.json" in r.stdout and "money.md" in r.stdout and "s1.jsonl" not in r.stdout
          and "history.jsonl" not in r.stdout)
    r = run("check")
    check("pantheon check: старые пути — строкой «предупреждение», на код выхода не влияют",
          "предупреждение · старый путь" in r.stdout)

    write(os.path.join(tmp, ".claude", "projects", key("ai/workshop/avito"), "keep.jsonl"), "{}\n")
    tr_before = read(transcript)
    r = run("migrate-paths", "agent-kit", "workshop", "finances")
    out = r.stdout
    check("конфликт истории: новая папка уже есть — не перенесена, код 1, остальное сделано",
          r.returncode == 1 and f"конфликт история {key(f'{WS}/avito')}" in out
          and os.path.isfile(ws_hist) and os.path.isdir(os.path.join(tmp, ".claude", "projects", key("ai/agent-kit"))))
    text = read(task)
    check("карточка: все виды путей заменены, похожие — нет",
          f"touches: [~/ai/agent-kit/plugins/x.py]" in text and "см. ~/ai/agent-kit." in text
          and "$HOME/ai/workshop/avito" in text and "/Users/someone/ai/life/finances/a.csv" in text
          and f"{tmp}/ai/agent-kit/README.md" in text and f"~/{AK}-old" in text and f"~/{AK}.git" in text
          and f"~/{P}/workshopx" in text)
    check("роль, код agent-kit на новом месте — заменены", read(agent) == "папка ~/ai/workshop/<задача>\n"
          and read(code) == "код: ~/ai/workshop\n")
    mem = read(os.path.join(tmp, ".claude", "projects", key("ai/agent-kit"), "memory", "MEMORY.md"))
    check("автопамять: папка под новым ключом, ключ в тексте заменён, ключ worktree — нет",
          f"projects/{key('ai/agent-kit')}/" in mem and f"{key(AK)}--claude-worktrees-a1" in mem)
    check("история worktree не перенесена", os.path.isfile(wt_hist))
    check("транскрипт, history.jsonl, .git, плагины, worktree, личное, двоичное — не тронуты",
          read(transcript.replace(key(AK), key("ai/agent-kit"))) == tr_before
          and f"{tmp}/{AK}" in read(os.path.join(tmp, ".claude", "history.jsonl"))
          and read(gitf) == f"~/{AK}\n" and read(os.path.join(tmp, ".claude", "plugins", "cache", "c.py")) == f"~/{AK}\n"
          and read(wt_code) == f"код: ~/{WS}\n" and read(personal) == f"~/{FIN}\n"
          and open(binary, "rb").read() == b"\0" + f"~/{AK}".encode())
    data = json.load(open(cj, encoding="utf-8"))
    check("~/.claude.json: записи под новым ключом с доверием и allowedTools, строки заменены, прочее как было",
          data["projects"].get(f"{tmp}/ai/agent-kit") == {"hasTrustDialogAccepted": True, "allowedTools": ["x"]}
          and data["projects"].get(f"{tmp}/ai/workshop/avito") == {"hasTrustDialogAccepted": True}
          and data["projects"]["/other"]["lastCwd"] == f"{tmp}/ai/life/finances/sub" and data["n"] == 1
          and f"{tmp}/{AK}" not in data["projects"])
    r = run("migrate-paths", "agent-kit", "finances")
    check("повтор: замен нет, код 0", r.returncode == 0 and "итог: файлов 0, замен 0, папок истории 0, замен в "
          "~/.claude.json 0" in r.stdout)
    r = run("check", "--moved")
    check("check --moved после замены: остались только личное и конфликт — код 1, в выводе нет карточки",
          r.returncode == 1 and "money.md" in r.stdout and "metis-0001" not in r.stdout)
    os.remove(personal)
    r = run("check", "--moved")
    check("check --moved: старых путей нет — код 0", r.returncode == 0 and "старых путей нет" in r.stdout)

    # ключ .claude.json уже есть под новым путём — старая запись остаётся, код 1
    write(cj, json.dumps({"projects": {f"{tmp}/{FIN}": {"a": 1}, f"{tmp}/ai/life/finances": {"b": 2}}}))
    r = run("migrate-paths", "finances")
    data = json.load(open(cj, encoding="utf-8"))
    check("конфликт ~/.claude.json: обе записи на месте, код 1",
          r.returncode == 1 and "конфликт ~/.claude.json" in r.stdout
          and data["projects"] == {f"{tmp}/{FIN}": {"a": 1}, f"{tmp}/ai/life/finances": {"b": 2}})

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
