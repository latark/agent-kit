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
    неотслеживаемый файл не равен базе, в info/attributes свой драйвер, merge не закончен; хуки клона не запускаются;
  - --merge против окна, которое пишет объекты и .git клона: подложенный коммит (другие родители), дерево, blob — отказ;
    blob подложен после проверки — путь переписан из своего bare; merge упал без MERGE_HEAD — убранные файлы и
    ссылка возвращены; HEAD сдвинулся до или во время слияния, commondir или звено пути подменены — отказ или откат,
    чужого на диске нет; конфиг и атрибуты git берёт из GIT_COMMON_DIR, а не из commondir окна.
Плюс привязка в outside.py: вид claude-sync идёт проходу серверов, check_request его принимает, лишний флаг — код 2.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311, mkroot  # pantheon.py — только на Python 3.11+
import _claude_git as H  # noqa: E402
from _claude_git import digest, git, mv, put, read  # noqa: E402

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
M = C.mm()
FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{extra}]"))
    if not cond:
        FAILS.append(name)


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
os.symlink("README.md", os.path.join(SEED, "link.txt"))
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
# git одних версий читает подложенный коммит (сверка сырого объекта), других — не находит его (нет коммита): оба отказ
check("--merge: под SHA базы в клоне чужой коммит — отказ, слияния нет",
      refused_with(res, "не совпал с сервером") or refused_with(res, "нет коммита"), res)
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

M1 = git(WT, "rev-parse", "HEAD")
A1 = git(WT, "rev-parse", MAIN0 + ":.claude/skills/a/SKILL.md")
A2 = git(WT, "rev-parse", TIP + ":.claude/skills/a/SKILL.md")
os.unlink(os.path.join(WT, "newfile.txt"))


def untracked():
    """Неотслеживаемые файлы, равные базе: файл, навык и ссылка (их слияние создаст)."""
    put(WT, "newfile.txt", "NEW\n")
    put(WT, ".claude/skills/new/SKILL.md", "N\n")
    link = os.path.join(WT, "link.txt")
    if os.path.lexists(link):
        os.unlink(link)
    os.symlink("README.md", link)


def back_to_m1():
    git(WT, "reset", "-q", "--hard", M1)   # и MERGE_*; код, оставленный откатом (его возвращает роль), — убрать
    for rel in ("newfile.txt", "link.txt"):
        if os.path.lexists(os.path.join(WT, rel)):
            os.unlink(os.path.join(WT, rel))


# --- ветка уже на базе — сливать нечего ---------------------------------------------------------------------------
git(WT, "checkout", "-q", "-b", "attip", TIP)
res = handle(merge=True)
check("--merge: HEAD уже на базе — done, код 0, «сливать нечего», без MERGE_HEAD",
      res.get("state") == "done" and res.get("code") == 0 and "сливать нечего" in str(res.get("note")) and not mh(), res)
git(WT, "checkout", "-q", "m1")
git(WT, "branch", "-q", "-D", "attip")

# --- изменение только в индексе (рабочее дерево равно индексу) — diff-index ----------------------------------------
put(WT, "src.txt", "staged\n")
git(WT, "add", "src.txt")
res = handle(merge=True)
check("--merge: изменение только в индексе — отказ «незакоммиченные»", refused_with(res, "незакоммиченные", "src.txt"),
      res)
back_to_m1()

# --- .gitattributes: в HEAD и неотслеживаемый на диске -------------------------------------------------------------
put(WT, ".gitattributes", "* merge=evil\n")
git(WT, "add", ".gitattributes")
git(WT, "commit", "-q", "-m", "m1: атрибуты")
res = handle(merge=True)
check("--merge: свой драйвер в .gitattributes HEAD — отказ", refused_with(res, "HEAD:.gitattributes", "merge=evil"), res)
back_to_m1()
put(WT, "sub/.gitattributes", "*.txt filter=evil\n")
res = handle(merge=True)
check("--merge: свой драйвер в неотслеживаемом sub/.gitattributes — отказ",
      refused_with(res, "sub/.gitattributes", "filter=evil"), res)
shutil.rmtree(os.path.join(WT, "sub"))

# --- sync: пути нет в HEAD, а на базе есть; папка на месте файла -------------------------------------------------
put(WT, ".claude/skills/new/SKILL.md", "X\n")
os.unlink(os.path.join(WT, ".claude/commands/c.md"))
os.mkdir(os.path.join(WT, ".claude/commands/c.md"))
res = handle()
refused = res.get("refused") or []
check("sync: пути нет в HEAD, а на базе есть — отказ, файл не тронут",
      read(WT, ".claude/skills/new/SKILL.md") == "X\n"
      and any(x.startswith(".claude/skills/new/SKILL.md: пути нет в HEAD, а на") for x in refused), res)
check("sync: на месте файла папка — отказ, папка на месте", os.path.isdir(os.path.join(WT, ".claude/commands/c.md"))
      and any(x.startswith(".claude/commands/c.md:") and "папка" in x for x in refused), refused)
os.rmdir(os.path.join(WT, ".claude/commands/c.md"))
shutil.rmtree(os.path.join(WT, ".claude/skills/new"))
back_to_m1()

# --- обход больше WALK_MAX — отказ --------------------------------------------------------------------------------
walk_max, C.WALK_MAX = C.WALK_MAX, 3
res = handle()
C.WALK_MAX = walk_max
check("sync: файлов больше WALK_MAX — отказ всей заявке", res.get("state") == "failed"
      and "больше 3 файлов" in str(res.get("why")), res)

# --- объекты клона подменены: родители коммита, дерево, blob под честным коммитом ----------------------------------
OBJS = os.path.join(CLONE, ".git", "objects")


plant = lambda sha, kind, body: H.plant(OBJS, sha, kind, body)   # noqa: E731
unplant = H.unplant

raw = subprocess.run(["git", "-C", WT, "cat-file", "commit", TIP], capture_output=True, check=True).stdout
po = plant(TIP, b"commit", b"".join(x for x in raw.splitlines(True) if not x.startswith(b"parent ")))
res = handle(merge=True)
unplant(po)
check("--merge: коммит базы с тем же деревом, но без родителей — отказ", refused_with(res, "не совпал с сервером"), res)
other = subprocess.run(["git", "-C", WT, "cat-file", "tree", MAIN0 + "^{tree}"], capture_output=True, check=True).stdout
po = plant(git(WT, "rev-parse", TIP + "^{tree}"), b"tree", other)
res = handle(merge=True)
unplant(po)
check("--merge: дерево базы в клоне подменено — отказ", refused_with(res, "дерево", "не совпало с сервером"), res)
po = plant(A2, b"blob", b"EVIL\n")
res = handle(merge=True)
unplant(po)
check("--merge: blob навыка под честным коммитом подменён — отказ", refused_with(res, "не совпал со своим хешем"), res)

# --- merge не прошёл (MERGE_HEAD нет): убранные файлы и ссылка возвращены своей записью ----------------------------
untracked()
cfg = M.MERGE_CFG
M.MERGE_CFG = tuple("merge.verifySignatures=true" if x == "merge.verifySignatures=false" else x for x in cfg)
res = handle(merge=True)
M.MERGE_CFG = cfg
check("--merge: git merge упал без MERGE_HEAD — отказ с кодом", refused_with(res, "не прошёл (код"), res)
check("--merge: после сбоя убранные неотслеживаемые возвращены — файл, навык и ссылка",
      read(WT, "newfile.txt") == "NEW\n" and read(WT, ".claude/skills/new/SKILL.md") == "N\n"
      and os.path.islink(os.path.join(WT, "link.txt")) and os.readlink(os.path.join(WT, "link.txt")) == "README.md")
back_to_m1()

# --- после git merge на диске чужое: итог защищённых путей — своя запись из своего bare ----------------------------
SH = []
check_clean = M.check_clean


def cc_shadow(d):
    check_clean(d)
    SH.append(plant(A2, b"blob", b"EVIL\n"))   # окно подложило blob после проверки объектов


M.check_clean = cc_shadow
res = handle(merge=True)
M.check_clean = check_clean
unplant(SH.pop())
check("--merge: git записал подложенный blob — путь переписан из своего bare, слияние есть",
      res.get("state") == "done" and mh() and read(WT, ".claude/skills/a/SKILL.md") == "A2\n"
      and any("после git merge не был равен базе" in x for x in res.get("synced") or []), res)
r = subprocess.run(["git", "-C", WT, "merge", "--abort"], capture_output=True, text=True)
check("--merge: после своей записи индекс освежён — роль может git merge --abort", r.returncode == 0, r.stderr)
back_to_m1()

settle, SETTLE = M.settle, []


def settle_bad(d, base, want, rels):
    done, bad = settle(d, base, want, rels)
    if not SETTLE:   # первая — приведение к базе после слияния: путь записан, но «не вышло» — откат
        SETTLE.append(1)
        bad = bad + ["x: проба отката"]
    return done, bad


M.check_clean, M.settle = cc_shadow, settle_bad
res = handle(merge=True)
M.check_clean, M.settle = check_clean, settle
unplant(SH.pop())
check("--merge: откат после своей записи — merge --abort прошёл (индекс освежён), чужого на диске нет",
      refused_with(res, "не привести к базе", "отменено") and "abort не прошёл" not in str(res.get("why"))
      and read(WT, ".claude/skills/a/SKILL.md") != "EVIL\n", res)
back_to_m1()


def drift():
    tree = git(WT, "rev-parse", "HEAD^{tree}")
    git(WT, "update-ref", "HEAD", git(WT, "commit-tree", tree, "-p", "HEAD", "-m", "drift"))


def cc_drift(d):
    check_clean(d)
    drift()


M.check_clean = cc_drift
res = handle(merge=True)
M.check_clean = check_clean
check("--merge: HEAD сдвинулся до слияния — отказ, слияния нет",
      refused_with(res, "сдвинулся после проверки") and "отменено" not in str(res.get("why")), res)
back_to_m1()
git_merge = M.git_merge


def gm_drift(d, base, plan):
    git_merge(d, base, plan)
    SH.append(plant(A1, b"blob", b"EVIL\n"))   # версия HEAD пути, который поменяла база, — подложена в клоне
    drift()


M.git_merge = gm_drift
res = handle(merge=True)
M.git_merge = git_merge
unplant(SH.pop())
check("--merge: HEAD сдвинулся во время слияния, blob HEAD подложен — откат: на диске снимок, ветка на head_sha",
      refused_with(res, "сдвинулся во время слияния", "отменено")
      and read(WT, ".claude/skills/a/SKILL.md") == "A1\n" and git(WT, "rev-parse", "refs/heads/m1") == M1, res)
back_to_m1()

SETTINGS = read(WT, ".claude/settings.local.json")


WINDOW = {".claude/settings.local.json": "{\"evil\": 1}\n", ".claude/hooks/x.sh": "echo evil\n"}


def window_commit(files=WINDOW):
    return H.window_commit(WT, os.path.join(ROOT, "window.index"), files)


def gm_ref(d, base, plan):
    git_merge(d, base, plan)
    git(WT, "update-ref", "refs/heads/m1", window_commit())   # окно двигает ref, ждавши MERGE_HEAD
    put(WT, ".claude/settings.local.json", "{\"evil\": 1}\n")
    put(WT, ".claude/hooks/x.sh", "echo evil\n")


M.git_merge = gm_ref
res = handle(merge=True)
M.git_merge = git_merge
check("--merge: ref ветки сдвинут на коммит окна — откат: новых настроек и хука нет, бывшие — как до прохода",
      refused_with(res, "сдвинулся во время слияния", "отменено")
      and not os.path.lexists(os.path.join(WT, ".claude/hooks/x.sh"))
      and read(WT, ".claude/settings.local.json") == SETTINGS and git(WT, "rev-parse", "refs/heads/m1") == M1
      and read(WT, ".claude/skills/a/SKILL.md") == "A1\n", res)
back_to_m1()


def gm_extra(d, base, plan):
    git_merge(d, base, plan)
    put(WT, ".claude/hooks/y.sh", "echo late\n")   # появился под защищёнными путями во время слияния
    put(WT, ".mcp.JSON", "{}\n")                    # и в другом регистре — для APFS и песочницы это .mcp.json
    put(WT, ".claude/worktrees/y/.claude/settings.json", "{}\n")   # и во вложенной копии


def nested():   # файлы под .claude/worktrees копии (папки после удаления файлов остаются)
    return [f for _, _, fs in os.walk(os.path.join(WT, ".claude", "worktrees")) for f in fs]


M.git_merge = gm_extra
res = handle(merge=True)
M.git_merge = git_merge
check("--merge: успех, а под защищёнными путями лишний файл — удалён, игнорируемое до прохода на месте",
      res.get("state") == "done" and mh() and not os.path.lexists(os.path.join(WT, ".claude/hooks/y.sh"))
      and ".mcp.JSON" not in os.listdir(WT) and not nested()
      and read(WT, ".claude/settings.local.json") == SETTINGS
      and any(".claude/hooks/y.sh: удалён" in x for x in res.get("synced") or []), res)
back_to_m1()

# --- commondir подменён: до слияния, во время, и git его не читает (GIT_COMMON_DIR) --------------------------------
with open(os.path.join(GITDIR, "commondir")) as fh:
    CDIR = fh.read()
EVILC, MARK2 = os.path.join(ROOT, "evilc"), os.path.join(ROOT, "filter-ran")
put(EVILC, "config", f"[core]\n\trepositoryformatversion = 0\n[filter \"evil\"]\n\tsmudge = touch '{MARK2}'\n")
put(EVILC, "info/attributes", "* filter=evil\n")
for name in ("objects", "refs", "packed-refs"):   # ветки и объекты — те же: git с чужим commondir дошёл бы до слияния
    if os.path.lexists(os.path.join(CLONE, ".git", name)):
        os.symlink(os.path.join(CLONE, ".git", name), os.path.join(EVILC, name))


def cc_swap(d):
    check_clean(d)
    put(GITDIR, "commondir", EVILC + "\n")


def gm_swap(d, base, plan):
    git_merge(d, base, plan)
    put(GITDIR, "commondir", EVILC + "\n")


M.check_clean = cc_swap
res = handle(merge=True)
M.check_clean = check_clean
put(GITDIR, "commondir", CDIR)
check("--merge: commondir подменён до слияния — отказ без слияния, фильтр не запущен",
      refused_with(res, "изменены после проверки") and "отменено" not in str(res.get("why"))
      and not os.path.exists(MARK2), res)
back_to_m1()
M.git_merge = gm_swap
res = handle(merge=True)
M.git_merge = git_merge
put(GITDIR, "commondir", CDIR)
check("--merge: commondir подменён во время слияния — откат", refused_with(res, "изменены после проверки", "отменено")
      and not os.path.exists(MARK2), res)
back_to_m1()
check_repo, C.check_repo = C.check_repo, (lambda d: None)
M.check_clean = cc_swap
res = handle(merge=True)
M.check_clean, C.check_repo = check_clean, check_repo
put(GITDIR, "commondir", CDIR)
check("--merge: и без сверки конфиг и атрибуты — из проверенного common (GIT_COMMON_DIR): фильтр окна не запущен",
      res.get("state") == "done" and (read(GITDIR, "MERGE_HEAD") or "").strip() == TIP and not os.path.exists(MARK2),
      res)
back_to_m1()

KEEP = []
for swap, name in (((".git", "gitdir: " + ROOT + "\n"), ".git-файл подменён"),
                   (("commondir", None), "commondir стал ссылкой")):
    def gm_broken(d, base, plan, swap=swap):
        git_merge(d, base, plan)
        put(WT, ".claude/hooks/x.sh", "echo evil\n")
        put(WT, ".claude/settings.local.json", "{\"evil\": 1}\n")
        put(WT, ".claude/worktrees/y/.claude/hooks/z.sh", "echo evil\n")
        path = os.path.join(WT if swap[0] == ".git" else GITDIR, swap[0])
        KEEP.append((path, read(*os.path.split(path))))
        os.unlink(path)
        if swap[1]:
            put(*os.path.split(path), swap[1])
        else:
            os.symlink(os.path.join(CLONE, ".git"), path)
    KEEP.clear()
    put(WT, ".claude/worktrees/y/.claude/settings.json", "{\"own\": 1}\n")   # своё вложенной копии — в снимке
    M.git_merge = gm_broken
    res = handle(merge=True)
    M.git_merge = git_merge
    os.unlink(KEEP[0][0])
    put(*os.path.split(KEEP[0][0]), KEEP[0][1])
    own = read(WT, ".claude/worktrees/y/.claude/settings.json")
    check(f"--merge: {name} во время слияния, repair не смог — ветку и индекс не трогал, снимок восстановлен",
          res.get("state") == "failed" and "ветку и индекс не трогал" in str(res.get("why"))
          and not os.path.lexists(os.path.join(WT, ".claude/hooks/x.sh")) and nested() == ["settings.json"]
          and own == "{\"own\": 1}\n" and read(WT, ".claude/settings.local.json") == SETTINGS
          and read(WT, ".claude/skills/a/SKILL.md") == "A1\n", res)
    os.unlink(os.path.join(WT, ".claude/worktrees/y/.claude/settings.json"))
    back_to_m1()

# --- регистр и вложенные копии: отказ до слияния; откат рабочее дерево через git не пишет --------------------------
ODD = {".claude/Settings.local.json": "{\"evil\": 1}\n", ".claude/worktrees/y/.claude/settings.json": "{\"e\": 1}\n"}
for rel, text in ODD.items():
    for where in ("HEAD", "индекс"):
        c = window_commit({rel: text})
        git(WT, "update-ref", "refs/heads/m1", c if where == "HEAD" else M1)
        git(WT, "read-tree", c)
        res = handle(merge=True)
        git(WT, "update-ref", "refs/heads/m1", M1)
        git(WT, "read-tree", M1)
        check(f"--merge: {rel} в {where} — отказ до слияния, на диск не записан", refused_with(res, "не буква в букву",
              rel) and read(WT, ".claude/settings.local.json") == SETTINGS and not nested(), res)


ODDC, run_ = window_commit(ODD), C._run


def run_plant(d, *args, **kw):
    """git прочёл под head_sha дерево окна (свободный объект; одни версии git подмену замечают, другие — нет)."""
    r = run_(d, *args, **kw)
    if args[:2] == ("read-tree", "--reset"):
        git(WT, "read-tree", ODDC)
    return r


M.git_merge, C._run = (lambda d, base, plan: (git_merge(d, base, plan), drift())), run_plant
res = handle(merge=True)
M.git_merge, C._run = git_merge, run_
IDX = git(WT, "ls-files")   # индекс отката — дерево окна, а на диск git ничего не записал
git(WT, "read-tree", M1)
why = str(res.get("why"))
check("--merge: откат с подложенным деревом head_sha (регистр, вложенная копия) — git файлов не записал",
      refused_with(res, "отменено") and read(WT, ".claude/settings.local.json") == SETTINGS
      and not nested() and git(WT, "rev-parse", "refs/heads/m1") == M1 and ".claude/Settings.local.json" in IDX
      and ".claude/worktrees/y/.claude/settings.json" in IDX, (res, IDX))
check("--merge: откат код не трогает — README слияния на месте и в итоге «верни сам»",
      read(WT, "README.md") == "r2\n" and "верни сам" in why and "README.md" in why and "newfile.txt" in why, why)
back_to_m1()

# --- обход полный (вложенные копии, подпапки любой глубины), без предела; предел — только у снимка, до записи -----
SUBS, GONE = ".claude/worktrees/q/sub/.claude/settings.json", ".claude/worktrees/q/.mcp.json"
DEEP = ".claude/skills/deep/" + "d/" * 70 + "SKILL.md"   # глубже DEPTH_MAX: обход не удалит, индекс в откате — да
EVIL = {"app/.claude/settings.json": "{}\n", ".claude/skills/a/SKILL.md": "E\n"}


def gm_deep(d, base, plan, shift, lock):
    assert C.DEADLINE > time.monotonic() and not setattr(C, "DEADLINE", 0), "run не поставил срок до первой записи"
    git_merge(d, base, plan)
    assert C.DEADLINE > time.monotonic(), "срок не начат заново после git merge"
    for rel, text in [(f".claude/skills/zz/f{i}.md", "x\n") for i in range(40)] + [(SUBS, "{\"h\": 1}\n")] + [*EVIL.items()]:
        put(WT, rel, text)
    put(WT, GONE, "{}\n")
    git(WT, "add", "-f", SUBS, GONE)   # ort слил правку базы в путь, куда дерево HEAD «переименовало» настройки
    os.unlink(os.path.join(WT, GONE))   # и путь, который есть только в индексе
    for rel in (".claude/skills/lock/x.md", DEEP)[:2 if lock == 1 else 0]:
        put(WT, rel, "x\n")   # 1: папка без прав и цепочка глубже DEPTH_MAX с навыком внизу; 2: потолок обхода истёк
    _ = lock == 1 and git(WT, "add", "-f", DEEP)
    for rel in (".claude/hooks/x.sh", ".mcp.json", "app/.mcp.json", ".claude/settings.json")[:lock and (1 if lock == 1 else 4)]:
        put(WT, rel, "{\"evil\": 1}\n")   # злые настройки корня и первого уровня; 3: и мусор в .claude/junk — их убирает spots
    _ = lock == 3 and [put(WT, f".claude/junk/d{i}/f.md", "x\n") for i in range(300)]
    _ = lock and (os.chmod(os.path.join(WT, ".claude/skills/lock"), 0) if lock == 1 else [setattr(C, k, -1) for k in ("HANG_MAX", "HOT_MAX")[:1 if lock == 2 else 2]])
    _ = shift and drift()


def run_fail(fail, hits):   # git с кодом 128 на fail: ls-files -o — только первый вызов (план), ls-files -z — после merge
    def run(d, *a, **kw):
        if a[:2] == fail and (fail[1] == "-z" and mh() or fail[1] == "-o" and not hits):
            hits.append(a)
            return subprocess.CompletedProcess(a, 128, b"", b"")
        return run_(d, *a, **kw)
    return run


walk_max, C.WALK_MAX, deep_walk = C.WALK_MAX, 25, M.deep_walk
for shift, lock, blind, fail, words in (
        (0, 0, 0, (), ()), (0, 0, 1, (), ()), (1, 0, 0, ("ls-files", "-o"), ("возвращены к снимку", "ls-files -o не прошёл")),
        (0, 0, 0, ("ls-files", "-z"), ("индекс после слияния не сверен",)),
        (1, 1, 0, (), ("НЕ возвращены", "не открыта", "глубже 64", "владельцу", "/* и глубже", "проход не удаляет")),
        (1, 2, 0, (), ("срок обхода истёк", "НЕ возвращены", "владельцу")), (1, 3, 0, (), ("срок обхода истёк", "НЕ возвращены", "владельцу"))):
    M.git_merge = lambda d, base, plan, a=shift, b=lock: gm_deep(d, base, plan, a, b)
    M.deep_walk = (lambda d, plan, bad, on_found: None) if blind else deep_walk   # вторая защита: пути индекса — и без обхода
    C._run, t0, s0 = run_fail(fail, []), time.monotonic(), read(WT, ".claude/settings.json")
    res = handle(merge=True)
    M.git_merge, M.deep_walk, C._run, took, C.HANG_MAX, C.HOT_MAX = git_merge, deep_walk, run_, time.monotonic() - t0, 600, 600
    _ = lock == 1 and os.chmod(os.path.join(WT, ".claude/skills/lock"), 0o755)
    left = [r for r in (SUBS, "app/.claude/settings.json", ".claude/skills/zz/f0.md", ".claude/hooks/x.sh", ".mcp.json",
                        "app/.mcp.json", DEEP)[:1 if blind else 7] if os.path.lexists(os.path.join(WT, r)) and not (lock == 3 and "zz" in r)] + (
        ["долго"] if took > 30 else []) + (["settings.json"] if read(WT, ".claude/settings.json") != s0 else [])
    check(f"--merge: {SUBS} (правка базы), app/.claude, 40 навыков {(shift, lock, blind, fail)} — новых нет, {words}",
          not left and (refused_with(res, "отменено", *words) and read(WT, ".claude/skills/a/SKILL.md") == "A1\n"
                        if words else res.get("state") == "done"), (left, res))
    for rel in ("app", ".claude/skills/zz", ".claude/skills/lock", ".claude/skills/deep", ".claude/junk"):
        shutil.rmtree(os.path.join(WT, rel), True)
    back_to_m1()
WHY = {"merge": "оборвался", "read-tree": "git read-tree не прошёл", "-z": "после слияния сбой", "-o": "список кода не"}
for step in WHY:   # git убит по таймауту (Refused из _run) после записи хука — откат и снимок всё равно; -o — второй вызов
    def boom(d, *a, s=step, seen=[], **kw):   # noqa: B006 — счёт вызовов -o одного случая
        seen.append(s in a)
        if (s in a and (s != "-z" or mh()) and (s != "-o" or seen.count(True) > 1)) or (s in ("read-tree", "-o") and "merge" in a):
            _ = s in a and put(WT, ".claude/hooks/t.sh", "x\n")
            raise C.Refused(f"git {a[0]} не запустился (TimeoutExpired)")
        return run_(d, *a, **kw)
    C._run, s0 = boom, read(WT, ".claude/settings.json")
    res, C._run = handle(merge=True), run_
    check(f"--merge: {step} убит по таймауту после записи хука — хука нет, снимок возвращён, итог громкий",
          not os.path.lexists(os.path.join(WT, ".claude/hooks/t.sh")) and read(WT, ".claude/settings.json") == s0
          and refused_with(res, "отменено", WHY[step], "возвращены к снимку"), res)
    back_to_m1()
for i in range(30):   # во вложенной копии: sync их не считает (protected), снимок — считает
    put(WT, f".claude/worktrees/q/.claude/skills/zz/f{i}.md", "x\n")
put(WT, ".claude/skills/a/SKILL.md", "X\n")   # sync привёл бы к HEAD — но предел снимка проверен до первой записи
res = handle(merge=True)
check("--merge: снимок на пределе — отказ до слияния, диск не тронут", refused_with(res, "больше 25")
      and "отменено" not in str(res.get("why")) and read(WT, ".claude/skills/a/SKILL.md") == "X\n", res)
shutil.rmtree(os.path.join(WT, ".claude/worktrees/q"), True)
C.WALK_MAX = walk_max
back_to_m1()

# --- звено пути подменено после проверки (ссылка, другая папка) --------------------------------------------------
Base = C.Base
WTS = os.path.join(CLONE, ".claude", "worktrees")


link_parent = lambda: (mv((WTS, WTS + ".real")), os.symlink(WTS + ".real", WTS))   # noqa: E731
unlink_parent = lambda: (os.unlink(WTS), mv((WTS + ".real", WTS)))   # noqa: E731
other_dir, back_dir = (lambda: mv((WT, WT + ".moved"), (WT, None))), (lambda: mv((None, WT), (WT + ".moved", WT)))


for swap, undo, word, name in ((link_parent, unlink_parent, "подменено", "звено пути стало ссылкой"),
                               (other_dir, back_dir, "сменился inode", "на месте копии другая папка")):
    C.Base = lambda d, swap=swap: (Base(d), swap())[0]
    res = handle(merge=True)
    C.Base = Base
    undo()
    check(f"--merge: {name} после Base — отказ без записи", refused_with(res, word)
          and read(WT, ".claude/skills/a/SKILL.md") == "A1\n", res)

untracked()
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
check("--merge: неотслеживаемые, равные базе (и навык не из HEAD — skip в sync), убраны и слиты",
      read(WT, "newfile.txt") == "NEW\n" and os.readlink(os.path.join(WT, "link.txt")) == "README.md"
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

# --- в базе путь, защищённый не буква в букву, — отказ до слияния ---------------------------------------------------
put(SEED, "app/.MCP.json", "{}\n")
git(SEED, "add", "-A")
git(SEED, "commit", "-q", "-m", "main: регистр")
git(SEED, "push", "-q", SERVER, "main")
git(CLONE, "fetch", "-q", "origin")
res = handle(merge=True)
check("--merge: в базе app/.MCP.json — отказ до слияния", refused_with(res, "не буква в букву", "app/.MCP.json"), res)
os.unlink(os.path.join(SEED, "app/.MCP.json"))

# --- свой драйвер в .gitattributes базы -----------------------------------------------------------------------------
put(SEED, "sub/.gitattributes", "*.txt diff=evil\n")
git(SEED, "add", "-A")
git(SEED, "commit", "-q", "-m", "main: атрибуты")
git(SEED, "push", "-q", SERVER, "main")
git(CLONE, "fetch", "-q", "origin")
res = handle(merge=True)
check("--merge: свой драйвер в .gitattributes базы — отказ",
      refused_with(res, "origin/main:sub/.gitattributes", "diff=evil"), res)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} проверок")
if FAILS:
    print("FAIL: " + "; ".join(FAILS))
    sys.exit(1)
