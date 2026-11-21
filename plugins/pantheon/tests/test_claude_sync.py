#!/usr/bin/env python3
"""`pantheon outside claude-sync` (lib/claude_sync.py, metis-1327): защищённые пути копии — к проверенной версии.

Запуск: python3 -I plugins/pantheon/tests/test_claude_sync.py  (код выхода 0 — все прошли)
На временных папках: «сервер» — bare-репозиторий (ветка по умолчанию main), клон реестра направления athena-x и его
worktree окна .claude/worktrees/agent-x на ветке feat. После «застрявшего checkout» на диске копии лежат старые версии
защищённых путей; проход (outside.handle → claude_sync.run) должен:
  - привести к HEAD путь, чья запись в HEAD равна ветке по умолчанию сервера (навык, удалённый settings.json);
  - отказать (код 1, файл не тронут) пути со своей версией в HEAD и пути, которого нет на ветке по умолчанию, — и
    когда окно подделало свой refs/remotes/origin/main под feat (сверка — со слов сервера, не по ref копии);
  - удалить файл, которого нет ни в HEAD, ни на ветке по умолчанию, и опустевшую папку над ним;
  - не трогать файлы вне защищённых путей и игнорируемые (.gitignore);
  - не проходить ссылку в звене пути (файл за ссылкой не тронут);
  - не менять индекс git копии;
  - отказать всей заявке при незаконченном rebase (и merge) без изменений;
  - отказать папке не из реестра окна;
  - не удалять игнорируемые файлы и файлы вне .claude/skills|commands|agents: окно добавило settings.local.json в
    индекс или положило хук, которого нет ни в HEAD, ни на main, — файл на месте, отказ;
  - --merge: слить SHA ветки по умолчанию со слов сервера (git merge --no-commit) и оставить конфликты — и отказать
    без изменений, если коммита нет в клоне или он подменён, ветка меняет защищённые пути, код грязный,
    неотслеживаемый файл не равен базе, в info/attributes свой драйвер, merge не закончен; хуки клона не запускаются.
Плюс привязка в outside.py: вид claude-sync идёт проходу серверов, check_request его принимает, лишний флаг — код 2.
"""
import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311, mkroot  # pantheon.py — только на Python 3.11+

if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)] + sys.argv[1:])

ROOT = os.path.realpath(mkroot("claude-sync-"))
atexit.register(shutil.rmtree, ROOT, True)
HOME = os.path.join(ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                   "GIT_CONFIG_NOSYSTEM": "1"})
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import pantheon as P  # noqa: E402

O = P.outside_mod()
C = O.sub_mod("claude-sync")
FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{extra}]"))
    if not cond:
        FAILS.append(name)


def git(d, *args):
    r = subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        "-c", "init.defaultBranch=main", *args], capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def put(d, rel, text):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text)


def read(d, rel):
    try:
        with open(os.path.join(d, rel)) as fh:
            return fh.read()
    except OSError:
        return None


def digest(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# --- сервер, клон реестра и worktree окна --------------------------------------------------------------------------
SERVER = os.path.join(ROOT, "server.git")
SEED = os.path.join(ROOT, "seed")
CLONE = os.path.join(HOME, "projects", "app")
OTHER = os.path.join(HOME, "projects", "other")
WT = os.path.join(CLONE, ".claude", "worktrees", "agent-x")
EXT = os.path.join(ROOT, "ext")   # папка вне копии, куда ведёт подложенная ссылка

git(ROOT, "init", "-q", "--bare", "-b", "main", SERVER)
os.makedirs(SEED)
git(SEED, "init", "-q", "-b", "main")
BASE_FILES = {".claude/skills/a/SKILL.md": "A1\n", ".claude/settings.json": "{\"s\": 1}\n",
              ".claude/commands/c.md": "C1\n", ".claude/hooks/h.sh": "echo ok\n", "README.md": "r1\n",
              ".gitignore": ".claude/settings.local.json\n.claude/skills/local/\n"}
for rel, text in BASE_FILES.items():
    put(SEED, rel, text)
git(SEED, "add", "-A")
git(SEED, "commit", "-q", "-m", "base")
git(SEED, "push", "-q", SERVER, "main")
os.makedirs(os.path.dirname(CLONE))
os.makedirs(OTHER)
git(ROOT, "clone", "-q", SERVER, CLONE)
git(CLONE, "worktree", "add", "-q", "-b", "feat", WT)
put(WT, ".claude/commands/c.md", "C2\n")       # своя версия команды — не слита
put(WT, ".claude/agents/own.md", "OWN\n")      # свой агент — на main его нет
git(WT, "add", "-A")
git(WT, "commit", "-q", "-m", "feat: своё")
FEAT = git(WT, "rev-parse", "HEAD")
P.write_json(os.path.join(STATE, "domains.json"),
             {"domains": {"athena-x": ["~/projects/app"], "metis-y": ["~/projects/other"]}})
C.origin_url = lambda bare, d: "file://" + SERVER   # адрес сервера теста: github.com в тесте нет


def stuck():
    """Диск копии после checkout, который не смог переписать защищённые пути (EPERM)."""
    put(WT, ".claude/skills/a/SKILL.md", "OLD\n")              # HEAD == main → привести
    os.unlink(os.path.join(WT, ".claude/settings.json"))       # HEAD == main → вернуть
    put(WT, ".claude/commands/c.md", "C-old\n")                 # HEAD (C2) ≠ main (C1) → отказ
    put(WT, ".claude/agents/own.md", "x\n")                     # в HEAD есть, на main нет → отказ
    put(WT, ".claude/skills/stale/SKILL.md", "STALE\n")         # нет ни в HEAD, ни на main → удалить
    put(WT, "README.md", "r-dirty\n")                          # вне защищённых путей — не трогать
    put(WT, ".claude/settings.local.json", "{\"mine\": 1}\n")  # игнорируется — не трогать
    put(WT, ".claude/skills/local/SKILL.md", "LOCAL\n")       # игнорируемый навык — не удалять
    shutil.rmtree(os.path.join(WT, ".claude", "hooks"))
    os.makedirs(EXT, exist_ok=True)
    put(EXT, "h.sh", "evil\n")
    os.symlink(EXT, os.path.join(WT, ".claude", "hooks"))       # звено пути — ссылка наружу


QDIR = os.path.join(ROOT, "queue")
os.makedirs(QDIR)
N = [0]


def handle(window="athena-x", d=WT, merge=False):
    N[0] += 1
    rid = f"20261122-120000-{N[0]:06x}"
    req = {"v": 1, "id": rid, "kind": "claude-sync", "dir": d, **({"merge": True} if merge else {})}
    check(f"check_request принимает claude-sync ({rid})", O.check_request(req, rid) is None, O.check_request(req, rid))
    return O.handle(QDIR, window, rid, req)


# --- привязка в outside.py -----------------------------------------------------------------------------------------
check("вид claude-sync — проходу серверов", O._req_kind({"kind": "claude-sync"}) == "serve")
check("вид test — проходу тестов", O._req_kind({"kind": "test"}) == "test")
check("лишний флаг — код 2", O.main(["claude-sync", "--sha", "abc1234"]) == 2)
check("--wait не число — код 2", O.main(["claude-sync", "--wait", "x"]) == 2)
check("--merge с лишним флагом — код 2", O.main(["claude-sync", "--merge", "--sha", "abc1234"]) == 2)

# --- шаблоны песочницы ---------------------------------------------------------------------------------------------
check("защищены навык, команда, агент, хук, настройки, .mcp.json на любой глубине",
      all(C.protected(p) for p in (".claude/skills/a/SKILL.md", ".claude/commands/c.md", ".claude/agents/x.md",
                                   ".claude/hooks/h.sh", ".claude/settings.json", ".claude/settings.local.json",
                                   ".mcp.json", "app/.mcp.json", "app/.claude/skills/b/SKILL.md", ".husky/pre-commit")))
check("не защищены README, .claude/other, вложенные копии .claude/worktrees/*",
      not any(C.protected(p) for p in ("README.md", ".claude/other.md", ".claude/worktrees/x/.claude/skills/a",
                                       "src/settings.json", "../.mcp.json")))
check("удалять можно только навыки, команды и агентов",
      all(C.deletable(p) for p in (".claude/skills/x/SKILL.md", ".claude/commands/c.md", "a/.claude/agents/x.md")))
check("настройки, .mcp.json, хуки, .husky и настройки внутри навыка — не удаляются",
      not any(C.deletable(p) for p in (".claude/settings.json", ".claude/settings.local.json", ".mcp.json",
                                       ".claude/hooks/h.sh", ".husky/pre-commit", ".claude/skills/x/.claude/settings.json",
                                       ".claude/skills/x/.claude/hooks/h.sh")))
check("свой драйвер в атрибутах найден, встроенные — нет",
      C.bad_attrs("# c\n* merge=evil\n*.py diff=python\n*.bin -diff binary\n[attr]m filter=lfs\nx merge=union", "f")
      == ["f: merge=evil", "f: filter=lfs"], C.bad_attrs("* merge=evil\n[attr]m filter=lfs", "f"))

# --- папка не окна ------------------------------------------------------------------------------------------------
stuck()
res = handle(window="metis-y")
check("папка не из реестра окна — отказ без изменений", res.get("state") == "failed" and "не из папок" in
      str(res.get("why")) and read(WT, ".claude/skills/a/SKILL.md") == "OLD\n", res)

# --- незаконченный rebase и merge ---------------------------------------------------------------------------------
GITDIR = git(WT, "rev-parse", "--absolute-git-dir")
for marker, is_dir in (("rebase-merge", True), ("MERGE_HEAD", False)):
    p = os.path.join(GITDIR, marker)
    if is_dir:
        os.makedirs(p)
    else:
        put(GITDIR, marker, FEAT + "\n")
    res = handle()
    check(f"{marker}: отказ «закончи или отмени», файлы не тронуты",
          res.get("state") == "failed" and "закончи или отмени" in str(res.get("why"))
          and read(WT, ".claude/skills/a/SKILL.md") == "OLD\n"
          and read(WT, ".claude/skills/stale/SKILL.md") == "STALE\n", res)
    if is_dir:
        shutil.rmtree(p)
    else:
        os.unlink(p)

# --- основной проход: окно ещё и подделало свой origin/main под feat --------------------------------------------
git(WT, "update-ref", "refs/remotes/origin/main", FEAT)
INDEX = os.path.join(GITDIR, "index")
before = digest(INDEX)
res = handle()
synced, refused = res.get("synced") or [], res.get("refused") or []
check("итог done, код 1 (есть отказы)", res.get("state") == "done" and res.get("code") == 1, res)
check("код выхода status — 1", O.result_code(res) == 1, res)
check("HEAD == main: навык приведён к HEAD", read(WT, ".claude/skills/a/SKILL.md") == "A1\n", synced)
check("HEAD == main: удалённый settings.json возвращён", read(WT, ".claude/settings.json") == "{\"s\": 1}\n", synced)
check("своя версия в HEAD (не на main) — отказ, файл не тронут",
      read(WT, ".claude/commands/c.md") == "C-old\n" and any(x.startswith(".claude/commands/c.md:") for x in refused),
      refused)
check("подделанный origin/main копии не в счёт: агент только из feat — отказ",
      read(WT, ".claude/agents/own.md") == "x\n" and any(x.startswith(".claude/agents/own.md:") for x in refused),
      refused)
check("нет ни в HEAD, ни на main — удалён вместе с пустой папкой",
      not os.path.lexists(os.path.join(WT, ".claude/skills/stale")), synced)
check("вне защищённых путей — не тронут", read(WT, "README.md") == "r-dirty\n")
check("игнорируемый settings.local.json — не тронут", read(WT, ".claude/settings.local.json") == "{\"mine\": 1}\n")
check("игнорируемый навык не удалён, игнорируемые — без отказа",
      read(WT, ".claude/skills/local/SKILL.md") == "LOCAL\n" and not [x for x in refused if "local" in x], refused)
check("ссылка в звене пути не пройдена: файл за ней не тронут, ссылка на месте, отказ",
      read(EXT, "h.sh") == "evil\n" and os.path.islink(os.path.join(WT, ".claude", "hooks"))
      and any(x.startswith(".claude/hooks/h.sh:") for x in refused), refused)
check("индекс git копии не изменён", digest(INDEX) == before)
check("временных файлов записи не осталось",
      not [n for n in os.listdir(os.path.join(WT, ".claude", "skills", "a")) if "claude-sync" in n])
check("итог в папке заявок — с путями", "SKILL.md" in json.dumps(
      json.loads(read(QDIR, res["id"] + ".result.json") or "{}"), ensure_ascii=False))
check("свой bare сверки убран", not [n for n in os.listdir(O.root("claude-sync")) if n.startswith("bare-")])

# --- всё совпадает — приводить нечего, код 0 ----------------------------------------------------------------------
os.unlink(os.path.join(WT, ".claude", "hooks"))
git(WT, "checkout", "-q", "--", ".claude")
res = handle()
check("всё совпадает с HEAD — done, код 0, без сети", res.get("state") == "done" and res.get("code") == 0
      and not res.get("synced") and not res.get("refused"), res)

# --- окно добавило settings.local.json в индекс и положило свой хук: не удалять, отказ ----------------------------
git(WT, "add", "-f", ".claude/settings.local.json")
put(WT, ".claude/hooks/new.sh", "echo mine\n")
res = handle()
refused = res.get("refused") or []
check("settings.local.json в индексе (и в .gitignore) — не удалён, отказ",
      read(WT, ".claude/settings.local.json") == "{\"mine\": 1}\n" and res.get("code") == 1
      and any(x.startswith(".claude/settings.local.json:") for x in refused), res)
check("хук, которого нет ни в HEAD, ни на main, — не удалён, отказ", read(WT, ".claude/hooks/new.sh") == "echo mine\n"
      and any(x.startswith(".claude/hooks/new.sh:") for x in refused), refused)
git(WT, "rm", "-q", "--cached", ".claude/settings.local.json")
os.unlink(os.path.join(WT, ".claude/hooks/new.sh"))
git(WT, "checkout", "-q", "--", "README.md")

# --- --merge: сервер ушёл вперёд ----------------------------------------------------------------------------------
MAIN0 = git(SEED, "rev-parse", "HEAD")
for rel, text in ((".claude/skills/a/SKILL.md", "A2\n"), (".claude/skills/new/SKILL.md", "N\n"),
                  ("newfile.txt", "NEW\n"), ("README.md", "r2\n")):
    put(SEED, rel, text)
git(SEED, "add", "-A")
git(SEED, "commit", "-q", "-m", "main: дальше")
git(SEED, "push", "-q", SERVER, "main")
TIP = git(SEED, "rev-parse", "HEAD")


def mh():
    return os.path.lexists(os.path.join(GITDIR, "MERGE_HEAD"))


def refused_with(res, *words):
    return res.get("state") == "failed" and all(w in str(res.get("why")) for w in words) and not mh()


res = handle(merge=True)
check("--merge: коммита базы нет в клоне — отказ «сначала fetch»", refused_with(res, "pantheon git fetch"), res)

body = subprocess.run(["git", "-C", WT, "cat-file", "commit", FEAT], capture_output=True, check=True).stdout
FAKE = os.path.join(CLONE, ".git", "objects", TIP[:2], TIP[2:])
os.makedirs(os.path.dirname(FAKE), exist_ok=True)
with open(FAKE, "wb") as fh:
    fh.write(zlib.compress(b"commit %d\0" % len(body) + body))
res = handle(merge=True)
check("--merge: под SHA базы в клоне чужой коммит — отказ, слияния нет", refused_with(res, "не совпало с сервером"),
      res)
os.unlink(FAKE)
git(CLONE, "fetch", "-q", "origin")

res = handle(merge=True)
check("--merge: ветка меняет защищённые пути — отказ без слияния",
      refused_with(res, "меняет защищённые пути", ".claude/commands/c.md"), res)

git(WT, "checkout", "-q", "-b", "m1", MAIN0)
put(WT, "src.txt", "s1\n")
git(WT, "add", "src.txt")
git(WT, "commit", "-q", "-m", "m1: код")

put(WT, "src.txt", "dirty\n")
res = handle(merge=True)
check("--merge: незакоммиченный код — отказ", refused_with(res, "незакоммиченные", "src.txt"), res)
git(WT, "checkout", "-q", "--", "src.txt")

put(WT, "newfile.txt", "OTHER\n")
res = handle(merge=True)
check("--merge: неотслеживаемый файл не равен базе — отказ, файл на месте",
      refused_with(res, "newfile.txt") and read(WT, "newfile.txt") == "OTHER\n", res)

ATTR = os.path.join(CLONE, ".git", "info", "attributes")
put(os.path.dirname(ATTR), "attributes", "* merge=evil\n")
res = handle(merge=True)
check("--merge: свой драйвер в info/attributes — отказ", refused_with(res, "свой драйвер", "merge=evil"), res)
os.unlink(ATTR)

put(WT, "newfile.txt", "NEW\n")
put(WT, ".claude/skills/new/SKILL.md", "N\n")
HOOKS, MARK = os.path.join(CLONE, ".git", "hooks"), os.path.join(ROOT, "hook-ran")
NAMES = ("reference-transaction", "post-merge", "pre-merge-commit", "post-checkout", "post-index-change")
for h in NAMES:
    put(HOOKS, h, f"#!/bin/sh\necho {h} >> '{MARK}'\n")
    os.chmod(os.path.join(HOOKS, h), 0o755)
res = handle(merge=True)
for h in NAMES:
    os.unlink(os.path.join(HOOKS, h))
check("--merge: слито без конфликтов — код 0, MERGE_HEAD = SHA сервера",
      res.get("state") == "done" and res.get("code") == 0 and (read(GITDIR, "MERGE_HEAD") or "").strip() == TIP
      and "без конфликтов" in str(res.get("note")), res)
check("--merge: защищённые пути и код — как на базе", read(WT, ".claude/skills/a/SKILL.md") == "A2\n"
      and read(WT, ".claude/skills/new/SKILL.md") == "N\n" and read(WT, "README.md") == "r2\n"
      and read(WT, "src.txt") == "s1\n")
check("--merge: неотслеживаемые, равные базе, убраны и слиты", read(WT, "newfile.txt") == "NEW\n"
      and any("неотслеживаемый" in x for x in res.get("synced") or []), res)
check("--merge: хуки клона не запущены", not os.path.exists(MARK), read(ROOT, "hook-ran"))
check("--merge: игнорируемые не тронуты", read(WT, ".claude/settings.local.json") == "{\"mine\": 1}\n"
      and read(WT, ".claude/skills/local/SKILL.md") == "LOCAL\n")

res = handle(merge=True)
check("--merge при незаконченном merge — отказ «закончи или отмени»",
      res.get("state") == "failed" and "закончи или отмени" in str(res.get("why")), res)
git(WT, "merge", "--abort")

put(WT, "README.md", "mine\n")
git(WT, "commit", "-q", "-am", "m1: свой README")
res = handle(merge=True)
check("--merge: конфликт оставлен роли — код 1, MERGE_HEAD есть, README в списке",
      res.get("state") == "done" and res.get("code") == 1 and res.get("conflicts") == ["README.md"] and mh()
      and "<<<<<<<" in (read(WT, "README.md") or ""), res)
check("--merge: при конфликте защищённые пути — как на базе", read(WT, ".claude/skills/a/SKILL.md") == "A2\n")
git(WT, "merge", "--abort")

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} проверок")
if FAILS:
    print("FAIL: " + "; ".join(FAILS))
    sys.exit(1)
