#!/usr/bin/env python3
"""pantheon direction check (навык new-direction, ROLE-05, STATE-11): что готово у нового направления.
Временный HOME: реестр, журнал решений, папка штаба, domains.json, окно, доверие, autoMode, names.part, репозиторий."""
import json
import os
import subprocess
import sys
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="direction-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="direction-test-"))
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    repo = os.path.join(tmp, "projects", "demo")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin", "git@github.com:latark/demo.git"], check=True)
    write(os.path.join(repo, "AGENTS.md"), "# demo\n")
    write(os.path.join(home, "directions.toml"),
          '[[direction]]\nname = "iris-demo"\nproject = "demo"\nfolders = ["~/projects/demo"]\nleads = ["hephaestus"]\n'
          'does = "Демо"\ndoes_not = "Чужое — соседям"\nexamples = ["раз", "два", "три"]\n')
    decisions = os.path.join(home, "decisions.md")
    write(decisions, "| Дата | Решение |\n| --- | --- |\n"
                     "| 15.10.2026 | Новое направление `iris-demo`. Ваши слова: «да» | — |\n")
    for x in ("inbox/.keep", "tasks/.keep", "STATUS.md"):
        write(os.path.join(home, "directions", "iris-demo", x), "")
    write(os.path.join(state, "domains.json"), json.dumps({"domains": {"iris-demo": [repo]}}))
    write(os.path.join(state, "settings", "iris-demo.json"), "{}")
    write(os.path.join(tmp, ".claude.json"), json.dumps({"projects": {repo: {"hasTrustDialogAccepted": True}}}))
    settings = os.path.join(tmp, ".claude", "settings.json")
    write(settings, json.dumps({"autoMode": {"environment": ["**Source control**: GitHub `github.com/latark/*`"]}}))
    write(os.path.join(tmp, ".claude", "agents", "_parts", "names.part"), "- она: Ирида (iris-demo)\n")
    write(os.path.join(tmp, ".claude", "agents", "hephaestus-demo.md"), "x")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    run = lambda name: subprocess.run([sys.executable, "-I", LIB, "direction", "check", name], env=env,
                                      capture_output=True, text=True)

    r = run("iris-demo")
    check("галочки на доске нет — «НЕТ»: строку decisions.md пишет Зевс, сама она не доказательство",
          r.returncode == 1 and "НЕТ     ваша галочка" in r.stdout)
    import time
    iso = lambda days: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))
    blog = os.path.join(state, "owner-log", "board.jsonl")
    rec = lambda days, q, a: json.dumps({"time": iso(days), "kind": "answer", "id": "x-0001", "answer": a,
                                         "question": q}, ensure_ascii=False) + "\n"
    write(blog, rec(0, "Сделать обзор недели?", "Да"))
    check("ваше «Да» на другой вопрос не засчитывается", run("iris-demo").returncode == 1)
    write(blog, rec(0, "Завести направление iris-demo-old?", "Да"))
    check("«Да» на вопрос о направлении с тем же началом имени не засчитывается", run("iris-demo").returncode == 1)
    write(blog, rec(0, "Завести направление iris-demo?", "Нет — пока не нужно"))
    check("ответ «Нет» не засчитывается", run("iris-demo").returncode == 1)
    write(blog, rec(20, "Завести направление iris-demo?", "Да — завести"))
    check("«Да» старше 14 дней не засчитывается", run("iris-demo").returncode == 1)
    write(blog, rec(0, "Завести направление iris-demo?", "Давай позже"))
    check("«Давай позже» начинается с «да», но согласием не считается", run("iris-demo").returncode == 1)
    write(blog, rec(0, "Сделать обзор недели? %%Завести направление iris-demo%%", "Да"))
    check("имя в скрытом тексте Obsidian (%%…%%) не засчитывается", run("iris-demo").returncode == 1)
    write(blog, rec(0, "Завести направление iris-demo? <!-- нет, это про обзор -->", "Да"))
    check("вопрос с HTML-разметкой не засчитывается", run("iris-demo").returncode == 1)
    write(blog, rec(0, "Завести направление iris-demo?", "Да — завести"))
    r = run("iris-demo")
    check("всё готово — код 0, ни одного «НЕТ»", r.returncode == 0 and "НЕТ" not in r.stdout)

    write(decisions, "| 15.10.2026 | Новое направление `iris-demo` — совет Зевса | — |\n")
    r = run("iris-demo")
    check("без ваших слов в decisions.md — код 1, «НЕТ» на строке «да»",
          r.returncode == 1 and "НЕТ     ваше «да»" in r.stdout)
    write(decisions, "| 15.10.2026 | Направление `iris-demo-old` закрыто. Ваши слова: «да» | — |\n")
    check("«да» другому направлению с тем же началом имени не засчитывается", run("iris-demo").returncode == 1)
    write(decisions, "| 15.10.2026 | Новое направление `iris-demo`. Ваши слова: «да» | — |\n")

    r = run("Iris_Demo")
    check("имя не по образцу — «НЕТ» на имени", r.returncode == 1 and "НЕТ     имя" in r.stdout)

    write(os.path.join(repo, "CLAUDE.md"), "# свои правила\n")
    check("CLAUDE.md без @AGENTS.md — не готово", "НЕТ     AGENTS.md" in run("iris-demo").stdout)
    write(os.path.join(repo, "CLAUDE.md"), "@AGENTS.md\n\nТолько для Claude.\n")
    check("CLAUDE.md, который начинается с @AGENTS.md, — готово", run("iris-demo").returncode == 0)

    write(os.path.join(repo, "AGENTS.md"), "x" * 40000)
    out = run("iris-demo").stdout
    check("AGENTS.md больше 32 КиБ без Codex на Mac — не блокирует, но видно",
          "готово  Codex: инструкции до 32 КиБ на путь (сейчас 39 КиБ; Codex на этом Mac нет" in out)
    os.makedirs(os.path.join(tmp, ".codex"))
    check("с Codex на Mac — не готово (Codex обрежет)", "НЕТ     Codex: инструкции до 32 КиБ" in run("iris-demo").stdout)
    os.rmdir(os.path.join(tmp, ".codex"))
    write(os.path.join(repo, "AGENTS.md"), "x\n" * 250)
    check("AGENTS.md 250 строк — Claude: длинно, не готово", "НЕТ     Claude: CLAUDE.md с импортами до 200 строк (сейчас 25"
          in run("iris-demo").stdout)
    write(os.path.join(repo, "AGENTS.md"), "# demo\n")
    write(settings, json.dumps({"autoMode": {"environment": ["**Source control**: GitHub `github.com/other/*`"]}}))
    check("владелец remote не описан в autoMode.environment — не готово",
          "НЕТ     владелец remote" in run("iris-demo").stdout)

    test_init()
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


def test_init():
    """pantheon direction init (metis-0042): папка ~/projects/<x> по галочке владельца — git init, AGENTS.md, коммит."""
    import time
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="direction-init-test-"))
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    projects = os.path.join(tmp, "projects")
    write(os.path.join(tmp, ".gitconfig"), "[user]\n\tname = Test\n\temail = test@example.com\n")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    run = lambda *a: subprocess.run([sys.executable, "-I", LIB, "direction", *a], env=env,
                                    capture_output=True, text=True)
    git = lambda p, *a: subprocess.run(["git", "-C", p, *a], env=env, capture_output=True, text=True).stdout.strip()
    reg = os.path.join(home, "directions.toml")
    setreg = lambda folders, name="iris-new": write(
        reg, f'[[direction]]\nname = "{name}"\nproject = "newx"\nfolders = {json.dumps(folders)}\n'
             'does = "Делает новое"\ndoes_not = "Старое — соседям"\nexamples = ["раз", "два", "три"]\n')
    write(os.path.join(home, "decisions.md"), "| 15.10.2026 | Новое направление `iris-new`. Ваши слова: «да» | — |\n")
    newx = os.path.join(projects, "newx")
    setreg(["~/projects/newx"])

    r = run("init", "iris-new")
    check("init: галочки владельца нет — код 1, «НЕТ» как у check, папка не создана",
          r.returncode == 1 and "НЕТ     ваша галочка" in r.stdout and not os.path.lexists(newx))
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    write(os.path.join(state, "owner-log", "board.jsonl"), json.dumps(
        {"time": iso, "kind": "answer", "id": "x-0001", "answer": "Да — завести",
         "question": "Завести направление iris-new?"}, ensure_ascii=False) + "\n")
    setreg(["~/projects/newx"], name="iris-other")
    r = run("init", "iris-new")
    check("init: нет записи в directions.toml — код 1, папка не создана",
          r.returncode == 1 and "НЕТ     запись в directions.toml" in r.stdout and not os.path.lexists(newx))
    setreg([])
    r = run("init", "iris-new")
    check("init: пустой folders — код 1, сообщение", r.returncode == 1 and "нет folders" in r.stdout)

    # отказы: проверка всех папок до создания — ни одна папка записи не появляется
    elsewhere = os.path.join(tmp, "elsewhere")
    os.makedirs(os.path.join(tmp, "target"))
    os.makedirs(projects, exist_ok=True)
    os.symlink(os.path.join(tmp, "target"), os.path.join(projects, "link"))
    for bad, what in ((["~/projects/oka", "~/projects/../x"], "«..»"),
                      (["~/projects/oka", "~/elsewhere/x"], "вне ~/projects"),
                      (["~/projects/oka", "~/projects/link"], "ссылка"),
                      (["~/projects/oka", "~/projects/.hidden"], "вне ~/projects")):
        setreg(bad)
        r = run("init", "iris-new")
        check(f"init: {bad[1]} — код 1, отказ ({what}), ничего не создано",
              r.returncode == 1 and what in r.stdout and not os.path.lexists(os.path.join(projects, "oka"))
              and not os.path.lexists(os.path.join(tmp, "x")) and not os.path.lexists(elsewhere)
              and not os.path.lexists(os.path.join(projects, ".hidden")) and os.listdir(os.path.join(tmp, "target")) == [])
    # ~/projects сам — ссылка в сторону: создавать в нём нельзя
    home2 = os.path.join(tmp, "home2")
    os.makedirs(os.path.join(tmp, "aside"))
    os.makedirs(home2)
    os.symlink(os.path.join(tmp, "aside"), os.path.join(home2, "projects"))
    setreg(["~/projects/viaLink"])
    r = subprocess.run([sys.executable, "-I", LIB, "direction", "init", "iris-new"], env=dict(env, HOME=home2),
                       capture_output=True, text=True)
    check("init: ~/projects — ссылка в сторону — код 1, ничего не создано",
          r.returncode == 1 and "вне ~/projects" in r.stdout and os.listdir(os.path.join(tmp, "aside")) == [])

    setreg(["~/projects/newx"])
    r = run("init", "iris-new")
    agents = os.path.join(newx, "AGENTS.md")
    text = open(agents, encoding="utf-8").read() if os.path.isfile(agents) else ""
    check("init: всё есть — код 0, ~/projects/newx с .git и AGENTS.md (does, does_not)",
          r.returncode == 0 and "создано ~/projects/newx" in r.stdout and os.path.isdir(os.path.join(newx, ".git"))
          and text.startswith("# newx\n") and "`iris-new`" in text and "Делает новое" in text
          and "Старое — соседям" in text and "Агор" not in text)
    check("init: ровно один коммит с AGENTS.md, ветка main, remote нет",
          git(newx, "rev-list", "--count", "HEAD") == "1" and git(newx, "log", "-1", "--format=%s")
          == "AGENTS.md (pantheon direction init)" and git(newx, "symbolic-ref", "--short", "HEAD") == "main"
          and git(newx, "remote") == "" and git(newx, "ls-files") == "AGENTS.md" and git(newx, "status", "--porcelain") == "")
    mtime = os.stat(agents).st_mtime_ns
    r = run("init", "iris-new")
    check("init: повтор — код 0, «есть, пропущено», AGENTS.md и коммиты те же",
          r.returncode == 0 and "есть, пропущено ~/projects/newx" in r.stdout and os.stat(agents).st_mtime_ns == mtime
          and git(newx, "rev-list", "--count", "HEAD") == "1")
    check("check после init: «AGENTS.md в папке запуска» — готово",
          "готово  AGENTS.md в папке запуска" in run("check", "iris-new").stdout)

    foreign = os.path.join(projects, "foreign")
    write(os.path.join(foreign, "README"), "чужое\n")
    setreg(["~/projects/foreign"])
    r = run("init", "iris-new")
    check("init: непустая чужая папка — не тронута, код 0",
          r.returncode == 0 and "не пуста" in r.stdout and os.listdir(foreign) == ["README"])

    half = os.path.join(projects, "half")
    os.makedirs(half)
    subprocess.run(["git", "init", "-q", "-b", "main", half], env=env, check=True)
    setreg(["~/projects/half"])
    r = run("init", "iris-new")
    check("init: прерванный запуск (.git без коммита) — доделано: AGENTS.md и коммит",
          r.returncode == 0 and "доделано ~/projects/half: AGENTS.md, коммит" in r.stdout
          and git(half, "rev-list", "--count", "HEAD") == "1")
    empty = os.path.join(projects, "empty")
    os.makedirs(empty)
    setreg(["~/projects/empty"])
    r = run("init", "iris-new")
    check("init: пустая папка — доделано: git init, AGENTS.md, коммит",
          r.returncode == 0 and "доделано ~/projects/empty: git init, AGENTS.md, коммит" in r.stdout
          and git(empty, "rev-list", "--count", "HEAD") == "1")

    # чужое не трогаем: пустой клон с remote, чужой коммит без remote
    clone = os.path.join(projects, "clone")
    subprocess.run(["git", "init", "-q", "-b", "main", clone], env=env, check=True)
    subprocess.run(["git", "-C", clone, "remote", "add", "origin", "git@github.com:x/clone.git"], env=env, check=True)
    setreg(["~/projects/clone"])
    r = run("init", "iris-new")
    check("init: пустой клон с remote — не тронут (нет AGENTS.md, нет коммита), код 0",
          r.returncode == 0 and "не пуста" in r.stdout and os.listdir(clone) == [".git"]
          and subprocess.run(["git", "-C", clone, "rev-parse", "--verify", "-q", "HEAD"], env=env).returncode != 0)
    alien = os.path.join(projects, "alien")
    subprocess.run(["git", "init", "-q", "-b", "main", alien], env=env, check=True)
    subprocess.run(["git", "-C", alien, "commit", "-q", "--allow-empty", "-m", "чужой"], env=env, check=True)
    setreg(["~/projects/alien"])
    r = run("init", "iris-new")
    check("init: чужой коммит без remote — не тронут, код 0",
          r.returncode == 0 and "не пуста" in r.stdout and os.listdir(alien) == [".git"]
          and git(alien, "rev-list", "--count", "HEAD") == "1")

    # папка запуска — по правилу start: первая существующая папка записи (после init — первая в списке)
    old = os.path.join(projects, "oldrepo")
    write(os.path.join(old, "main.py"), "print(1)\n")
    subprocess.run(["git", "init", "-q", "-b", "main", old], env=env, check=True)
    subprocess.run(["git", "-C", old, "add", "main.py"], env=env, check=True)
    subprocess.run(["git", "-C", old, "commit", "-q", "-m", "старое"], env=env, check=True)
    setreg(["~/projects/oldrepo", "~/projects/newa"])
    r = run("init", "iris-new")
    newa = os.path.join(projects, "newa")
    check("init A: папка запуска — существующий репозиторий: он не тронут, новая папка — только mkdir",
          r.returncode == 0 and "папка запуска" in r.stdout and "создано ~/projects/newa" in r.stdout
          and os.path.isdir(newa) and os.listdir(newa) == [] and sorted(os.listdir(old)) == [".git", "main.py"]
          and git(old, "rev-list", "--count", "HEAD") == "1")
    other = os.path.join(projects, "other", "y")
    write(os.path.join(other, "main.py"), "print(1)\n")
    setreg(["~/projects/other/y", "~/projects/newz"])
    r = run("init", "iris-new")
    newz = os.path.join(projects, "newz")
    check("init B: папка запуска вне ~/projects/<x> без git — «есть, пропущено», про папку запуска; новая — только mkdir",
          r.returncode == 0 and "есть, пропущено ~/projects/other/y — папка запуска" in r.stdout
          and os.listdir(other) == ["main.py"] and os.path.isdir(newz) and os.listdir(newz) == [])
    setreg(["~/projects/newb", "~/projects/newc"])
    r = run("init", "iris-new")
    newb, newc = os.path.join(projects, "newb"), os.path.join(projects, "newc")
    check("init: все папки новые — git и AGENTS.md в первой (папка запуска), остальные — только mkdir",
          r.returncode == 0 and git(newb, "rev-list", "--count", "HEAD") == "1"
          and os.path.isfile(os.path.join(newb, "AGENTS.md")) and os.listdir(newc) == [])
    setreg(["~/projects/other/y", "~/projects/newb"])
    check("check: папка запуска — первая существующая (правило start), а не первая с .git",
          "НЕТ     AGENTS.md в папке запуска" in run("check", "iris-new").stdout)

    # вызов из хука git: GIT_DIR чужого репозитория не уводит коммит туда
    outer = os.path.join(tmp, "outer")
    subprocess.run(["git", "init", "-q", outer], env=env, check=True)
    setreg(["~/projects/hooked"])
    env_hook = dict(env, GIT_DIR=os.path.join(outer, ".git"), GIT_WORK_TREE=outer)
    r = subprocess.run([sys.executable, "-I", LIB, "direction", "init", "iris-new"], env=env_hook,
                       capture_output=True, text=True)
    hooked = os.path.join(projects, "hooked")
    check("init: GIT_DIR/GIT_WORK_TREE из окружения не уводят git в чужой репозиторий",
          r.returncode == 0 and git(hooked, "rev-list", "--count", "HEAD") == "1"
          and subprocess.run(["git", "-C", outer, "rev-parse", "--verify", "-q", "HEAD"], env=env).returncode != 0)


if __name__ == "__main__":
    main()
