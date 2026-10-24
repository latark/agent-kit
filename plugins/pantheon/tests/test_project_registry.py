#!/usr/bin/env python3
"""Поле project — только имя проекта из directions.toml (metis-0323): task new берёт проект направления и не
принимает чужое имя; pantheon check — ошибка на карточку с чужим project; pantheon task migrate-project — сухой
прогон ничего не пишет, --write переносит и пишет журнал, повтор пуст.

Запуск: python3 -I plugins/pantheon/tests/test_project_registry.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="preg-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


DIRS = '''[[direction]]
name = "metis-pantheon"
project = "Пантеон"
folders = ["~/projects/agent-kit", "~/.claude"]

[[direction]]
name = "themis-sources"
project = "legal-watch и expert-corpus"
folders = ["~/projects/legal-watch", "~/projects/expert-corpus"]

[[direction]]
name = "plain-dir"
folders = ["~/projects/plain"]
'''


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="preg-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("metis-pantheon", "themis-sources", "plain-dir", "ghost"):
        os.makedirs(os.path.join(home, "directions", d, "tasks"))
    os.makedirs(os.path.join(home, "inbox", "tasks"))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(DIRS)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0"}
    return tmp, home, env


def run(env, *args, t=T0):
    e = dict(env, PANTHEON_NOW=str(t))
    return subprocess.run([PY311, "-I", CLI, *args], env=e, capture_output=True, text=True, timeout=90)


def new(env, direction, *args):
    r = run(env, "task", "new", "--direction", direction, "--title", "Задача", *args)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()[0]


def proj(home, tid):
    return T.load_tasks(home, T.WORK_TYPES)[tid][1]["project"]


def snapshot(home):
    out = {}
    for root, _, files in os.walk(home):
        for f in files:
            p = os.path.join(root, f)
            out[p] = open(p, encoding="utf-8").read()
    return out


def main():
    tmp, home, env = make()
    # --- источник: task new ---
    a = new(env, "metis-pantheon")
    check("task new без --project: проект направления из реестра, а не имя папки", proj(home, a) == "Пантеон", proj(home, a))
    b = new(env, "plain-dir")
    check("направление без project в реестре: project = его имя", proj(home, b) == "plain-dir", proj(home, b))
    c = new(env, "themis-sources", "--project", "legal-watch и expert-corpus")
    check("--project с именем из реестра принят", proj(home, c) == "legal-watch и expert-corpus")
    before = snapshot(home)
    for bad in ("agent-kit", "metis-pantheon", "pantheon 0.11.28", "сверка Paperclip 17.10: у них #3207"):
        r = run(env, "task", "new", "--direction", "metis-pantheon", "--title", "X", "--project", bad)
        check(f"--project «{bad[:20]}»: отказ, код 1, файл не создан",
              r.returncode == 1 and "directions.toml" in r.stderr and snapshot(home) == before, (r.returncode, r.stderr[-200:]))
    st = run(env, "task", "new", "--direction", "metis-pantheon", "--type", "story", "--title", "Пачка")
    check("story без --project: проект направления", st.returncode == 0 and proj(home, st.stdout.split()[0]) == "Пантеон", st.stderr)

    # --- check ---
    r = run(env, "check")
    check("check на чистых данных: про project тишина", "project" not in r.stdout, r.stdout[-300:])
    clean_code = r.returncode
    for tid, v in ((a, "agent-kit"), (b, "metis-pantheon"), (c, "legal-watch")):
        assert run(env, "task", "set", tid, f"project={v}").returncode == 0
    r = run(env, "check")
    check("check: ошибка на каждый неизвестный project, код не 0",
          r.returncode != 0 and all(f"ОШИБКА · {t}: project" in r.stdout for t in (a, b, c)), (r.returncode, r.stdout[-400:]))
    r2 = run(env, "check", "--quiet")
    check("check --quiet не падает", r2.returncode == 0, r2.stderr[-200:])

    # --- миграция ---
    d = new(env, "themis-sources")
    e = new(env, "metis-pantheon")
    g = new(env, "themis-sources")
    for tid, v in ((d, "expert-corpus"), (e, "pantheon 0.11.28"), (g, "themis-sources")):
        assert run(env, "task", "set", tid, f"project={v}").returncode == 0
    ok_card = new(env, "metis-pantheon")
    # карточка без направления в реестре: project нельзя определить
    gh = os.path.join(home, "directions", "ghost", "tasks", "ghost-0001.md")
    open(gh, "w", encoding="utf-8").write(
        "---\ntype: task\nid: ghost-0001\ntitle: Призрак\nstatus: todo\nproject: мусор\ndirection: ghost\nowner: ghost\n"
        "created: 2026-10-15\nupdated: 2026-10-15T10:00:00\nschema_version: 1\n---\n\n# Призрак\n\n## Журнал\n")
    before = snapshot(home)
    for bad in (["--dry-run"], ["--write", "--x"], ["x"]):
        r = run(env, "task", "migrate-project", *bad)
        check(f"migrate-project {' '.join(bad)}: отказ, код 2, ничего не записано", r.returncode == 2 and snapshot(home) == before, r.returncode)
    r = run(env, "task", "migrate-project")
    want = {a: "Пантеон", b: "plain-dir", c: "legal-watch и expert-corpus", d: "legal-watch и expert-corpus",
            e: "Пантеон", g: "legal-watch и expert-corpus"}
    # b направления plain-dir: его проект — plain-dir, а project «metis-pantheon» — имя другого направления
    want[b] = "Пантеон"
    check("сухой прогон: «id: было → станет» по каждой карточке", all(f"{t}: " in r.stdout and f"→ {w}" in r.stdout for t, w in want.items()), r.stdout)
    check("сухой прогон: карточка из реестра не в списке", ok_card not in r.stdout)
    check("сухой прогон: направление вне реестра — «не определить», код 1",
          "ghost-0001" in r.stdout and "не определить" in r.stdout and r.returncode == 1, (r.returncode, r.stdout[-200:]))
    check("сухой прогон ничего не пишет", snapshot(home) == before)
    r = run(env, "task", "migrate-project", "--write", t=T0 + 100)
    pr = {i: proj(home, i) for i in want}
    check("--write: проекты перенесены (имя направления, папка, мусор → проект направления)", pr == want, pr)
    body = open(T.load_tasks(home, T.WORK_TYPES)[e][0], encoding="utf-8").read()
    check("--write: в журнале карточки строка «было → стало»", "project «pantheon 0.11.28» → «Пантеон»" in body, body[-300:])
    check("--write: призрак не тронут, код 1 (не определить)", r.returncode == 1 and "мусор" in open(gh, encoding="utf-8").read())
    check("--write: карточка из реестра не тронута", proj(home, ok_card) == "Пантеон" and "project «" not in
          open(T.load_tasks(home, T.WORK_TYPES)[ok_card][0], encoding="utf-8").read())
    os.remove(gh)
    after = snapshot(home)
    r = run(env, "task", "migrate-project", "--write", t=T0 + 200)
    check("повтор: переносить нечего, код 0, ничего не изменилось", r.returncode == 0 and "переносить нечего" in r.stdout and snapshot(home) == after, (r.returncode, r.stdout))
    r = run(env, "check")
    check("после миграции check не жалуется на project", "project" not in r.stdout, r.stdout[-300:])
    check("код check не ушёл вверх от project", r.returncode == clean_code, (r.returncode, clean_code))

    # --- без реестра: как раньше ---
    os.remove(os.path.join(home, "directions.toml"))
    r = run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Без реестра", "--project", "что угодно")
    check("реестра нет: project не сверяется", r.returncode == 0, r.stderr[-200:])
    shutil.rmtree(tmp, True)


def pure():
    """Чистые функции — и на системном Python 3.9 (без CLI)."""
    dirs = [{"name": "metis-pantheon", "project": "Пантеон", "folders": ["~/projects/agent-kit"]},
            {"name": "a-one", "project": "P", "folders": ["~/projects/shared"]},
            {"name": "b-two", "project": "Q", "folders": ["~/projects/shared"]}]
    al = T.project_aliases(dirs)
    check("псевдонимы: имя направления и папка", al.get("metis-pantheon") == "Пантеон" and al.get("agent-kit") == "Пантеон", al)
    check("псевдоним на два проекта не берётся", "shared" not in al, al)
    check("имя проекта не псевдоним", "Пантеон" not in al and "P" not in al)
    check("known_projects: проекты и «входящие»", T.known_projects(dirs) == {"Пантеон", "P", "Q", "входящие"})
    check("direction_project: inbox и реестр", T.direction_project(dirs, "inbox") == "входящие" and T.direction_project(dirs, "a-one") == "P"
          and T.direction_project(dirs, "нет") is None)


pure()
if PY311:
    main()
else:
    print("skip: нужен Python 3.11+ для CLI")
print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
