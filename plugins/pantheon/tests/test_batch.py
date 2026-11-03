#!/usr/bin/env python3
"""Пачка — одна ветка и один PR (metis-0757): pantheon batch start|pr.

Запуск: python3 -I plugins/pantheon/tests/test_batch.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="batch-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def card(path, head, body=""):
    lines = ["---"] + [f"{k}: {v}" for k, v in head.items()] + ["---", "", f"# {head['title']}", "", body]
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


tmp = os.path.realpath(tempfile.mkdtemp(prefix="batch-test-"))
home, state, view, bindir = (os.path.join(tmp, x) for x in ("pantheon", "state", "view", "bin"))
tdir = os.path.join(home, "directions", "metis-pantheon", "tasks")
os.makedirs(tdir)
os.makedirs(view)
os.makedirs(bindir)
open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(
    '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n')
base = {"project": "Пантеон", "direction": "metis-pantheon", "owner": "metis-pantheon", "created": "2026-11-03",
        "updated": "2026-11-03T12:00:00", "schema_version": 1}
card(os.path.join(tdir, "metis-0900.md"), {"type": "story", "id": "metis-0900", "title": '"П9 Пачка"',
                                           "status": "doing", **base}, "## Готово, когда\n\n- [ ] пачка слита, тесты зелёные")
STUB = "(впишите проверяемые пункты: что должно работать и как это проверить)"
card(os.path.join(tdir, "metis-0909.md"), {"type": "story", "id": "metis-0909", "title": '"Пачка-заглушка"',
                                           "status": "doing", **base}, "## Готово, когда\n\n- [ ]  " + STUB.replace(" ", "  ", 1))
card(os.path.join(tdir, "metis-0901.md"), {"type": "task", "id": "metis-0901", "title": '"Первая"', "status": "doing",
                                           "parent": "metis-0900", **base})
card(os.path.join(tdir, "metis-0902.md"), {"type": "task", "id": "metis-0902", "title": '"Вторая"', "status": "todo",
                                           "parent": "metis-0900", "depends_on": "[metis-0901]", **base})
card(os.path.join(tdir, "metis-0903.md"), {"type": "task", "id": "metis-0903", "title": '"Готовая часть работы"', "status": "done",
                                           "parent": "metis-0900", **base})
card(os.path.join(tdir, "metis-0904.md"), {"type": "task", "id": "metis-0904", "title": '"Чужая"', "status": "todo",
                                           **base})

# репозиторий с origin: голый origin, копия с main
origin = os.path.join(tmp, "origin.git")
repo = os.path.join(tmp, "repo")
subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
genv = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
os.environ.update(genv)
open(os.path.join(repo, "a.txt"), "w").write("a\n")
git(repo, "add", "a.txt")
git(repo, "commit", "-q", "-m", "init")
git(repo, "remote", "add", "origin", origin)
git(repo, "push", "-q", "origin", "main")
main_sha = git(repo, "rev-parse", "HEAD")

# поддельный gh: каждый вызов — строка аргументов через NUL в gh.log; `pr list` отдаёт номер из open_pr (если есть)
ghlog = os.path.join(tmp, "gh.log")
openpr = os.path.join(tmp, "open_pr")
open(os.path.join(bindir, "gh"), "w").write(
    "#!/bin/sh\n"
    f"for a in \"$@\"; do printf '%s\\0' \"$a\"; done >> '{ghlog}'; printf '\\001' >> '{ghlog}'\n"
    f"if [ \"$1 $2\" = 'pr list' ]; then cat '{openpr}' 2>/dev/null; exit 0; fi\n"
    "echo https://github.com/x/y/pull/9\n")
os.chmod(os.path.join(bindir, "gh"), 0o755)


def gh_calls():
    if not os.path.exists(ghlog):
        return []
    return [ln.split("\0")[:-1] for ln in open(ghlog).read().split("\x01") if ln]


env = {"PATH": bindir + os.pathsep + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
       "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
       "PANTHEON_FAKE_IDLE": "0", "TMPDIR": _ROOT, "GH_REPO": "evil/repo", **genv}


def cli(cwd, *a):
    return subprocess.run([PY311, "-I", RUN_PY, *a], cwd=cwd, env=env, capture_output=True, text=True)


# разбор
for bad in ([], ["start"], ["go", "metis-0900"], ["start", "../x"], ["start", "metis-0900", "x"],
            ["start", "metis-0900", "--dry-run"]):
    r = cli(repo, "batch", *bad)
    check(f"разбор: batch {' '.join(bad) or '(пусто)'} → код 2", r.returncode == 2, r.stderr[-200:])
r = cli(repo, "batch", "start", "metis-0901")
check("start на задаче, не пачке → код 1, «нет»", r.returncode == 1 and "нет" in r.stderr, r.stderr)
for sub in (["start"], ["pr", "--dry-run"]):  # metis-0766: story без проверяемых пунктов — отказ с номером, ветки нет
    r = cli(repo, "batch", sub[0], "metis-0909", *sub[1:])
    check(f"{sub[0]} у story только с заглушкой → код 1, «нет критериев» с номером story, gh не зван",
          r.returncode == 1 and "нет критериев" in r.stderr and "metis-0909" in r.stderr and not gh_calls(), r.stderr)
check("start у story-заглушки ветку не создал",
      subprocess.run(["git", "rev-parse", "--verify", "--quiet", "refs/heads/batch/metis-0909"], cwd=repo).returncode != 0)

# start
r = cli(repo, "batch", "start", "metis-0900")
wt = os.path.join(repo, ".claude", "worktrees", "batch-metis-0900")
check("start: код 0, копия создана", r.returncode == 0 and os.path.isdir(wt), r.stdout + r.stderr)
check("start: ветка batch/metis-0900 от origin/main",
      os.path.isdir(wt) and git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "batch/metis-0900"
      and git(wt, "rev-parse", "HEAD") == main_sha)
r = cli(repo, "batch", "start", "metis-0900")
check("start повторно → код 1, «уже есть»", r.returncode == 1 and "уже есть" in r.stderr, r.stderr)
r = cli(wt, "batch", "start", "metis-0900")
check("start из копии пачки — тот же репозиторий, «уже есть»", r.returncode == 1 and "уже есть" in r.stderr, r.stderr)

# pr
r = cli(repo, "batch", "pr", "metis-0900")
check("pr не из ветки пачки → код 2, gh не зван", r.returncode == 2 and not gh_calls(), r.stderr)
r = cli(wt, "batch", "pr", "metis-0900", "--dry-run")
check("pr --dry-run без коммитов задач: Closes нет, все открытые — «не вошли», gh не зван",
      r.returncode == 0 and "Closes" not in r.stdout and "остаются открытыми: metis-0901; metis-0902" in r.stdout
      and not gh_calls(), r.stdout + r.stderr)

# работа 0901 — коммитом в ветке пачки, 0902 — влитой веткой задачи
open(os.path.join(wt, "b.txt"), "w").write("b\n")
git(wt, "add", "b.txt")
git(wt, "commit", "-q", "-m", "metis-0901: первая")
r = cli(wt, "batch", "pr", "metis-0900", "--dry-run")
out = r.stdout
check("коммит с номером → Closes только ему, вторая — «не вошли»",
      "Closes metis-0901\n" in out and "остаются открытыми: metis-0902" in out and "Closes metis-0901, metis-0902" not in out, out)
check("тело: задачи пачки по порядку, закрытая без Closes, чужой нет",
      out.find("metis-0901") < out.find("metis-0902") and "metis-0903" in out and "metis-0904" not in out
      and "Closes metis-0900" not in out and "metis-0903" not in out.split("Closes", 1)[1], out)

sys.path.insert(0, LIB)
import autoclose as AC  # noqa: E402  — тот же разбор, что у планового прохода
check("autoclose: тело с «не вошли» закрывает только metis-0901 (и id пачки из ветки — не задача)",
      AC.closing_ids("batch/metis-0900", out.split("\n\n", 1)[1]) == ["metis-0900", "metis-0901"],
      str(AC.closing_ids("batch/metis-0900", out)))

git(wt, "switch", "-q", "-c", "metis-0902-vtoraya")
open(os.path.join(wt, "c.txt"), "w").write("c\n")
git(wt, "add", "c.txt")
git(wt, "commit", "-q", "-m", "вторая задача")
git(wt, "switch", "-q", "batch/metis-0900")
git(wt, "merge", "-q", "--no-ff", "--no-edit", "metis-0902-vtoraya")
r = cli(wt, "batch", "pr", "metis-0900")
calls = gh_calls()
create = [c for c in calls if c[:2] == ["pr", "create"]]
check("pr: сначала gh pr list по ветке, затем create --base main --head batch/metis-0900",
      r.returncode == 0 and len(calls) == 2 and calls[0][:4] == ["pr", "list", "--head", "batch/metis-0900"]
      and len(create) == 1 and create[0][2:7] == ["--base", "main", "--head", "batch/metis-0900", "--title"], str(calls))
check("влитая ветка metis-0902-… засчитана: Closes на обе",
      bool(create) and create[0][7].startswith("Пачка metis-0900") and create[0][8] == "--body"
      and "Closes metis-0901, metis-0902" in create[0][9] and "не вошли" not in create[0][9].lower(), str(create))
check("pr: ссылка gh в выводе", "pull/9" in r.stdout, r.stdout)

# PR уже открыт — повтор обновляет его тело, второго не создаёт
os.remove(ghlog)
open(openpr, "w").write("17\n")
r = cli(wt, "batch", "pr", "metis-0900")
calls = gh_calls()
check("повтор при открытом PR → gh pr edit 17 с новым телом, create нет",
      r.returncode == 0 and any(c[:3] == ["pr", "edit", "17"] and "Closes metis-0901, metis-0902" in c[-1] for c in calls)
      and not any(c[:2] == ["pr", "create"] for c in calls), str(calls))

# коммит «часть <id>» — задача сделана не вся: Closes ей нет, в теле нет слова «часть» (autoclose снял бы весь PR)
open(os.path.join(wt, "d.txt"), "w").write("d\n")
git(wt, "add", "d.txt")
git(wt, "commit", "-q", "-m", "доработка, часть metis-0902")
r = cli(wt, "batch", "pr", "metis-0900", "--dry-run")
body = r.stdout.split("\n\n", 1)[1] if "\n\n" in r.stdout else ""
check("«часть metis-0902» в коммите → Closes только metis-0901, 0902 — «не целиком»",
      "Closes metis-0901\n" in body and "остаются открытыми: metis-0902" in body and "· частично ·" in body, body)
check("тело без слова «часть» (и из заголовка задачи): autoclose.is_part — нет",
      not AC.is_part(body) and "ч. работы" in body, body)
check("autoclose по телу закрывает только metis-0901",
      AC.closing_ids("batch/metis-0900", body) == ["metis-0900", "metis-0901"], str(AC.closing_ids("batch/metis-0900", body)))

# metis-0767: Closes только задачам с отмеченными «Готово, когда»; [ ] и заглушка — «не целиком», в stderr «неотмечено N»
HINT = "(впишите проверяемые пункты: что должно работать и как это проверить)"
for n, dw in (("0905", "- [x] сделано\n- [ ] ещё не сделано\n- [ ] и это"), ("0906", "- [x] раз\n- [x] два"), ("0907", "- [ ] " + HINT)):
    card(os.path.join(tdir, f"metis-{n}.md"), {"type": "task", "id": f"metis-{n}", "title": f'"Карточка {n}"', "status": "doing",
                                               "parent": "metis-0900", **base}, "## Готово, когда\n\n" + dw + "\n")
    open(os.path.join(wt, f"{n}.txt"), "w").write(n)
    git(wt, "add", f"{n}.txt")
    git(wt, "commit", "-q", "-m", f"metis-{n}: работа")
r = cli(wt, "batch", "pr", "metis-0900", "--dry-run")
body = r.stdout.split("\n\n", 1)[1]
check("«Готово, когда» с [ ] → не в Closes, в строке «Не целиком, остаются открытыми»",
      "Closes metis-0901, metis-0906\n" in body and "metis-0905" not in body.split("Closes", 1)[1]
      and "Не целиком, остаются открытыми: metis-0902; metis-0905; metis-0907" in body, body)
check("все [x] → в Closes", "metis-0906" in body.split("Closes", 1)[1], body)
check("заглушка DONE_WHEN_HINT → не в Closes", "metis-0907" not in body.split("Closes", 1)[1], body)
check("stderr: «metis-0905: неотмечено 2 — отметь пункты в карточке или оставь открытой»",
      "metis-0905: неотмечено 2 — отметь пункты в карточке или оставь открытой" in r.stderr and "metis-0907: неотмечено 1" in r.stderr
      and "metis-0906" not in r.stderr, r.stderr)

# GH_REPO не доходит до gh
open(os.path.join(bindir, "gh"), "w").write(f"#!/bin/sh\necho \"[$GH_REPO]\" >> '{ghlog}.env'\n")
cli(wt, "batch", "pr", "metis-0900")
check("pr: GH_REPO из окружения до gh не доходит",
      os.path.exists(ghlog + ".env") and set(open(ghlog + ".env").read().split()) == {"[]"})

r = subprocess.run([PY311, "-I", RUN_PY, "help"], env=env, capture_output=True, text=True)
check("справка называет batch start|pr", "batch start|pr" in r.stdout)

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
