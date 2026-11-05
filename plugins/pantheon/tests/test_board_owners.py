#!/usr/bin/env python3
"""Доска и карточки сходятся с фактами сами (metis-0868): хозяин задачи и следы работы проходом доски, свежий вид
после правки карточки, время журнала от кода.

1. Сессию переименовали — owner открытых карточек следует за ней по sessionId (память STATE/owner-sids.json), закрытые
   и чужие не трогаются; старое имя носит другое живое окно — не переносим.
2. Хозяин — сессия, которой нет среди окон, остановленная (`claude stop`) или с меткой `pantheon stop` (и координатор),
   — тревога «задача без хозяина» с готовой командой передачи; передали — тревога снята. Снимок сессий устарел —
   о хозяевах молчим.
3. Задача doing без ветки, worktree и открытого PR с её номером и без правки дольше 6 ч — тревога.
4. Правка карточки (`pantheon task set/new/…`) сразу запускает задачи расписания view и board; чтение (show) и
   неудачная правка — нет; пауза, выключенная задача — нет.
5. Время в начале --note не пишется в журнал (предупреждение); PANTHEON_NOW не датирует настоящее хранилище;
   строка журнала «из будущего» — хвост «время» в `pantheon check`.

Запуск: python3 -I plugins/pantheon/tests/test_board_owners.py  (код выхода 0 — все прошли; Python 3.11+)
"""
import atexit
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402 — CLI pantheon только на Python 3.11+

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="board-owners-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib")
RUN_PY = os.path.join(LIB, "run.py")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(LIB, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S, T = load("boardstatus"), load("tasks")
results = []
T0 = 1_792_800_000
H = 3600
DIRS = {"metis-pantheon", "example-site"}


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:1200]}]"))


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def card(tid, status="todo", owner="metis-pantheon", direction="metis-pantheon", kind="task", **f):
    return tid, ("", dict({"type": kind, "id": tid, "status": status, "owner": owner, "direction": direction}, **f), "")


def agent(sid, name, state="working"):
    return {"sessionId": sid, "name": name, "state": state}


# --- 1. переименование сессии: owner за sessionId ---------------------------------------------------------------------
tasks = dict([card("metis-0001", owner="dev-a"), card("metis-0002", "done", owner="dev-a"),
              card("metis-0003", "doing", owner="dev-a"), card("metis-0004", owner="dev-b")])
ren, known = S.owner_renames(tasks, [agent("sid-a", "dev-new")], {"sid-a": "dev-a"}, DIRS)
check("1. сессию переименовали → owner открытых карточек (todo, doing) за ней, закрытая и чужая не тронуты",
      ren == [("metis-0001", "dev-a", "dev-new", "sid-a"), ("metis-0003", "dev-a", "dev-new", "sid-a")]
      and known == {"sid-a": "dev-new"}, (ren, known))
ren, known = S.owner_renames(tasks, [agent("sid-a", "dev-a")], {}, DIRS)
check("1. первая встреча sessionId — только память имени, без переименований", ren == [] and known == {"sid-a": "dev-a"},
      (ren, known))
ren, _ = S.owner_renames(tasks, [agent("sid-a", "dev-new"), agent("sid-x", "dev-a")], {"sid-a": "dev-a"}, DIRS)
check("1. старое имя носит другое живое окно — карточки не переносим", ren == [], ren)
ren, _ = S.owner_renames(tasks, [agent("sid-a", "dev-new"), agent("sid-x", "dev-a (2)")], {"sid-a": "dev-a"}, DIRS)
check("1. … и копию имени («dev-a (2)») тоже считаем этим окном", ren == [], ren)
ren, _ = S.owner_renames(tasks, [agent("sid-a", "dev-new"), agent("sid-x", "dev-a", "stopped")], {"sid-a": "dev-a"}, DIRS)
check("1. старое имя у остановленного окна — переносим", [r[0] for r in ren] == ["metis-0001", "metis-0003"], ren)
tasks_k = dict([card("metis-0010", owner="metis-pantheon"), card("metis-0011", owner="zeus"), card("metis-0012", owner="вы")])
for old in ("metis-pantheon", "zeus", "вы"):
    ren, _ = S.owner_renames(tasks_k, [agent("sid-k", "metis-pantheon-2")], {"sid-k": old}, DIRS)
    check(f"1. старое имя «{old}» — направление, роль или владелец, не сессия: owner не трогаем", ren == [], ren)
check("1. записи снимка без sessionId или имени не в счёт",
      S.session_rows([{"name": "x"}, {"sessionId": "s"}, {"sessionId": "s", "name": " "}, "мусор", agent("s", " y ")])
      == [("s", "y", "working")])

# --- 2. задача без хозяина --------------------------------------------------------------------------------------------
tasks2 = dict([card("metis-0020", owner="dev-ghost"), card("metis-0021", owner="dev-stopped"),
               card("metis-0022", owner="dev-live"), card("metis-0023", owner="dev-live2"),
               card("metis-0024", owner="metis-pantheon"), card("metis-0025", owner="вы"), card("metis-0026", owner="zeus"),
               card("metis-0027", "done", owner="dev-ghost"), card("metis-0028", "dropped", owner="dev-ghost"),
               card("metis-0029", owner="dev-tab"), card("metis-0030", owner="Иван Петров"),
               card("metis-0031", owner="dev-gone"), card("metis-0032", "waiting", owner="dev-ghost")])
ags = [agent("s1", "dev-stopped", "stopped"), agent("s2", "dev-live"), agent("s3", "dev-live2 (2)", "done"),
       agent("s4", "dev-tab", None), agent("s5", "dev-gone", "failed")]
orph = S.orphan_owners(tasks2, ags, DIRS)
check("2. сессии нет среди окон → без хозяина; остановленная (claude stop) → без хозяина",
      orph.get("metis-0020") == ("dev-ghost", "сессии нет среди окон")
      and orph.get("metis-0021") == ("dev-stopped", "сессия остановлена")
      and orph.get("metis-0032") == ("dev-ghost", "сессии нет среди окон"), orph)
check("2. живое окно, копия имени, вкладка без состояния, failed (поднимет дежурный) — хозяин есть",
      not {"metis-0022", "metis-0023", "metis-0029", "metis-0031"} & set(orph), orph)
check("2. владелец, роль, координатор направления, имя не сессии, закрытые задачи — не тревожат",
      not {"metis-0024", "metis-0025", "metis-0026", "metis-0027", "metis-0028", "metis-0030"} & set(orph), orph)
orph = S.orphan_owners(tasks2, ags, DIRS, stopped={"metis-pantheon", "dev-live"})
check("2. метка pantheon stop — без хозяина, и у координатора направления тоже",
      orph.get("metis-0024") == ("metis-pantheon", "сессию остановили (pantheon stop)")
      and orph.get("metis-0022") == ("dev-live", "сессию остановили (pantheon stop)"), orph)
check("2. кому передать: координатору направления; остановили координатора или направления нет — Зевсу",
      S.handover("dev-ghost", "metis-pantheon", DIRS) == "metis-pantheon"
      and S.handover("metis-pantheon", "metis-pantheon", DIRS) == "zeus" and S.handover("dev-x", "nope", DIRS) == "zeus")

# --- 3. doing без следов работы ---------------------------------------------------------------------------------------
repo = os.path.join(ROOT, "unit-repo")
write(os.path.join(repo, ".git", "refs", "heads", "metis-0041-work"), "abc\n")
write(os.path.join(repo, ".git", "refs", "remotes", "origin", "metis-0042-pushed"), "abc\n")
write(os.path.join(repo, ".git", "packed-refs"), "# pack-refs\n" + "0123456789abcdef0123 refs/heads/metis-0043-packed\n")
wt = os.path.join(repo, ".claude", "worktrees", "w1")
os.makedirs(wt)
write(os.path.join(repo, ".git", "worktrees", "w1", "HEAD"), "ref: refs/heads/metis-0044-wt\n")
write(os.path.join(repo, ".git", "worktrees", "w1", "gitdir"), os.path.join(wt, ".git") + "\n")
check("3. ветки: локальные, удалённые и упакованные", {"metis-0041-work", "origin/metis-0042-pushed", "metis-0043-packed"}
      <= S.branch_refs(repo), S.branch_refs(repo))
old, fresh = T.now_iso(T0 - 7 * H), T.now_iso(T0 - 5 * H)
tasks3 = dict([card(f"metis-00{i}", "doing", updated=old) for i in range(40, 46)]
              + [card("metis-0046", "doing", updated=fresh), card("metis-0047", "todo", updated=old),
                 card("metis-0048", "doing", updated=old, claimed_until=T.now_iso(T0 + H)),
                 card("metis-0049", "doing", updated=old, claimed_until=T.now_iso(T0 - H)),
                 card("site-0001", "doing", direction="example-site", updated=old),
                 card("metis-0050", "doing", kind="story", updated=old)])
stale = S.stale_doing(tasks3, {"metis-pantheon": [repo]}, {"metis-0045"}, T0, T.ts_of)
check("3. doing дольше 6 ч без ветки, worktree и PR → тревога; часы без правки",
      stale == {"metis-0040": 7, "metis-0049": 7}, stale)
check("3. порог — 6 ч: правили 5 ч назад — нет; 7 ч при пороге 8 — нет",
      "metis-0046" not in stale and S.stale_doing(tasks3, {"metis-pantheon": [repo]}, {"metis-0045"}, T0, T.ts_of, hours=8) == {})

# --- 5. время в --note и журнал из будущего ---------------------------------------------------------------------------
cases = {"23:45 — сделал": ("сделал", "23:45"), "2026-11-05 01:20: тесты зелёные": ("тесты зелёные", "2026-11-05 01:20"),
         "05.11 23:30 · ушёл": ("ушёл", "05.11 23:30"), "2026-11-05 — итог": ("итог", "2026-11-05"),
         "15:00 созвон с клиентом": ("15:00 созвон с клиентом", None), "23:45 —  ": ("23:45 —  ", None),
         "сделал к 23:45 — ок": ("сделал к 23:45 — ок", None), "12:30:15 | проба": ("проба", "12:30:15")}
got = {k: T.note_stamp(k) for k in cases}
check("5. время в начале --note снимается только с разделителем; содержание и пустой остаток — как есть", got == cases,
      {k: v for k, v in got.items() if v != cases[k]})
body = "\n## Журнал\n\n- 2026-10-23 10:00 — агент: создана\n- 2026-10-24 23:59 — агент: из будущего\n"
fut = dict([("metis-0060", ("", {"status": "doing"}, body)), ("metis-0061", ("", {"status": "done"}, body))])
t_ok = T.ts_of("2026-10-24T23:50")
check("5. строка журнала позже часов больше 10 мин — находка (открытые задачи), 9 мин — нет",
      [i for i, _ in T.journal_future(fut, T.ts_of("2026-10-24T23:40"))] == ["metis-0060"]
      and T.journal_future(fut, t_ok) == [], T.journal_future(fut, T.ts_of("2026-10-24T23:40")))

# --- сквозь CLI -------------------------------------------------------------------------------------------------------
tmp = os.path.join(ROOT, "e2e")
home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
os.makedirs(os.path.join(home, "directions", "metis-pantheon", "tasks"))
os.makedirs(view)
erepo = os.path.join(tmp, "agent-kit")
os.makedirs(os.path.join(erepo, ".git", "refs", "heads"))
SCHED = ('primary_host = "mac-a"\n\n[[job]]\nname = "board"\ncommand = "pantheon board"\nevery = "tick"\n\n'
         '[[job]]\nname = "view"\ncommand = "pantheon view --quiet"\nevery = "tick"\n\n'
         '[[job]]\nname = "commit"\ncommand = "pantheon commit"\nevery = "tick"\n')
write(os.path.join(home, "schedule.toml"), SCHED)
write(os.path.join(home, "directions.toml"), '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n')
write(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), '[merge_repos]\nmetis-pantheon = ["latark/agent-kit"]\n')
write(os.path.join(state, "domains.json"), json.dumps({"domains": {"metis-pantheon": [erepo]}}))
env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state, "PANTHEON_VIEW": view,
       "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "PANTHEON_FAKE_IDLE": "0",
       "PANTHEON_METRICS": "0", "TMPDIR": tmp}


def cli(args, t, **extra):
    return subprocess.run([PY311, "-I", RUN_PY] + args, env=dict(env, PANTHEON_NOW=str(t), **extra), capture_output=True,
                          text=True, timeout=300)


def new(title, t=T0, *extra):
    r = cli(["task", "new", "--direction", "metis-pantheon", "--title", title, "--text", "тело задачи", *extra], t)
    if r.returncode:
        raise SystemExit(f"task new: {r.stderr}")
    return r.stdout.split()[0], os.path.join(home, r.stdout.split()[1])


def head(p):
    return T.read(p)[0]


def snapshot(t, *ags):
    write(os.path.join(state, "agents.json"), json.dumps({"time": t, "agents": list(ags)}))


def orphan_alert(out):
    return [ln for ln in out.splitlines() if "задача без хозяина" in ln]


def once_marks(key):
    return glob.glob(os.path.join(state, "once", key + "-*"))


tA, pA = new("Сессия переименована", T0, "--status", "todo", "--owner", "dev-a")
tH, pH = new("Закрытая у той же сессии", T0, "--status", "done", "--owner", "dev-a")
tB, pB = new("Хозяина нет среди окон", T0, "--status", "todo", "--owner", "dev-ghost")
tS, pS = new("Хозяин остановлен", T0, "--status", "todo", "--owner", "dev-stop")
tC, pC = new("У координатора", T0, "--status", "todo", "--owner", "metis-pantheon")
tE, pE = new("doing без следов", T0, "--status", "doing", "--owner", "metis-pantheon")
tF, pF = new("doing с веткой", T0, "--status", "doing", "--owner", "metis-pantheon")
tG, pG = new("doing с открытым PR", T0, "--status", "doing", "--owner", "metis-pantheon")
write(os.path.join(erepo, ".git", "refs", "heads", f"{tF}-work"), "abc\n")
write(os.path.join(state, "autoclose-prs.json"), json.dumps({"fetched": T0, "merged": {}, "open": {}, "open_prs": {
    "latark/agent-kit": [{"number": 150, "head": "abc", "ids": [tG], "closes": [tG], "part": False, "core": False}]}}))

T1 = T0 + 60
snapshot(T1, agent("aaaa1111-0000", "dev-a"), agent("bbbb2222-0000", "dev-stop", "stopped"))
r = cli(["board"], T1)
mem = json.loads(read(os.path.join(state, "owner-sids.json")))
check("e2e 1. проход доски запомнил имена сессий по sessionId",
      r.returncode == 0 and {k: v["name"] for k, v in mem.items()} == {"aaaa1111-0000": "dev-a", "bbbb2222-0000": "dev-stop"},
      r.stdout + r.stderr + str(mem))
al = orphan_alert(r.stdout)
check("e2e 2. тревога «задача без хозяина»: причина и готовая команда передачи координатору направления",
      len(al) == 1 and f"owner dev-ghost — сессии нет среди окон: {tB}. Передать: pantheon task set {tB} owner=metis-pantheon"
      in al[0] and f"owner dev-stop — сессия остановлена: {tS}. Передать: pantheon task set {tS} owner=metis-pantheon" in al[0]
      and tA not in al[0] and tC not in al[0], r.stdout)
check("e2e 3. doing 1 мин — ещё не тревога", "board-doing-stale" not in r.stdout and "без ветки, worktree и PR" not in r.stdout,
      r.stdout)

T2 = T0 + 7 * H
snapshot(T2, agent("aaaa1111-0000", "dev-renamed"), agent("bbbb2222-0000", "dev-stop", "stopped"))
r = cli(["board"], T2)
check("e2e 1. сессию переименовали → owner открытой карточки за ней, строка в журнал с sessionId",
      head(pA).get("owner") == "dev-renamed" and "owner: сессию dev-a переименовали в dev-renamed (sessionId aaaa1111)" in read(pA)
      and f"хозяин · {tA}: dev-a → dev-renamed" in r.stdout, r.stdout + r.stderr + read(pA))
check("e2e 1. закрытая карточка той же сессии не тронута", head(pH).get("owner") == "dev-a" and "переименовали" not in read(pH))
check("e2e 1. время строки журнала — время прохода", f"{T.now_iso(T2)[:16].replace('T', ' ')} — плановый проход: owner" in read(pA),
      read(pA))
check("e2e 2. та же картина без хозяина — тревога не повторяется", orphan_alert(r.stdout) == [], r.stdout)
stale_ln = [ln for ln in r.stdout.splitlines() if "без ветки, worktree и PR" in ln]
check("e2e 3. doing 7 ч без ветки, worktree и PR → тревога с командой; с веткой и с открытым PR — нет",
      len(stale_ln) == 1 and f"{tE} (7 ч без правки" in stale_ln[0] and tF not in stale_ln[0] and tG not in stale_ln[0]
      and f"pantheon task set {tE} status=todo" in stale_ln[0] and tA not in stale_ln[0], r.stdout)

os.makedirs(os.path.join(state, "stopped"), exist_ok=True)
write(os.path.join(state, "stopped", "metis-pantheon"), "")
r = cli(["board"], T2 + 60)
al = orphan_alert(r.stdout)
check("e2e 2. координатора остановили (pantheon stop) → его задачи без хозяина, передать Зевсу",
      len(al) == 1 and f"owner metis-pantheon — сессию остановили (pantheon stop): {tC}, {tE}, {tF}, {tG}. Передать: "
      f"for id in {tC} {tE} {tF} {tG}; do pantheon task set $id owner=zeus; done" in al[0], r.stdout)
os.remove(os.path.join(state, "stopped", "metis-pantheon"))
for tid in (tB, tS, tC):  # команда из тревоги, буквально
    cli(["task", "set", tid, "owner=metis-pantheon"], T2 + 90)
r = cli(["board"], T2 + 120)
check("e2e 2. задачи передали командой из тревоги → тревога снята (метка «один раз» убрана)",
      orphan_alert(r.stdout) == [] and not once_marks("board-orphan-owner") and head(pB).get("owner") == "metis-pantheon",
      r.stdout + str(once_marks("board-orphan-owner")))
tX, pX = new("Хозяин ушёл, а снимок старый", T2 + 130, "--status", "todo", "--owner", "dev-x")
snapshot(T2 + 150 - 3600, agent("aaaa1111-0000", "dev-renamed"))
r = cli(["board"], T2 + 150)
check("e2e 2. снимок сессий старше 30 мин — о хозяевах молчим", orphan_alert(r.stdout) == [], r.stdout)
snapshot(T2 + 160, agent("aaaa1111-0000", "dev-renamed"))
r = cli(["board"], T2 + 160)
check("e2e 2. снимок свежий — тревога снова идёт", any(f"owner dev-x — сессии нет среди окон: {tX}" in ln
                                                     for ln in orphan_alert(r.stdout)), r.stdout)

# --- 4. правка карточки → view и доска сразу ---------------------------------------------------------------------------
dry = os.path.join(state, "dryrun.log")


def kicked(args, t, **extra):
    before = read(dry) if os.path.exists(dry) else ""
    r = cli(args, t, **extra)
    after = read(dry) if os.path.exists(dry) else ""
    return r, sorted(ln.split()[1] for ln in after[len(before):].splitlines())


T3 = T2 + 400
r, got = kicked(["task", "set", tE, "status=todo"], T3, PANTHEON_REFRESH="1")
check("e2e 4. task set меняет карточку → задачи расписания view и board запущены сразу (без commit)",
      r.returncode == 0 and got == ["board", "view"], r.stdout + r.stderr + str(got))
r, got = kicked(["task", "new", "--direction", "metis-pantheon", "--title", "Новая", "--text", "т"], T3 + 1, PANTHEON_REFRESH="1")
check("e2e 4. task new — тоже", r.returncode == 0 and got == ["board", "view"], r.stdout + r.stderr + str(got))
r, got = kicked(["task", "show", tE], T3 + 2, PANTHEON_REFRESH="1")
check("e2e 4. task show (чтение) — ничего не запускает", r.returncode == 0 and got == [], got)
r, got = kicked(["task", "set", "metis-9999", "status=todo"], T3 + 3, PANTHEON_REFRESH="1")
check("e2e 4. правка не прошла (нет задачи) — ничего не запускает", r.returncode != 0 and got == [], r.stderr + str(got))
r, got = kicked(["task", "set", tE, "status=todo"], T3 + 4)
check("e2e 4. проба на временной папке без PANTHEON_REFRESH=1 — не запускает (окно владельца не трогаем)",
      r.returncode == 0 and got == [], got)
write(os.path.join(state, "paused"), "")
r, got = kicked(["task", "set", tE, "status=doing"], T3 + 5, PANTHEON_REFRESH="1")
check("e2e 4. весь планировщик на паузе — не запускает", r.returncode == 0 and got == [], got)
os.remove(os.path.join(state, "paused"))
r, got = kicked(["task", "set", tE, "status=todo"], T3 + 6, PANTHEON_REFRESH="1", PANTHEON_HOST="mac-b")
check("e2e 4. не главный Mac — тоже запускает (view и board идут на всех Mac)", got == ["board", "view"], got)
write(os.path.join(home, "schedule.toml"), SCHED.replace('every = "tick"\n\n[[job]]\nname = "view"',
                                                         'every = "tick"\nenabled = false\n\n[[job]]\nname = "view"'))
r, got = kicked(["task", "set", tE, "status=doing"], T3 + 7, PANTHEON_REFRESH="1")
check("e2e 4. задача board выключена в расписании — запускается только view", got == ["view"], got)
write(os.path.join(home, "schedule.toml"), SCHED)

# --- 5. время журнала ставит код ---------------------------------------------------------------------------------------
r = cli(["task", "set", tA, "--note", "23:45 — сделал шаг"], T3 + 10)
log = [ln for ln in read(pA).splitlines() if "сделал шаг" in ln]
check("e2e 5. время в начале --note не записано, строка датирована часами pantheon, предупреждение в stderr",
      r.returncode == 0 and log == [f"- {T.now_iso(T3 + 10)[:16].replace('T', ' ')} — агент: сделал шаг"]
      and "время «23:45» в начале --note не записано" in r.stderr, r.stderr + str(log))
probe = f"""
import sys
sys.path.insert(0, {LIB!r})
import pantheon as p
print("тест:", int(p.card_now()))
p.real_store = lambda: True
print("настоящее:", int(p.card_now()))
sys.exit(p.main(["task", "set", {tA!r}, "--note", "пишу в настоящее хранилище"]))
"""
r = subprocess.run([PY311, "-I", "-c", probe], env=dict(env, PANTHEON_NOW=str(T0)), capture_output=True, text=True,
                   timeout=120)
real = time.time()
ln = [x for x in read(pA).splitlines() if "пишу в настоящее хранилище" in x]
check("e2e 5. PANTHEON_NOW датирует только временное хранилище; настоящее — часами системы",
      r.returncode == 0 and f"тест: {T0}" in r.stdout and ln
      and abs(int(r.stdout.split("настоящее:")[1].split()[0]) - real) < 120
      and ln[0].startswith(f"- {T.now_iso(real)[:10]} "), r.stdout + r.stderr + str(ln))
cli(["check", "--quiet"], T3 + 15)  # первый проход слежения за хвостами запоминает, что уже есть
with open(pB, "a", encoding="utf-8") as fh:
    fh.write(f"- {T.now_iso(T3 + 3 * H)[:16].replace('T', ' ')} — агент: дописал руками на глаз\n")
r = cli(["check", "--quiet"], T3 + 20)
al = [x for x in r.stdout.splitlines() if "строка журнала задачи позже часов системы" in x]
check("e2e 5. строка журнала позже часов системы — тревога хвоста «время» в pantheon check, с id и строкой",
      len(al) == 1 and f"{tB}: строка журнала позже часов системы — «- " in al[0] and "дописал руками на глаз" in al[0],
      r.stdout + r.stderr)
probe = f"""
import sys
sys.path.insert(0, {LIB!r})
import pantheon as p
class Broken:
    def owner_renames(self, *a):
        raise RuntimeError("проба")
    def __getattr__(self, name):
        raise RuntimeError("проба")
p.boardstatus_mod = lambda: Broken()
print("строк:", len(p.board_owner_sync(p.tasks_mod())))
"""
r = subprocess.run([PY311, "-I", "-c", probe], env=dict(env, PANTHEON_NOW=str(T3 + 30)), capture_output=True, text=True,
                   timeout=120)
check("сбой: сверка хозяев упала → тревога с причиной, проход доски не падает",
      r.returncode == 0 and "сверка хозяев задач упала (RuntimeError: проба)" in r.stdout and "строк: 0" in r.stdout,
      r.stdout + r.stderr)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
