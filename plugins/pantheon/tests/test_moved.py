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
MOVED_PY = os.path.join(os.path.dirname(RUN_PY), "moved.py")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
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
    # Д3: соседние живые папки с тем же началом ключа и настоящая подпапка (у неё ключ тоже с хвостом)
    hist = lambda rel: os.path.join(tmp, ".claude", "projects", key(rel), "s.jsonl")
    for rel in (f"{AK}-old", f"{P}/workshop_notes", f"{AK}-x", f"{AK}/plugins", f"{AK}/x"):
        os.makedirs(os.path.join(tmp, rel), exist_ok=True)
    for rel in (f"{AK}-old", f"{AK}-v2", f"{P}/workshop_notes", f"{AK}-x", f"{AK}/plugins"):
        write(hist(rel), "{}\n")   # agent-kit-v2 — папки нет; agent-kit/x и agent-kit-x — ключ один, неоднозначно
    write(os.path.join(tmp, "ai", "pantheon", "notes.md"),
          f"история {key(AK + '-old')} и {key(AK + '/plugins')}; {key(P + '/workshop_notes')}\n")
    # argus-2 Б1: код agent-kit (настоящие тесты и данные guard) migrate-paths не переписывает
    guard_copy = os.path.join(tmp, AK, "plugins", "guard")
    _shutil.copytree(os.path.join(REPO, "plugins", "guard"), guard_copy,
                     ignore=_shutil.ignore_patterns("__pycache__", "*.pyc"))
    guard_before = snapshot(guard_copy)
    # Д2 argus-2: ссылка-файл в ~/ai на внешний файл со старым путём — не переписывается
    ext = os.path.join(_ROOT, "external.md")
    write(ext, f"~/{AK}\n")
    os.symlink(ext, os.path.join(tmp, "ai", "link.md"))
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
          and f"MEMORY.md: 1" in out and f"~/{AK}/README.md" not in out and "plugins/guard" not in out
          and f"история {key(AK)} → {key('ai/agent-kit')}" in out and "~/.claude.json: 3" in out
          and f"история {key(f'{WS}/avito')} → {key('ai/workshop/avito')}" in out)
    check("--dry-run: транскрипты, history.jsonl, .git, плагины, worktree, личное, двоичное — вне плана",
          "s1.jsonl" not in out and "history.jsonl" not in out and ".git" not in out and "plugins/cache" not in out
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
    code, wt_code, guard_copy = (p.replace(f"/{AK}/", "/ai/agent-kit/") for p in (code, wt_code, guard_copy))
    r = run("check", "--moved")
    check("check --moved после переноса: файлы со старыми путями — предупреждение, код 1; личное тоже",
          r.returncode == 1 and "предупреждение · старый путь · ~/ai/pantheon/directions" in r.stdout
          and "~/.claude.json" in r.stdout and "s1.jsonl" not in r.stdout and "history.jsonl" not in r.stdout
          and "личное ~/ai/knowledge" in r.stdout and ": 1 файлов — его меняет Мнемозина" in r.stdout)
    check("check --moved: имени личного файла и кода agent-kit в выводе нет (argus-2 Б2, Б1)",
          "money" not in r.stdout and "Areas/" not in r.stdout and "plugins/guard" not in r.stdout)
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
    check("роль заменена; код agent-kit на новом месте — нет (его меняет PR)",
          read(agent) == "папка ~/ai/workshop/<задача>\n" and read(code) == f"код: ~/{WS}\n")
    check("копия plugins/guard в ~/ai/agent-kit побайтно прежняя — набор guard не сломан (argus-2 Б1)",
          snapshot(guard_copy) == guard_before)
    check("ссылка-файл в ~/ai: внешний файл не тронут, ссылка на месте",
          read(ext) == f"~/{AK}\n" and os.path.islink(os.path.join(tmp, "ai", "link.md")))
    pk = lambda rel: os.path.isfile(hist(rel))
    check("история: соседи agent-kit-old, agent-kit-v2, workshop_notes и неоднозначный agent-kit-x — на месте",
          all(pk(x) for x in (f"{AK}-old", f"{AK}-v2", f"{P}/workshop_notes", f"{AK}-x"))
          and not os.path.lexists(hist("ai/agent-kit-old")) and not os.path.lexists(hist("ai/agent-kit-x")))
    check("история: настоящая подпапка agent-kit/plugins — под новым ключом",
          not pk(f"{AK}/plugins") and os.path.isfile(hist("ai/agent-kit/plugins")))
    notes = read(os.path.join(tmp, "ai", "pantheon", "notes.md"))
    check("ключи в тексте: подпапка заменена, соседи — нет",
          key("ai/agent-kit/plugins") in notes and key(AK + "-old") in notes and key(P + "/workshop_notes") in notes)
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
    check("check --moved после замены: осталось только личное — код 1, числом, без имени; карточки нет",
          r.returncode == 1 and "личное ~/ai/knowledge" in r.stdout and "money" not in r.stdout
          and "metis-0001" not in r.stdout)
    # argus-2 Б2: тревога планового прохода (check --quiet) — личное только числом
    with __import__("contextlib").suppress(OSError):
        os.remove(os.path.join(tmp, "state", "moved-check.stamp"))
    run("check", "--quiet")
    alerts = os.path.join(tmp, "ai", "pantheon", "alerts.md")
    al = read(alerts) if os.path.isfile(alerts) else ""
    check("check --quiet: тревога о старых путях есть, имени личного файла в alerts.md нет",
          "старые пути перенесённых папок" in al and "money" not in al and "Areas/" not in al)
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

    edge_cases()
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


def load_moved():
    import importlib.util
    spec = importlib.util.spec_from_file_location("moved_t", MOVED_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def edge_cases():
    """Ссылки, done() без новой папки (мутанты argus-2 Д2) и запись целиком (Д2 argus-1)."""
    M = load_moved()
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="moved-edge-"))
    ext = os.path.join(tmp, "ext")
    write(os.path.join(ext, "agents", "x.md"), f"~/{WS}\n")
    home = os.path.join(tmp, "h")
    os.makedirs(os.path.join(home, "ai"))
    os.symlink(ext, os.path.join(home, ".claude"))   # ~/.claude — ссылка: обходить её нельзя
    log = []
    rc = M.migrate(["workshop"], False, home, out=log.append)
    check("done(): ни старой, ни новой папки — отказ, код 1", rc == 1 and any("новой папки нет" in x for x in log))
    os.makedirs(os.path.join(home, "ai", "workshop"))
    log = []
    rc = M.migrate(["workshop"], False, home, out=log.append)
    check("~/.claude — ссылка: внешние файлы не тронуты", rc == 0 and read(os.path.join(ext, "agents", "x.md")) == f"~/{WS}\n")
    # запись целиком: сбой os.replace — ~/.claude.json и файл прежние, временных файлов нет, код 1
    os.remove(os.path.join(home, ".claude"))
    task = os.path.join(home, "ai", "t.md")
    write(task, f"~/{WS}\n")
    cj = os.path.join(home, ".claude.json")
    write(cj, json.dumps({"projects": {f"{home}/{WS}/a": {"x": 1}}}))
    os.chmod(cj, 0o600)
    cj_before, task_before = read(cj), read(task)
    real_replace = os.replace

    def boom(*a, **k):
        raise OSError(5, "сбой записи (проба)")
    os.replace = boom
    try:
        log = []
        rc = M.migrate(["workshop"], False, home, out=log.append)
    finally:
        os.replace = real_replace
    left = [x for d, _, ns in os.walk(home) for x in ns if x.endswith(".moved")]
    check("сбой записи: ~/.claude.json и файл целы, временных файлов нет, код 1",
          rc == 1 and read(cj) == cj_before and read(task) == task_before and not left
          and any("сбой    ~/.claude.json" in x for x in log))
    log = []
    rc = M.migrate(["workshop"], False, home, out=log.append)
    check("запись после сбоя: заменено, права ~/.claude.json прежние (0600)",
          rc == 0 and f"{home}/ai/workshop/a" in read(cj) and read(task) == "~/ai/workshop\n"
          and (os.stat(cj).st_mode & 0o777) == 0o600)
    _shutil.rmtree(tmp, True)


if __name__ == "__main__":
    main()
