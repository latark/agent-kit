#!/usr/bin/env python3
"""Статусы задач и пачек в шаг с работой (metis-0397, расширение «вся доска», lib/boardstatus.py): выдача исполнителю
(`pantheon task claim`, живая worktree на ветке с id задачи) → doing; открытый PR, который закрывает задачу, → review
(автозакрытие); пачка с задачей doing или review → doing («В работе»), все задачи done или dropped → done («Готово»);
задачу вернули в todo, а работа идёт — тревога, второй раз проход её не двигает; пачку на приёмке (review) и пачку
с вопросом владельцу проход не закрывает и вопрос не стирает; пачку, закрытую руками, снова не открывает.

Запуск: python3 -I plugins/pantheon/tests/test_board_status.py  (код выхода 0 — все прошли; разбор — на любом
python3, сквозные проверки CLI pantheon — на Python 3.11+)
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402 — CLI pantheon только на Python 3.11+

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="board-status-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(PLUGIN, "lib", "pantheon.py")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PLUGIN, "lib", name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S, A = load("boardstatus"), load("autoclose")
results = []
T0 = 1_792_800_000


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"))


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def task(tid, status, kind="task", parent=None, direction="metis-pantheon", body=""):
    return tid, ("", {"type": kind, "id": tid, "status": status, "parent": parent, "direction": direction}, body)


def worktree(root, name, branch):
    """Запись worktree, как её пишет git: <root>/.git/worktrees/<имя>/{HEAD,gitdir}, папка копии на месте."""
    wt = os.path.join(root, ".claude", "worktrees", name)
    os.makedirs(wt, exist_ok=True)
    d = os.path.join(root, ".git", "worktrees", name)
    write(os.path.join(d, "HEAD"), f"ref: refs/heads/{branch}\n")
    write(os.path.join(d, "gitdir"), os.path.join(wt, ".git") + "\n")
    return wt


# --- 1. пачка по составу ---------------------------------------------------------------------------------------------
def story(st, *kids):
    return dict([task("metis-0500", st, "story")] + [task(f"metis-05{i:02d}", k, parent="metis-0500")
                                                     for i, k in enumerate(kids, 1)])


check("1. пачка todo с одной задачей doing → doing («В работе»)", S.story_target("metis-0500", story("todo", "doing", "todo")) == "doing")
check("1. пачка todo с задачей на проверке (review) → doing", S.story_target("metis-0500", story("todo", "review", "done")) == "doing")
check("1. все задачи done или dropped → done («Готово»)", S.story_target("metis-0500", story("doing", "done", "dropped")) == "done")
check("1. готовая пачка, задачу вернули в работу → снова doing", S.story_target("metis-0500", story("done", "doing", "done")) == "doing")
check("1. смешанный состав без работы (todo и done) — как есть",
      S.story_target("metis-0500", story("todo", "todo", "done")) is None)
check("1. пачка без задач — как есть", S.story_target("metis-0500", story("todo")) is None)
check("1. пачка ждёт человека (waiting) или снята (dropped) — не трогаем",
      S.story_target("metis-0500", story("waiting", "doing")) is None
      and S.story_target("metis-0500", story("waiting", "done")) is None
      and S.story_target("metis-0500", story("dropped", "doing")) is None)
DOING_LINE = "- 2026-10-24 02:00 — плановый проход: пачка по составу: есть задача в работе или на проверке → doing"
check("1. уже в нужном статусе и отметка прохода в журнале — plan не пишет",
      S.plan(dict(story("doing", "doing"), **{"metis-0500": task("metis-0500", "doing", "story", body=DOING_LINE)[1]}),
             {}) == ([], {}))
mv, hold = S.plan(story("doing", "doing"), {})
check("1. пачка в doing не проходом, состав держит doing → одна отметка в журнале без сдвига (metis-0412)",
      [(m[0], m[1]) for m in mv] == [("metis-0500", {})] and S.last_story_move("- 24.10 — плановый проход: " + mv[0][2])
      == "doing" and hold == {}, (mv, hold))
check("1. пачка done или todo при задаче doing — отметки нет, а сдвиг; пачка doing без задачи в работе — ничего",
      S.plan(story("done", "doing"), {})[0][0][1] == {"status": "doing"}
      and S.plan(story("todo", "doing"), {})[0][0][1] == {"status": "doing"}
      and S.plan(story("doing", "todo", "done"), {}) == ([], {}))
check("1. задача другой пачки и пачка-заметка (type stage) состав не меняют",
      S.story_target("metis-0500", dict(story("todo", "todo"), **dict([task("metis-0599", "doing", parent="metis-0600")]))) is None)


def story_with(st, extra=None, body="", *kids):
    """Пачка с полями головы extra и журналом body."""
    out = story(st, *kids)
    pth, h, _ = out["metis-0500"]
    out["metis-0500"] = (pth, dict(h, **(extra or {})), body)
    return out


check("1. пачка на проверке (review), все задачи done → не закрываем: приёмка за человеком",
      S.story_target("metis-0500", story("review", "done", "done")) is None and S.plan(story("review", "done"), {})[0] == [])
for fld, val in (("question", "Принять итоги ночи?"), ("options", ["А — принять", "Б — вернуть"]), ("requested", "А")):
    for st in ("inbox", "todo", "doing", "review", "done"):
        for kid in ("doing", "done"):
            mv, hold = S.plan(story_with(st, {fld: val}, "", kid), {})
            if S.story_target("metis-0500", story(st, kid)) in (None, st):
                continue
            check(f"1. пачка {st} с открытым {fld}, задача {kid} → не двигаем, а тревожим",
                  not any(m[0] == "metis-0500" for m in mv) and "ждёт ответа владельца" in hold.get("metis-0500", ""),
                  (mv, hold))
moved_note = "- 2026-10-24 02:00 — плановый проход: пачка по составу: есть задача в работе или на проверке → doing"
mv, hold = S.plan(story_with("done", None, moved_note, "doing"), {})
check("1. пачку сдвинули проходом в doing, а закрыли руками (done) → не открываем заново, тревога",
      mv == [] and "вернули руками в done" in hold.get("metis-0500", ""), (mv, hold))
mv, hold = S.plan(story_with("done", None, "- 2026-10-24 02:00 — плановый проход: пачка по составу: все задачи "
                                           "закрыты → done", "doing"), {})
check("1. проход последним ставил done, а задачу вернули в работу → снова doing",
      [m[0] for m in mv] == ["metis-0500"] and mv[0][1] == {"status": "doing"} and hold == {}, (mv, hold))
mv, hold = S.plan(story_with("done", None, "в описании: пачка по составу: … → doing", "doing"), {})
check("1. похожий текст не в журнале прохода отметкой не считается", [m[0] for m in mv] == ["metis-0500"], (mv, hold))
mv, hold = S.plan(story_with("done", None, DOING_LINE + "\n- 2026-10-24 03:00 — плановый проход: пачка по составу: "
                                               "все задачи закрыты → done", "doing"), {})
check("1. журнал из двух сдвигов (→ doing, затем → done), задача снова в работе → doing: важна последняя отметка",
      [(m[0], m[1]) for m in mv] == [("metis-0500", {"status": "doing"})] and hold == {}, (mv, hold))
check("1. пачка doing с вопросом владельцу — отметки нет (вопрос проход не трогает)",
      S.plan(story_with("doing", {"question": "Принять?"}, "", "doing"), {}) == ([], {}))

# --- 2. worktree на ветке с id задачи → doing; вернули в todo — тревога ----------------------------------------------
repo = os.path.join(ROOT, "u", "agent-kit")
os.makedirs(os.path.join(repo, ".git"))
other = os.path.join(ROOT, "u", "site")
os.makedirs(os.path.join(other, ".git"))
doms = {"metis-pantheon": [repo, os.path.join(ROOT, "u", "нет-такой")], "example-site": [other]}
worktree(repo, "agent-1", "metis-0510-board-sync")
worktree(other, "agent-2", "metis-0511-fix")         # репозиторий чужого направления
gone = worktree(repo, "agent-3", "metis-0512-old")
shutil.rmtree(gone)                                   # запись есть, папки копии нет — не живая
write(os.path.join(repo, ".git", "worktrees", "agent-4", "HEAD"), "0123456789abcdef0123456789abcdef01234567\n")
write(os.path.join(repo, ".git", "worktrees", "agent-4", "gitdir"), os.path.join(repo, ".claude", "worktrees", "agent-4", ".git"))
os.makedirs(os.path.join(repo, ".claude", "worktrees", "agent-4"))  # отделённый HEAD — не ветка
tasks = dict([task("metis-0510", "todo"), task("metis-0511", "todo"), task("metis-0512", "todo"),
              task("metis-0513", "todo"), task("metis-0500", "todo", "story"),
              task("metis-0520", "todo", parent="metis-0500"), task("metis-0510x", "todo")])
tasks["metis-0510"][1]["parent"] = "metis-0500"
moves, stale = S.plan(tasks, doms)
check("2. живая worktree на ветке metis-0510-… в репозитории направления → задача doing, строка в журнал",
      ("metis-0510", {"status": "doing"}, "worktree на ветке metis-0510-board-sync → doing") in moves, moves)
check("2. та же задача в пачке → пачка doing в том же проходе",
      ("metis-0500", {"status": "doing"}, "пачка по составу: есть задача в работе или на проверке → doing") in moves, moves)
check("2. копия без папки, отделённый HEAD, задача без следа — не трогаем",
      not any(m[0] in ("metis-0512", "metis-0513") for m in moves) and "metis-0512" not in stale, (moves, stale))
check("2. worktree в репозитории чужого направления — не двигаем, тревога", "metis-0511" not in [m[0] for m in moves]
      and stale.get("metis-0511") == "worktree на ветке metis-0511-fix", (moves, stale))
back = dict(tasks)
back["metis-0510"] = ("", dict(tasks["metis-0510"][1]), "## Журнал\n- 24.10 — плановый проход: worktree на ветке metis-0510-board-sync → doing\n")
moves2, stale2 = S.plan(back, doms)
check("2. задачу уже двигали этой веткой, а её вернули в todo → второй раз не двигаем, тревога",
      "metis-0510" not in [m[0] for m in moves2] and stale2.get("metis-0510") == "worktree на ветке metis-0510-board-sync",
      (moves2, stale2))
check("2. doing, review, done при живой worktree — не трогаем",
      all(S.plan(dict([task("metis-0510", st)]), doms) == ([], {}) for st in ("doing", "review", "done", "waiting")))
check("2. отпечаток: HEAD записей worktree по корням направлений",
      sorted(os.path.basename(os.path.dirname(p)) for p in S.wt_heads(repo)) == ["agent-1", "agent-3", "agent-4"])

# --- 3. открытый PR → review (автозакрытие), вернули в todo — тревога -------------------------------------------------
check("3. строка журнала review у автозакрытия и у прохода доски — одна и та же", A.REVIEW_MARK == S.REVIEW_MARK)
mark = S.review_note("latark/agent-kit", 130)
moves3, stale3 = S.plan(dict([task("metis-0530", "todo", body="- плановый проход: " + mark),
                              task("metis-0531", "todo")]),
                        {}, {"metis-0530": [("latark/agent-kit", 130)], "metis-0531": [("latark/agent-kit", 131)]})
check("3. по PR уже ставили review, а задачу вернули в todo → тревога; PR ещё не разобран автозакрытием — тишина",
      stale3 == {"metis-0530": "открытый PR latark/agent-kit#130"} and moves3 == [], (moves3, stale3))

# --- 4. сквозь CLI: claim, автозакрытие (review), проход доски (doing, пачка, тревога) ---------------------------------
tmp = os.path.join(ROOT, "e2e")
home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
os.makedirs(os.path.join(home, "directions", "metis-pantheon", "tasks"))
os.makedirs(os.path.join(home, "directions", "example-site", "tasks"))
os.makedirs(view)
erepo = os.path.join(tmp, "agent-kit")
os.makedirs(os.path.join(erepo, ".git"))
write(os.path.join(home, "schedule.toml"),
      'primary_host = "mac-a"\n\n[[job]]\nname = "board"\ncommand = "pantheon board"\nevery = "tick"\n')
write(os.path.join(home, "directions.toml"), '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n\n'
      '[[direction]]\nname = "example-site"\nproject = "Сайт"\n')
write(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), '[merge_repos]\nmetis-pantheon = ["latark/agent-kit"]\n')
write(os.path.join(state, "domains.json"), json.dumps({"domains": {"metis-pantheon": [erepo]}}))
env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state, "PANTHEON_VIEW": view,
       "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "PANTHEON_FAKE_IDLE": "0",
       "PANTHEON_METRICS": "0", "TMPDIR": tmp}


def cli(args, t=T0):
    return subprocess.run([PY311, "-I", CLI] + args, env=dict(env, PANTHEON_NOW=str(t)), capture_output=True, text=True,
                          timeout=300)


def new(title, *extra, direction="metis-pantheon"):
    status = [] if "--status" in extra else ["--status", "todo"]  # --status одиночный: у вызовов свой
    r = cli(["task", "new", "--direction", direction, "--title", title, "--text", "тело задачи", *status, *extra])
    if r.returncode:
        raise SystemExit(f"task new: {r.stderr}")
    return r.stdout.split()[0], os.path.join(home, r.stdout.split()[1])


def head(p):
    return {ln.split(":", 1)[0]: ln.split(":", 1)[1].strip() for ln in read(p).split("---")[1].splitlines() if ":" in ln}


sid, sp = new("Пачка", "--type", "story")
t1, p1 = new("Через claim", "--parent", sid, "--mode", "single")
t2, p2 = new("Через worktree", "--parent", sid, "--mode", "single")
t3, p3 = new("Через PR", "--mode", "single")
s2, sp2 = new("Пачка готова", "--type", "story")
t4, p4 = new("Последняя задача", "--parent", s2, "--mode", "single", "--status", "done")
t5, p5 = new("PR частью", "--mode", "single")
t6, p6 = new("Чужое направление", "--mode", "single", direction="example-site")
s3, sp3 = new("Пачка на приёмке с вопросом", "--type", "story")
t7, p7 = new("Готовая задача приёмки", "--parent", s3, "--mode", "single", "--status", "done")
s4, sp4 = new("Пачка в очереди с вопросом", "--type", "story")
t8, p8 = new("Готовая задача очереди", "--parent", s4, "--mode", "single", "--status", "done")
s5, sp5 = new("Пачка в работе руками", "--type", "story", "--status", "doing")  # doing не проходом (metis-0412)
t9, p9 = new("Задача пачки в работе", "--parent", s5, "--mode", "single", "--status", "doing")
ASK = ('question: "Принять итоги ночи?"\noptions: ["А — принять итоги, все проверки зелёные", '
       '"Б — вернуть на доработку, нужен ещё круг"]\nrecommend: "А — проверки зелёные"\n')
for sp_, st_ in ((sp3, "review"), (sp4, "todo")):
    txt = read(sp_).replace("status: todo\n", f"status: {st_}\n" + ASK, 1)
    write(sp_, txt)
r = cli(["task", "claim", t1, "--by", "dev-opus"])
check("4. выдача исполнителю (pantheon task claim) → doing", r.returncode == 0 and head(p1).get("status") == "doing",
      r.stdout + r.stderr)
write(os.path.join(state, "autoclose-prs.json"), json.dumps({"fetched": T0, "merged": {}, "open": {}, "open_prs": {
    "latark/agent-kit": [{"number": 140, "head": "abcdef1", "ids": [t3], "closes": [t3], "part": False, "core": False},
                         {"number": 141, "head": "abcdef2", "ids": [t5], "closes": [t5], "part": True, "core": False},
                         {"number": 142, "head": "abcdef3", "ids": [t6], "closes": [t6], "part": False, "core": False}]}}))
r = cli(["tick"], T0 + 60)
check("4. открытый PR, который закрывает задачу, → review (тик, автозакрытие), строка в журнал",
      head(p3).get("status") == "review" and S.review_note("latark/agent-kit", 140) in read(p3), r.stdout + r.stderr + read(p3))
check("4. PR «часть» и PR из репозитория чужого направления review не ставят",
      head(p5).get("status") == "todo" and head(p6).get("status") == "todo", (head(p5), head(p6)))
worktree(erepo, "agent-e2e", f"{t2}-work")
r = r_first = cli(["board"], T0 + 120)
check("4. проход доски: worktree на ветке задачи → doing, строка в журнал",
      head(p2).get("status") == "doing" and f"worktree на ветке {t2}-work → doing" in read(p2), r.stdout + r.stderr)
check("4. пачка с задачей doing → doing («В работе»)", head(sp).get("status") == "doing", r.stdout + r.stderr)
check("4. пачка, где все задачи done, → done («Готово»)", head(sp2).get("status") == "done", r.stdout + r.stderr)
check("4. проход печатает, что сдвинул", f"статус · {t2}: todo → doing" in r.stdout and f"статус · {sid}: todo → doing" in r.stdout,
      r.stdout)
for sp_, st_ in ((sp3, "review"), (sp4, "todo")):
    hd = head(sp_)
    check(f"4. пачка {st_} с вопросом владельцу, все задачи done → статус, question и options на месте",
          hd.get("status") == st_ and "Принять итоги ночи?" in hd.get("question", "")
          and "А — принять итоги" in hd.get("options", ""), read(sp_))
check("4. … и тревога «статус пачки не поставлен» с id пачки", "статус пачки по составу не поставлен" in r.stdout
      and s4 in r.stdout and "ждёт ответа владельца" in r.stdout, r.stdout)
hand = []
for rnd in range(2):  # пачку закрыли руками — проход не открывает её снова
    cli(["task", "set", sid, "status=done"], T0 + 130 + rnd * 20)
    rr = cli(["board"], T0 + 140 + rnd * 20)
    hand.append((head(sp).get("status"), rr.stdout))
check("4. пачку, которую проход ставил в doing, закрыли руками — два прохода подряд статус done",
      [h for h, _ in hand] == ["done", "done"] and f"вернули руками в done" in hand[0][1], hand)
check("4. пачка в doing не проходом → отметка в её журнале без сдвига, проход печатает её",
      head(sp5).get("status") == "doing" and S.last_story_move(read(sp5)) == "doing"
      and f"статус · {s5}: doing, отметка в журнале" in r_first.stdout, (read(sp5), r_first.stdout))
cli(["task", "set", s5, "status=done"], T0 + 172)
rr = cli(["board"], T0 + 174)
check("4. её закрыли руками → проход не открывает, тревога «вернули руками» (metis-0412)",
      head(sp5).get("status") == "done" and f"{s5} (пачку вернули руками в done" in rr.stdout, (read(sp5), rr.stdout))
write(sp, read(sp).replace("status: done\n", 'status: done\nquestion: "Закрыть пачку насовсем?"\n', 1))
rr = cli(["board"], T0 + 176)
check("4. у той же пачки сменилась причина (ручной статус → вопрос владельцу) → тревога звучит заново",
      f"{sid} (пачка ждёт ответа владельца (question)" in rr.stdout and head(sp).get("status") == "done", rr.stdout)
rr = cli(["board"], T0 + 178)
check("4. … повтор той же причины молчит", "статус пачки по составу не поставлен" not in rr.stdout, rr.stdout)
cli(["task", "set", t2, "status=todo"], T0 + 180)
r = cli(["board"], T0 + 240)
check("4. задачу вернули в todo при живой worktree → проход не двигает, тревога «в очереди, а работа идёт»",
      head(p2).get("status") == "todo" and f"{t2}" in r.stdout and "в todo, а работа по ним идёт" in r.stdout,
      r.stdout + r.stderr)
r = cli(["board"], T0 + 300)
check("4. повтор той же тревоги молчит", "в todo, а работа по ним идёт" not in r.stdout, r.stdout)
cli(["task", "set", t3, "status=todo"], T0 + 320)
cache = json.load(open(os.path.join(state, "autoclose-prs.json")))
write(os.path.join(state, "autoclose-prs.json"), json.dumps(dict(cache, fetched=T0 + 330)))
cli(["tick"], T0 + 360)
check("4. задачу с review по PR вернули в todo → новый проход автозакрытия второй раз не ставит review",
      head(p3).get("status") == "todo", read(p3))
r = cli(["board"], T0 + 400)
check("4. … а проход доски тревожит: открытый PR при задаче в todo",
      f"{t3} (открытый PR latark/agent-kit#140)" in r.stdout and head(p3).get("status") == "todo", r.stdout)
for x in (t2, t3):
    cli(["task", "claim", x, "--by", "dev-opus"], T0 + 420)
r = cli(["board"], T0 + 440)
quiet = "в todo, а работа по ним идёт" not in r.stdout
for x in (t2, t3):
    cli(["task", "set", x, "status=todo"], T0 + 460)
r = cli(["board"], T0 + 480)
check("4. работа взята — тревога снята; снова в todo — та же тревога звучит заново",
      quiet and "в todo, а работа по ним идёт" in r.stdout, r.stdout)

write(os.path.join(state, "autoclose-prs.json"), json.dumps({"fetched": T0 + 490, "merged": {}, "open": {}, "open_prs": {
    "latark/agent-kit": [{"number": 143, "head": "abcdef4", "ids": [], "closes": [["x"], 5, None], "part": False},
                         {"number": 144, "head": "abcdef5", "ids": [], "closes": "metis-0001", "part": False}]}}))
r = cli(["tick"], T0 + 492)
rb = cli(["board"], T0 + 494)
check("4. кривые closes в кэше (список в списке, число, строка вместо списка) — ни тик, ни проход доски не падают",
      r.returncode == 0 and "Traceback" not in r.stdout + r.stderr and rb.returncode == 0
      and "сверка статусов упала" not in rb.stdout and "autoclose" not in "".join(ln for ln in r.stdout.splitlines()
                                                                                 if "упал" in ln),
      r.stdout + r.stderr + rb.stdout + rb.stderr)
ac = json.load(open(os.path.join(state, "autoclose.json"), encoding="utf-8")) if os.path.exists(
    os.path.join(state, "autoclose.json")) else {}
check("4. autoclose с кривыми closes доходит до конца прохода (seen = fetched кэша)", ac.get("seen") == T0 + 490, repr(ac))

# --- 5. задачу правят между чтением и записью: проход не перетирает чужую правку ---------------------------------------
cli(["task", "claim", t2, "--by", "dev-opus"], T0 + 500)
probe = f"""
import os, sys
sys.path.insert(0, {os.path.join(PLUGIN, "lib")!r})
import pantheon as p
T = p.tasks_mod()
class Stale:
    def __getattr__(self, k):
        return getattr(T, k)
    def load_tasks(self, *a):
        out = T.load_tasks(*a)
        pth, h, body = out[{t2!r}]
        out[{t2!r}] = (pth, dict(h, status="todo"), body.replace("worktree на ветке", "-"))
        return out
print("\\n".join(p.board_status_sync(Stale())))
"""
r = subprocess.run([PY311, "-I", "-c", probe], env=dict(env, PANTHEON_NOW=str(T0 + 520)), capture_output=True, text=True,
                   timeout=120)
check("5. статус сменился после чтения прохода → задача не сдвинута, строка «не сдвинут»",
      f"статус · {t2}: не сдвинут" in r.stdout and head(p2).get("status") == "doing", r.stdout + r.stderr)
probe = f"""
import sys
sys.path.insert(0, {os.path.join(PLUGIN, "lib")!r})
import pantheon as p
T = p.tasks_mod()
class Late:  # вопрос пачке поставили после плана прохода: план его не видел, файл — с вопросом
    def __getattr__(self, k):
        return getattr(T, k)
    def load_tasks(self, *a):
        out = T.load_tasks(*a)
        pth, h, body = out[{s4!r}]
        out[{s4!r}] = (pth, dict(h, question=None, options=None, requested=None), body)
        return out
print("\\n".join(p.board_status_sync(Late())))
"""
r = subprocess.run([PY311, "-I", "-c", probe], env=dict(env, PANTHEON_NOW=str(T0 + 530)), capture_output=True, text=True,
                   timeout=120)
hd = head(sp4)
check("5. вопрос пачке поставили между планом и записью → пачка не сдвинута, вопрос на месте (metis-0412)",
      f"статус · {s4}: не сдвинут ({s4}: ждёт ответа владельца" in r.stdout and hd.get("status") == "todo"
      and "Принять итоги ночи?" in hd.get("question", ""), r.stdout + r.stderr + read(sp4))
probe = f"""
import sys
sys.path.insert(0, {os.path.join(PLUGIN, "lib")!r})
import pantheon as p
class Broken:
    def plan(self, *a):
        raise RuntimeError("проба")
p.boardstatus_mod = lambda: Broken()
print("строк:", len(p.board_status_sync(p.tasks_mod())))
"""
r = subprocess.run([PY311, "-I", "-c", probe], env=dict(env, PANTHEON_NOW=str(T0 + 540)), capture_output=True, text=True,
                   timeout=120)
check("5. сверка статусов упала → тревога с причиной, проход доски не падает",
      r.returncode == 0 and "сверка статусов упала (RuntimeError: проба)" in r.stdout and "строк: 0" in r.stdout,
      r.stdout + r.stderr)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
