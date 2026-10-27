#!/usr/bin/env python3
"""Синтетические тесты планировщика: подменённые время, Mac, пробуждение, питание, простой и лимит.

Запуск: python3 -I plugins/pantheon/tests/test_tick.py  (код выхода 0 — все прошли)
Проверяет строки карты решений SCHED-02, SCHED-03, SCHED-06, SCHED-14, STATE-14 на временных папках:
задачи не запускаются (PANTHEON_DRYRUN), решения тика пишутся в dryrun.log.
"""
import json
import re
import os
import shlex
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="tick-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)
import time

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
T0 = 1_792_000_000  # опорное время


def make(tmp, schedule):
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home, exist_ok=True)
    open(os.path.join(home, "schedule.toml"), "w").write(schedule)
    return home, state


def tick(home, state, t, host="mac-a", wake=T0 - 7200, ac="1", idle=1200, limit=None, extra=None):
    env = {"PATH": os.environ["PATH"], "HOME": os.path.dirname(home), "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "PANTHEON_NOW": str(t), "PANTHEON_HOST": host, "PANTHEON_DRYRUN": "1",
           "PANTHEON_FAKE_WAKE": str(wake), "PANTHEON_FAKE_AC": ac, "PANTHEON_FAKE_IDLE": str(idle),
           "PANTHEON_NO_NOTIFY": "1"}
    if limit is not None:
        env["PANTHEON_FAKE_LIMIT"] = str(limit)
    env.update(extra or {})
    return subprocess.run([PY311, "-I", LIB, "tick"], env=env, capture_output=True, text=True, timeout=30)


def runs(state):
    p = os.path.join(state, "dryrun.log")
    return [ln.split()[1] for ln in open(p)] if os.path.exists(p) else []


def jstate(state, name):
    p = os.path.join(state, "jobs", name + ".json")
    return json.load(open(p)) if os.path.exists(p) else {}


SCHED = '''primary_host = "mac-a"
[[job]]
name = "view"
command = "pantheon view"
every = "tick"
[[job]]
name = "commit"
command = "pantheon view"
every = 5
[[job]]
name = "scout"
command = "pantheon view"
every = 10080
class = "heavy"
hosts = "primary"
claude = true
priority = 1
max_delay = 2880
[[job]]
name = "embed"
command = "pantheon view"
every = 60
class = "heavy"
priority = 2
max_delay = 180
'''


def main():
    results = []

    def check(name, cond):
        results.append(cond)
        print(("ok   " if cond else "FAIL ") + name)

    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, SCHED)
    tick(home, state, T0)
    r = runs(state)
    check("первый тик: лёгкие view и commit запущены", r.count("view") == 1 and r.count("commit") == 1)
    check("первый тик: одна тяжёлая (embed — приоритет выше), не две", r.count("embed") + r.count("scout") == 1 and "embed" in r)
    tick(home, state, T0 + 60)
    r = runs(state)
    check("через минуту: view снова, commit — нет (раз в 5 мин)", r.count("view") == 2 and r.count("commit") == 1)
    check("через минуту: вторая тяжёлая ждёт паузы 2 мин", r.count("scout") == 0
          and "пауза" in (jstate(state, "scout").get("waiting") or ""))
    tick(home, state, T0 + 180)
    check("через 3 мин: scout пошёл после паузы", runs(state).count("scout") == 1)
    tick(home, state, T0 + 3 * 3600)
    r = runs(state)
    check("после 3 часов сна: commit один раз, не 36", r.count("commit") == 2)
    tick(home, state, T0 + 3 * 3600 + 60)
    check("и на следующем тике commit не повторяется", runs(state).count("commit") == 2)

    # пробуждение, питание, простой, лимит
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, SCHED)
    tick(home, state, T0, wake=T0 - 300)
    check("5 мин после пробуждения: тяжёлые не идут", "embed" not in runs(state) and "scout" not in runs(state)
          and "пробуждения" in (jstate(state, "embed").get("waiting") or ""))
    tick(home, state, T0 + 60, wake=T0 - 7200, ac="0")
    check("на батарее: тяжёлые ждут сети", "embed" not in runs(state)
          and "сети" in (jstate(state, "embed").get("waiting") or ""))
    tick(home, state, T0 + 4 * 3600, wake=T0 - 7200, ac="0")
    check("max_delay (3 ч) истёк: embed идёт и на батарее", "embed" in runs(state))
    tick(home, state, T0 + 4 * 3600 + 300, wake=T0 - 7200, ac="1", idle=120)
    check("задача на Claude ждёт простоя 10 мин", "scout" not in runs(state)
          and "простоя" in (jstate(state, "scout").get("waiting") or ""))
    tick(home, state, T0 + 4 * 3600 + 600, idle=1200, limit=85)
    check("задача на Claude ждёт лимита < 70 %", "scout" not in runs(state)
          and "лимит" in (jstate(state, "scout").get("waiting") or ""))
    tick(home, state, T0 + 4 * 3600 + 900, idle=1200, limit=20)
    check("простой и лимит в норме: scout пошёл", "scout" in runs(state))

    # главный Mac
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, SCHED)
    tick(home, state, T0, host="mac-b")
    tick(home, state, T0 + 600, host="mac-b")
    r = runs(state)
    check("второй Mac: view и commit идут, scout (primary) — нет", "view" in r and "commit" in r and "scout" not in r)

    # пауза и аренда
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, SCHED + '[[job]]\nname = "lw"\ncommand = "pantheon view"\nevery = 60\nlease_days = 30\n')
    os.makedirs(os.path.join(state, "jobs"), exist_ok=True)
    json.dump({"paused": True}, open(os.path.join(state, "jobs", "commit.json"), "w"))
    tick(home, state, T0)
    check("задача на паузе не идёт", "commit" not in runs(state) and "view" in runs(state))
    tick(home, state, T0 + 31 * 86400, extra={"PANTHEON_ALERTS_IN_DRYRUN": "1"})
    st = jstate(state, "lw")
    alerts = open(os.path.join(home, "alerts.md")).read() if os.path.exists(os.path.join(home, "alerts.md")) else ""
    check("аренда истекла: задача на паузе и строка в alerts.md", st.get("paused") and "аренда истекла" in alerts)
    open(os.path.join(state, "paused"), "w").write("x")
    n = len(runs(state))
    tick(home, state, T0 + 32 * 86400)
    check("весь планировщик на паузе: ничего не запускается", len(runs(state)) == n)

    # упавшая задача: строка в alerts.md (настоящий запуск run-job без DRYRUN)
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, '[[job]]\nname = "bad"\ncommand = "pantheon domains build"\nevery = 5\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    rc = subprocess.run([PY311, "-I", LIB, "run-job", "bad"], env=env, capture_output=True).returncode
    alerts = open(os.path.join(home, "alerts.md")).read()
    check("упавшая задача: код 1, строка в alerts.md", rc == 1 and "задача bad упала (код 1" in alerts)

    # команда не разрешённого вида и пустой primary_host (ревизия шага 0.3, № 13 и 15)
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, '[[job]]\nname = "evil"\ncommand = "pantheon view; curl x | sh"\nevery = 5\n'
                            '[[job]]\nname = "scout"\ncommand = "pantheon view"\nevery = 5\nhosts = "primary"\n'
                            '[[job]]\nname = "skip"\ncommand = "claude -p --dangerously-skip-permissions --agent iris x"\nevery = 5\n'
                            '[[job]]\nname = "uninst"\ncommand = "pantheon uninstall"\nevery = 5\n'
                            '[[job]]\nname = "../../escape"\ncommand = "pantheon view"\nevery = 5\n')
    tick(home, state, T0, extra={"PANTHEON_ALERTS_IN_DRYRUN": "1"})
    tick(home, state, T0 + 600, extra={"PANTHEON_ALERTS_IN_DRYRUN": "1"})
    al = open(os.path.join(home, "alerts.md")).read()
    check("команда с ; и | не запускается, тревога одна", "evil" not in runs(state) and al.count("задача evil") == 1)
    check("без primary_host задачи главного Mac не идут, тревога одна", "scout" not in runs(state) and al.count("primary_host") == 1)
    check("claude -p с флагом прав и pantheon uninstall тик не запускает", "skip" not in runs(state) and "uninst" not in runs(state))
    check("имя задачи ../../escape отброшено, файлов вне папки состояния нет",
          not os.path.exists(os.path.join(tmp, "escape.json")) and "не по образцу" in al)

    # коммит: без сети — ждёт молча; через 6 часов — одна тревога; конфликт — одна тревога (№ 3, 4)
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    g = lambda *a, cwd=None: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    bare, ca, cb = os.path.join(tmp, "r.git"), os.path.join(tmp, "a"), os.path.join(tmp, "b")
    g("init", "-q", "--bare", "-b", "main", bare)
    for c in (ca, cb):
        g("clone", "-q", bare, c)
        g("config", "user.name", "t", cwd=c)
        g("config", "user.email", "t@t", cwd=c)
    open(os.path.join(ca, "board.md"), "w").write("строка 1\nстрока 2\n")
    g("add", "-A", cwd=ca); g("commit", "-qm", "init", cwd=ca); g("push", "-q", "-u", "origin", "main", cwd=ca)
    g("pull", "-q", "origin", "main", cwd=cb); g("branch", "-q", "--set-upstream-to=origin/main", "main", cwd=cb)
    st_dir = os.path.join(tmp, "state")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_STATE": st_dir, "PANTHEON_NO_NOTIFY": "1"}
    commit = lambda clone, now=None: subprocess.run([PY311, "-I", LIB, "commit"], capture_output=True, text=True,
                                                    env={**env, "PANTHEON_HOME": clone, **({"PANTHEON_NOW": str(now)} if now else {})}).returncode
    open(os.path.join(ca, "board.md"), "w").write("строка 1 — A\nстрока 2\n")
    open(os.path.join(cb, "board.md"), "w").write("строка 1 — B\nстрока 2\n")
    rc_a = commit(ca)
    rc_b1, rc_b2 = commit(cb), commit(cb)
    al_b = open(os.path.join(cb, "alerts.md")).read() if os.path.exists(os.path.join(cb, "alerts.md")) else ""
    check("конфликт: слияние отменено, код 76, тревога одна на два запуска", rc_a == 0 and rc_b1 == 76 and rc_b2 == 76
          and al_b.count("конфликт слияния") == 1 and not os.path.exists(os.path.join(cb, ".git", "MERGE_HEAD")))
    g("remote", "set-url", "origin", os.path.join(tmp, "нет-такого.git"), cwd=ca)
    open(os.path.join(ca, "board.md"), "a").write("ещё\n")
    rc_off = commit(ca)
    al_a = open(os.path.join(ca, "alerts.md")).read() if os.path.exists(os.path.join(ca, "alerts.md")) else ""
    check("без сети: код 75 и тишина", rc_off == 75 and "не синхронизируется" not in al_a)
    later = time.time() + 7 * 3600
    rc1, rc2 = commit(ca, later), commit(ca, later + 300)
    al_a = open(os.path.join(ca, "alerts.md")).read()
    check("без сети дольше 6 часов: одна тревога", rc1 == 75 and rc2 == 75 and al_a.count("не синхронизируется") == 1)

    # домены: реестр не отдаёт чужому направлению папку привилегированного координатора (№ 9)
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, "")
    open(os.path.join(home, "directions.toml"), "w").write(
        '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br", "~/projects/agent-kit"]\n'
        '[[direction]]\nname = "metis-pantheon"\nfolders = ["~/projects/agent-kit"]\n')
    os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
    open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w").write('[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n')
    # общий слой ролей плагина пуст: здесь каталог ролей — только то, что тест кладёт сам (оба слоя — test_roles.py)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_PLUGIN_ROLES": os.path.join(tmp, "plugin-roles-empty")}
    subprocess.run([PY311, "-I", LIB, "domains", "build"], env=env, capture_output=True)
    dj = json.load(open(os.path.join(state, "domains.json")))["domains"]
    check("реестр: папка Метиды у athena пропущена, у Метиды осталась",
          dj["athena-shop"] == ["~/projects/br"] and dj["metis-pantheon"] == ["~/projects/agent-kit"])

    # зарезервированные имена окон: hq, workshop, job-* — не направления (metis-0163)
    rtmp = tempfile.mkdtemp(prefix="tick-test-")
    rhome, rstate = make(rtmp, "")
    open(os.path.join(rhome, "directions.toml"), "w").write(
        "".join(f'[[direction]]\nname = "{n}"\nfolders = ["~/projects/br"]\n'
                for n in ("hq", "workshop", "hestia", "job-iris", "job-x", "athena-shop")))
    os.makedirs(os.path.join(rtmp, ".claude", "pantheon"))
    open(os.path.join(rtmp, ".claude", "pantheon", "policy.toml"), "w").write("")
    renv = {"PATH": os.environ["PATH"], "HOME": rtmp, "PANTHEON_HOME": rhome, "PANTHEON_STATE": rstate,
            "PANTHEON_NO_NOTIFY": "1"}
    rr = subprocess.run([PY311, "-I", LIB, "domains", "build"], env=renv, capture_output=True, text=True)
    rdj = json.load(open(os.path.join(rstate, "domains.json")))["domains"]
    check("реестр: направления hq, workshop, hestia, job-* пропущены с понятной ошибкой, обычное имя осталось",
          list(rdj) == ["athena-shop"] and rr.stderr.count("зарезервировано под окна системы") == 5
          and "«hestia»" in rr.stderr
          and "«job-iris»" in rr.stderr)

    # проектные allow папки запуска, пускающие gh pr merge: окно не собирается (metis-0137)
    def allow_build(tag, rules, fname="settings.json", second=None):
        atmp = os.path.realpath(tempfile.mkdtemp(prefix="tick-test-"))
        ahome, astate = make(atmp, "")
        os.makedirs(os.path.join(atmp, "projects", "br", ".claude"))
        os.makedirs(os.path.join(atmp, "projects", "ok"))
        open(os.path.join(ahome, "directions.toml"), "w").write(
            '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n'
            '[[direction]]\nname = "themis-docs"\nfolders = ["~/projects/ok"]\n')
        os.makedirs(os.path.join(atmp, ".claude", "pantheon"))
        open(os.path.join(atmp, ".claude", "pantheon", "policy.toml"), "w").write("")
        aenv = {"PATH": os.environ["PATH"], "HOME": atmp, "PANTHEON_HOME": ahome, "PANTHEON_STATE": astate,
                "PANTHEON_NO_NOTIFY": "1"}
        cli = lambda *a: subprocess.run([PY311, "-I", LIB, *a], env=aenv, capture_output=True, text=True)  # noqa: E731
        wr = lambda r: open(os.path.join(atmp, "projects", "br", ".claude", fname), "w").write(  # noqa: E731
            json.dumps({"permissions": {"allow": r}}))
        if second is not None:  # прежний файл окна от сборки без проблемы должен исчезнуть
            wr(second)
            cli("domains", "build")
        wr(rules)
        r = cli("domains", "build")
        win = os.path.join(astate, "settings", "athena-shop.json")
        return r, os.path.exists(win), os.path.exists(os.path.join(astate, "settings", "themis-docs.json")), cli, ahome

    r, built_a, built_t, cli, ahome = allow_build("a", ["Bash(gh *)", "Bash(ls *)"])
    check("allow Bash(gh *) в .claude/settings.json папки запуска — окно координатора не собирается; сообщение называет "
          "файл и правило и что сделать; соседнее направление собрано",
          not built_a and built_t and ".claude/settings.json" in r.stderr and "Bash(gh *)" in r.stderr
          and "убрать правило или сузить" in r.stderr)
    alerts = open(os.path.join(ahome, "alerts.md")).read() if os.path.exists(os.path.join(ahome, "alerts.md")) else ""
    chk = cli("check")
    check("тревога по направлению; pantheon check показывает то же предупреждение",
          "Bash(gh *)" in alerts and "предупреждение" in chk.stdout and "athena-shop" in chk.stdout
          and "Bash(gh *)" in chk.stdout)
    r, built_a, built_t, *_ = allow_build("b", ["Bash(gh pr view *)", "Bash(gh pr checks *)", "Bash(git status)", "Read(*)"])
    check("allow Bash(gh pr view *) и прочие узкие — окно собирается", built_a and "окно не собрано" not in r.stderr)
    for rule in ("Bash", "Bash(*)", "Bash(gh:*)", "Bash(gh pr merge:*)", "Bash(gh pr *)", "Bash(gh pr merge*)",
                 "Bash(gh pr merge 12 --admin)", "Bash(gh pr merge --admin *)", "Bash(gh pr merge --auto *)",
                 "Bash(gh pr merge -R *)", "Bash(gh pr merge --squash *)", "Bash(gh pr merge)",
                 "Bash(gh pr merge --admin)", "Bash(gh  pr merge *)", "Bash(GH_REPO=a/b gh pr merge *)",
                 "Bash(GH pr Merge *)", "Bash(g*)", "Bash(gh p*)",
                 # абсолютный путь к gh — это gh
                 "Bash(/opt/homebrew/bin/gh pr merge *)", "Bash(/usr/local/bin/gh *)", "Bash(/usr/bin/gh pr merge)",
                 "Bash(/opt/homebrew/bin/gh:*)",
                 # обёртки, пускающие любую команду
                 "Bash(env *)", "Bash(bash -c *)", "Bash(sh -c *)", "Bash(zsh -c *)", "Bash(command *)",
                 "Bash(xargs *)", "Bash(eval *)",
                 # их вариации: путь, VAR=, флаги, «:*», регистр, обёртка вокруг gh, кавычка после -c
                 "Bash(/usr/bin/env *)", "Bash(FOO=1 env *)", "Bash(env -i *)", "Bash(env FOO=1 *)", "Bash(env:*)",
                 "Bash(ENV  *)", "Bash(env gh pr merge *)", "Bash(command /opt/homebrew/bin/gh *)",
                 "Bash(bash -lc *)", "Bash(bash -c 'gh pr merge *')", "Bash(xargs -n1 gh pr merge *)",
                 "Bash(env -u HOME gh pr merge *)", "Bash(bash *)", "Bash(eval gh pr merge 12 --admin)"):
        r, built_a, *_ = allow_build("c", [rule])
        check(f"allow {rule!r} — окно не собирается", not built_a and rule in r.stderr)
    shown = [x.strip() for x in r.stdout.splitlines() if "окон ролей" in x]
    check("несобранное окно не числится в списке собранных окон ролей",
          bool(shown) and all("athena-shop" not in x for x in shown) and "themis-docs" in shown[0])
    for rule in ("Bash(gh pr view *)", "Bash(gh pr checks *)", "Bash(gh pr diff *)", "Bash(gh run view *)",
                 "Bash(git *)", "Bash(env)", "Bash(bash ./scripts/test.sh *)", "Bash(command -v gh)",
                 "Bash(/opt/homebrew/bin/gh pr view *)", "Bash(env FOO=1)", "Bash(env gh pr view *)", "Bash(bash -c)",
                 "Bash(./scripts/*)"):
        r, built_a, *_ = allow_build("g", [rule])
        check(f"allow {rule!r} — не слияние: окно собирается", built_a)
    r, built_a, *_ = allow_build("d", ["Bash(gh *)"], fname="settings.local.json")
    check("то же в settings.local.json — не собирается, файл назван", not built_a and "settings.local.json" in r.stderr)
    r, built_a, *_ = allow_build("e", ["Bash(gh *)"], second=["Bash(ls *)"])
    check("окно было собрано, правило появилось — прежний файл окна убран (pantheon start не стартует)", not built_a)
    r, built_a, *_ = allow_build("f", ["Bash(gh:*)", "Bash(ghx)"][1:])
    check("Bash(ghx) — не gh pr merge: окно собирается", built_a)

    # песочница окон ролей (SEC-19): строгий вид, папки направления, SSH-remote → сетевой git мимо песочницы
    br = os.path.join(tmp, "projects", "br", "app")
    os.makedirs(br)
    subprocess.run(["git", "init", "-q", br], check=True)
    subprocess.run(["git", "-C", br, "remote", "add", "origin", "git@github.com:x/y.git"], check=True)
    for d in ("pantheon/directions/athena-shop", "projects/zz", "ai/knowledge", ".cache/metis", ".ssh", "pantheon/scout",
              ".claude/plugins/marketplaces/agent-kit/plugins/guard/hooks"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    open(os.path.join(tmp, ".claude/plugins/marketplaces/agent-kit/plugins/guard/hooks/guard.py"), "w").write("# guard\n")
    # metis-0321: окна берут guard только из проверенного дерева кэша (verified.json), клон — никогда
    groot = os.path.join(tmp, ".claude/plugins/cache/agent-kit/guard/0.1.0")
    os.makedirs(os.path.join(groot, "hooks"))
    os.makedirs(os.path.join(groot, ".claude-plugin"))
    open(os.path.join(groot, "hooks", "guard.py"), "w").write("# guard из кэша\n")
    open(os.path.join(groot, ".claude-plugin", "plugin.json"), "w").write('{"name": "guard", "version": "0.1.0"}')
    open(os.path.join(tmp, ".claude/plugins/installed_plugins.json"), "w").write(json.dumps(
        {"version": 2, "plugins": {"guard@agent-kit": [{"scope": "user", "installPath": groot}]}}))
    subprocess.run([PY311, "-I", LIB, "plugins", "accept", "guard"], env=env, capture_output=True, check=True)
    os.symlink(os.path.join(tmp, "pantheon"), os.path.join(tmp, "projects", "ln"))
    with open(os.path.join(home, "directions.toml"), "a") as fh:
        fh.write('sandbox_write = ["~/.ssh"]\n'
                 '[[direction]]\nname = "mnemo-brain"\nfolders = ["~/ai/knowledge"]\n'
                 '[[direction]]\nname = "zz"\nfolders = ["~/ai/pantheon", "~/projects", "~/projects/zz", "~/.claude", '
                 '"~/projects/ln"]\n')
    with open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "a") as fh:
        fh.write('[sandbox_write]\nmetis-pantheon = ["~/.cache/metis", "~/ai/pantheon", "~/.cache/../.ssh"]\n'
                 '[private]\ncoordinators = ["mnemo-brain"]\npaths = ["~/ai/knowledge/me", "~/ai/pantheon/.git/git-crypt"]\n'
                 '[merge_repos]\nathena-shop = ["acme-co/br-app"]\n'
                 'metis-pantheon = ["tools-org/sync", "acme-co/kit", "bad owner/x", "acme-co/kit`"]\n'
                 'mnemo-brain = ["acme-co/notes"]\n'
                 # что закрыто штабу — только [hq] (metis-0182); выдуманный корпус lecture-notes
                 '[hq]\nclosed_dirs = ["~/projects/lecture-notes", "~/.cache/qmd", "~/.cache/lecture-notes", '
                 '"~/.claude/projects/*lecture-notes*"]\nclosed_collections = ["notes"]\n')
    os.makedirs(os.path.join(state, "settings"), exist_ok=True)
    open(os.path.join(state, "settings", "old-direction.json"), "w").write("{}")
    dash = lambda p: re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(p))
    for n in (dash(home), dash(home) + "--claude-worktrees-x", dash(tmp)):
        os.makedirs(os.path.join(tmp, ".claude", "projects", n), exist_ok=True)
    # память субагентов (metis-0051): роль с memory:, без неё, главная роль с memory:, роль-ссылка
    ag = os.path.join(tmp, ".claude", "agents")
    os.makedirs(ag, exist_ok=True)
    for r, hd in (("argus", "name: argus\nmemory: user\n"), ("dev-sonnet", "name: dev-sonnet\nmodel: sonnet\n"),
                  ("domain-coordinator", "name: domain-coordinator\nmemory: user\n"),
                  ("linked", "name: linked\nmemory: user\n")):
        open(os.path.join(ag, r + ".md"), "w").write(f"---\n{hd}---\nтекст\n")
    os.makedirs(os.path.join(tmp, "foreign-mem"))
    os.makedirs(os.path.join(tmp, ".claude", "agent-memory"), exist_ok=True)
    os.symlink(os.path.join(tmp, "foreign-mem"), os.path.join(tmp, ".claude", "agent-memory", "linked"))
    subprocess.run([PY311, "-I", LIB, "domains", "build"], env=env, capture_output=True)
    load = lambda n: json.load(open(os.path.join(state, "settings", n + ".json")))
    sa, sm, sw, sn, sz = load("athena-shop"), load("metis-pantheon"), load("workshop"), load("mnemo-brain"), load("zz")
    real = lambda x: os.path.realpath(os.path.join(tmp, x))
    box = sa["sandbox"]
    aw = box["filesystem"]["allowWrite"]
    check("песочница: строгий вид, папки направления и своё directions/<имя>/ настоящими путями, окно сжатия",
          box["enabled"] and box["failIfUnavailable"] and box["allowUnsandboxedCommands"] is False
          and real("projects/br") in aw and real("pantheon/directions/athena-shop") in aw
          and not any("~" in x or "agent-kit" in x for x in aw)
          and "~/**/.git/config" in box["filesystem"]["denyWrite"] and sa["autoCompactWindow"] == 200000)
    check("песочница: git push/fetch/pull мимо песочницы у каждого направления, и без SSH-remote (metis-0064)",
          all("git push *" in w["sandbox"]["excludedCommands"] and "git push" in w["sandbox"]["excludedCommands"]
              for w in (sa, sm, sn, sz)))
    # мастерская: тот же сетевой git — только при SSH-remote в ~/projects/workshop; здесь его нет
    check("песочница: у мастерской без SSH-remote сетевого git мимо песочницы нет",
          not any(x.startswith("git ") for x in sw["sandbox"]["excludedCommands"]))
    # metis-0141 п. 3: репозиторий с SSH-remote в подпапке ~/projects/workshop → сетевой git мимо песочницы есть;
    # убрали репозиторий — снова нет (сборка настоящая, окно workshop пересобирается)
    wr = os.path.join(tmp, "projects", "workshop", "t1")
    os.makedirs(wr, exist_ok=True)
    subprocess.run(["git", "init", "-q", wr], check=True)
    subprocess.run(["git", "-C", wr, "remote", "add", "origin", "git@github.com:x/w.git"], check=True)
    subprocess.run([PY311, "-I", LIB, "domains", "build"], env=env, capture_output=True)
    swx = load("workshop")["sandbox"]["excludedCommands"]
    check("песочница: у мастерской при SSH-remote в ~/projects/workshop git push/fetch/pull мимо песочницы",
          all(c in swx for c in ("git push", "git push *", "git fetch", "git fetch *", "git pull", "git pull *")))
    _shutil.rmtree(wr)
    subprocess.run([PY311, "-I", LIB, "domains", "build"], env=env, capture_output=True)
    check("песочница: репозиторий с SSH-remote убран → у мастерской сетевого git снова нет",
          not any(x.startswith("git ") for x in load("workshop")["sandbox"]["excludedCommands"]))
    reads = ["gh pr view", "gh pr view *", "gh pr checks", "gh pr checks *", "gh pr diff", "gh pr diff *",
             "gh pr list", "gh pr list *"]
    check("gh мимо песочницы (P0-4): нет gh api, gh issue и gh pr *; чтение PR (view/checks/diff/list) — у всех окон, "
          "кроме штаба",
          all(not any(x.startswith(("gh api", "gh issue")) or x == "gh pr *" for x in w["sandbox"]["excludedCommands"])
              for w in (sa, sm, sn, sz, sw))
          and all(all(r in w["sandbox"]["excludedCommands"] for r in reads) for w in (sa, sm, sn, sz, sw))
          and all(x in sa["sandbox"]["excludedCommands"] for x in ("gh repo view *", "gh auth status",
                                                                    "pantheon alert *", "pantheon consent *",
                                                                    "pantheon saved *")))
    run_reads = ["gh run view", "gh run view *", "gh run list", "gh run list *", "gh run watch", "gh run watch *"]
    check("gh run мимо песочницы — только чтение (view/list/watch, голые и со звёздочкой); cancel, rerun, delete и "
          "«gh run *» падают в песочнице",
          all(sorted(x for x in w["sandbox"]["excludedCommands"] if x.startswith("gh run")) == sorted(run_reads)
              for w in (sa, sm, sn, sz, sw)))
    check("gh pr create/edit/merge мимо песочницы — только в окнах направлений; у мастерской нет (metis-0247)",
          all(all(c in w["sandbox"]["excludedCommands"] for c in ("gh pr create *", "gh pr edit *", "gh pr merge *"))
              for w in (sa, sm, sn, sz))
          and not any(x.startswith(("gh pr create", "gh pr edit", "gh pr merge")) for x in sw["sandbox"]["excludedCommands"]))
    # metis-0247: весь gh мимо песочницы окна направления — ровно этот список. gh api, gh issue, gh pr close|comment|
    # review|ready, gh run cancel, «gh *» и «gh pr *» в него не попадают и в песочнице падают (TLS Go, x509 -26276)
    coord_gh = sorted(reads + run_reads + ["gh repo view *", "gh auth status", "gh pr create *", "gh pr edit *",
                                           "gh pr merge *"])
    check("окно координатора: gh мимо песочницы — ровно чтение, create/edit/merge; gh api и прочий gh — нет (metis-0247)",
          all(sorted(x for x in w["sandbox"]["excludedCommands"] if x.split()[0] == "gh") == coord_gh
              for w in (sa, sm, sn, sz)))
    check("песочница: `pantheon direction init *` мимо неё только в окне Метиды (metis-0042)",
          "pantheon direction init *" in sm["sandbox"]["excludedCommands"]
          and not any("direction" in x for w in (sa, sw, sn, sz) for x in w["sandbox"]["excludedCommands"]))
    merge_ex = ["pantheon merge request *", "pantheon merge status", "pantheon merge cancel *"]
    check("песочница: заявка на слияние по Touch ID мимо неё только в окне Метиды, `pantheon merge run` — нигде "
          "(metis-0285)",
          all(x in sm["sandbox"]["excludedCommands"] for x in merge_ex)
          and not any("merge run" in x or x == "pantheon merge *" for w in (sa, sm, sw, sn, sz)
                      for x in w["sandbox"]["excludedCommands"])
          and not any(x.startswith("pantheon merge") for w in (sa, sw, sn, sz) for x in w["sandbox"]["excludedCommands"]))
    cache_a = real("Library/Caches/pantheon-sandbox/athena-shop")
    check("песочница: кэши свои у направления (папка создана), общих в записи нет",
          sa["env"]["npm_config_cache"] == os.path.join(cache_a, "npm") and os.path.isdir(cache_a)
          and sa["env"]["XDG_CACHE_HOME"] != sm["env"]["XDG_CACHE_HOME"] and cache_a in aw
          and not any(x.endswith(("/.npm", "/.cache/uv", "/Library/pnpm")) for x in aw))
    mw = sm["sandbox"]["filesystem"]["allowWrite"]
    check("песочница: доп. запись — только из policy.toml и только кэши; реестр права не даёт",
          real(".cache/metis") in mw and not any(x.endswith(("/pantheon", "/.ssh")) for x in mw)
          and ".ssh" not in json.dumps(sa) + json.dumps(sm))
    zw = sz["sandbox"]["filesystem"]["allowWrite"]
    check("песочница: папки направления — только внутри ~/projects и ~/ai/knowledge, ссылки пропущены",
          zw[0] == real("projects/zz") and real("projects") not in zw and real("pantheon") not in zw
          and not any(x.endswith(("/.claude", "/ln")) for x in zw) and real("ai/knowledge") in sn["sandbox"]["filesystem"]["allowWrite"])
    dw, dr = box["filesystem"]["denyWrite"], box["filesystem"]["denyRead"]
    check("песочница: запреты и настоящими путями — .git внутри каждой разрешённой папки, личное — оба вида",
          real("projects/br") + "/**/.git/config" in dw and real("projects/br") + "/.git/hooks" in dw
          and cache_a + "/**/.git/hooks" in dw and real("ai/knowledge/me") in dr and "~/ai/knowledge/me" in dr)
    check("denyWrite: .claude/agents каждой папки (репозитория) окна, и в worktree внутри неё — как .git/config (metis-0140)",
          real("projects/br") + "/.claude/agents" in dw and real("projects/br") + "/**/.claude/agents" in dw
          and all(f + "/.claude/agents" in dw for f in box["filesystem"]["allowWrite"]))
    check("песочница: terminal-notifier ролям не прочитать и не запустить",
          "/opt/homebrew/Cellar/terminal-notifier" in box["filesystem"]["denyRead"]
          and "/opt/homebrew/Cellar/terminal-notifier" in sw["sandbox"]["filesystem"]["denyRead"])
    check("песочница: личное закрыто для чтения всем, кроме координатора с привилегией; мастерская; старый файл убран",
          "~/ai/knowledge/me" in box["filesystem"]["denyRead"] and not any("knowledge" in x for x in sn["sandbox"]["filesystem"]["denyRead"])
          and "~/ai/knowledge/me" in sw["sandbox"]["filesystem"]["denyRead"] and "autoCompactWindow" not in sw
          and not os.path.exists(os.path.join(state, "settings", "old-direction.json")))
    # вторая запись PreToolUse у координаторов и штаба — хук субагентов окна (P0-6, test_agent_allowlist.py)
    hk = [h for g in sa.get("hooks", {}).get("PreToolUse", []) if g["matcher"] != "Agent|Task|Skill" for h in g["hooks"]]
    gpath = os.path.realpath(os.path.join(groot, "hooks", "guard.py"))
    check("строгий guard в окне роли (SEC-29): --strict, onFailure block, только проверенный кэш, у мастерской тоже",
          len(hk) == 1 and hk[0]["onFailure"] == "block" and hk[0]["command"] == f"python3 {gpath} --strict"
          and "projects" not in hk[0]["command"] and sw["hooks"]["PreToolUse"] == sa["hooks"]["PreToolUse"][:1]
          and sa["hooks"]["PreToolUse"][0]["matcher"] == "Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob|Agent|Task|Skill")
    hq = load("hq")
    hb = hq["sandbox"]
    check("окно штаба (SEC-26): пишет только ~/ai/pantheon без .git и alerts.md, сети нет, мимо песочницы — start/wake/alert",
          hb["filesystem"]["allowWrite"][0] == real("pantheon") and real("projects/br") not in hb["filesystem"]["allowWrite"]
          and real("pantheon/.git") in hb["filesystem"]["denyWrite"] and real("pantheon/alerts.md") in hb["filesystem"]["denyWrite"]
          and hb["network"]["allowedDomains"] == [] and "~/ai/pantheon/.git/git-crypt" in hb["filesystem"]["denyRead"] and "pantheon start *" in hb["excludedCommands"]
          and "git push *" not in hb["excludedCommands"]
          and hq["hooks"]["PreToolUse"][0] == sa["hooks"]["PreToolUse"][0] and "worktree" not in hq
          and "~/ai/knowledge/me" not in hb["filesystem"]["denyRead"])
    check("окно штаба: мимо песочницы — прежний список пульта и gh PR (view/checks/edit), без сетевого git "
          "(metis-0064, metis-0247)",
          hb["excludedCommands"] == ["pantheon alert *", "pantheon start *", "pantheon wake", "pantheon wake *",
                                     "pantheon archive", "pantheon jobs *", "pantheon domains build",
                                     "pantheon roles build", "pantheon stop *", "pantheon resume *", "pantheon pause *",
                                     "pantheon restart *", "pantheon saved *", "pantheon who", "pantheon agents",
                                     "sessync find", "sessync find *",
                                     "gh pr view", "gh pr view *", "gh pr checks", "gh pr checks *", "gh pr edit *"])
    others = {n: load(n)["sandbox"]["excludedCommands"] for n in ("athena-shop", "metis-pantheon", "workshop",
                                                                    "mnemo-brain", "zz", "hestia")}
    others.update({f"job-{r}": load(f"job-{r}")["sandbox"]["excludedCommands"]
                   for r in ("clio", "prometheus", "iris") if os.path.exists(os.path.join(state, "settings", f"job-{r}.json"))})
    check("sessync find (metis-0566): мимо песочницы только у окна штаба; у окон направлений, мастерской, Гестии и "
          "задач его нет",
          len(others) >= 7 and not any("sessync" in x for v in others.values() for x in v)
          and "sessync find *" in hb["excludedCommands"])
    check("окно штаба: gh api, gh issue, gh run, gh repo, gh pr create/close/comment/merge, gh с флагами до "
          "подкоманды, «gh *» и «gh pr *» — в песочнице (metis-0247)",
          not any(x.startswith(("gh api", "gh issue", "gh run", "gh repo", "gh pr create", "gh pr close", "gh pr merge",
                                "gh -",
                                "gh pr comment", "gh pr review", "gh pr diff", "gh pr list"))
                  or x in ("gh", "gh *", "gh pr", "gh pr *") for x in hb["excludedCommands"]))
    corp = "lecture-notes"
    check("окно штаба: корпус из [hq].closed_dirs закрыт для чтения — песочница и правило Read (SEC-13, решение 15.10)",
          all(x in hb["filesystem"]["denyRead"] for x in (f"~/projects/{corp}", "~/.cache/qmd",
                                                           f"~/.cache/{corp}", f"~/.claude/projects/*{corp}*"))
          and "Read(~/.cache/qmd/**)" in hq["permissions"]["deny"]
          and any(x.endswith("pantheon-sandbox/workshop") for x in hb["filesystem"]["denyRead"])
          and not any(x.endswith("pantheon-sandbox/hq") for x in hb["filesystem"]["denyRead"])
          and "Read(~/.claude/projects/**/*.jsonl)" in hq["permissions"]["deny"]
          and any("tool-results" in x and "-projects-*" in x for x in hq["permissions"]["deny"])
          and any(f"claude-{os.getuid()}" in x for x in hb["filesystem"]["denyRead"]))
    check("окно штаба: выводы чужих сессий закрыты (и в ~), свои и своих worktree — нет",
          f"Read(~/.claude/projects/{dash(tmp)}/**/tool-results/**)" in hq["permissions"]["deny"]
          and not any(dash(home) in x for x in hq["permissions"]["deny"])
          and f"Read(~/projects/{corp}/**)" in hq["permissions"]["deny"]
          and any(x.startswith("Read(//") and x.endswith(f"/{corp}/**)") for x in hq["permissions"]["deny"]))
    check("окна направлений: worktree от HEAD (эпик), у мастерской — нет; места heavy созданы",
          sa["worktree"] == {"baseRef": "head"} and sm["worktree"] == {"baseRef": "head"} and "worktree" not in sw
          and os.path.exists(os.path.join(state, "locks", "heavy-cmd-2.lock")))
    # голый mktemp на macOS пишет в /var/folders/…/T (_CS_DARWIN_USER_TEMP_DIR раньше TMPDIR); владелец 15.10 решил не
    # открывать эту общую временную папку всех программ, а роли берут `mktemp -p "$TMPDIR"` (metis-0091)
    every = (sa, sm, sw, sn, sz, hq)
    # тестовый корень tmp лежит под TMPDIR: при TMPDIR=/var/folders/… его путь сам содержит /var/folders. Срезаем
    # префикс tmp (и его realpath) до поиска, поэтому проверка смотрит только на пути вне тестового корня (metis-0117)
    cut = sorted({tmp, os.path.realpath(tmp)}, key=len, reverse=True)

    def outside(p):
        for c in cut:
            p = p.replace(c, "")
        return p

    def wide_path(p):
        q = outside(p)
        return "/var/folders" in q or q.rstrip("/") in ("/var", "/private/var", "/private")

    wide = [x for w in every for x in w["sandbox"]["filesystem"]["allowWrite"] + list(w["env"].values())
            if wide_path(x)]
    check("временные файлы: /var/folders не открыт ни одному окну, TMPDIR окно не подменяет (metis-0091, решение 15.10)",
          not wide and not any("TMPDIR" in w["env"] for w in every))

    merge = "Bash(gh pr merge *)"
    check("окно координатора направления: gh pr merge НЕТ в permissions.allow (allow срабатывает раньше классификатора "
          "и пускал бы --admin/--auto, metis-0137); у мастерской и штаба тоже",
          all(merge not in json.dumps(w.get("permissions", {})) and not (w.get("permissions") or {}).get("allow")
              for w in (sa, sm, sn, sw, hq)))
    am = {n: w.get("autoMode", {}).get("allow") or [] for n, w in
          (("athena-shop", sa), ("metis-pantheon", sm), ("mnemo-brain", sn), ("zz", sz))}
    rule = lambda n, head: [r for r in am[n] if r.startswith(head)]
    gated = rule("athena-shop", "Pantheon Gated Merge:")
    record = rule("athena-shop", "Pantheon Review Record:")
    check("окна координаторов и Метиды: autoMode.allow — \"$defaults\" первым, слияние, сдача лида (metis-0215) и Review Record; без [merge_repos] "
          "— без правила слияния (metis-0098)",
          all(a[:1] == ["$defaults"] for a in am.values()) and len(record) == 1
          and all(len(am[n]) == 4 and len(rule(n, "Pantheon Gated Merge:")) == 1
                  and len(rule(n, "Pantheon Lead Delivery:")) == 1 and rule(n, "Pantheon Review Record:")
                  == record for n in ("athena-shop", "metis-pantheon"))
          and am["zz"] == ["$defaults"] + record)
    check("окно с доступом к личному (mnemo-brain): \"$defaults\" и только Review Record — правила слияния нет даже "
          "при [merge_repos], его PR сливает владелец (metis-0156)",
          bool(record) and am["mnemo-brain"] == ["$defaults"] + record)
    check("правило Review Record: оговорка — после `--` только тест-раннер проекта, его судят прочие правила; merge, "
          "push, gh, sh -c/python3 -c — Self-Approval или CI Bypass (metis-0156)",
          bool(record) and all(x in record[0] for x in (
              "covers only the `pantheon review` recording wrapper itself", "the command after `--` must be the "
              "project's own test runner", "judged by every other rule exactly as if it were run on its own",
              "A merge, push, deploy, `gh` or network command", "`sh -c`/`python3 -c` one-liner",
              "stays Self-Approval or CI Bypass")))
    gm = rule("metis-pantheon", "Pantheon Gated Merge:")
    texts = json.dumps(list(am.values()))
    check("правило слияния: репозитории — ровно [merge_repos] своего направления (owner/repo), имён владельца и "
          "направлений в тексте правил нет (metis-0098, решение 16.10)",
          bool(gated) and bool(gm) and "(`acme-co/br-app`)" in gated[0] and "acme-co/kit" not in gated[0]
          and "(`acme-co/kit`, `tools-org/sync`)" in gm[0] and "bad owner" not in gm[0] and "kit``" not in gm[0]
          and not any(x in texts for x in ("athena-shop", "metis-pantheon", "mnemo-brain", "workshop",
                                           "agent-kit", "projects/br", "ai/knowledge")))
    check("правило Gated Merge: обе формы репозитория, перечень argus, ядро — сливает сам владелец, --admin/--auto не "
          "разрешает (metis-0098)",
          bool(gated) and all(x in gated[0] for x in ("`-R <owner/repo>`", "`--repo <owner/repo>`",
                                                      "--match-head-commit", "checklist", "plugins/guard/",
                                                      "plugins/pantheon/roles/", "window_rules.py", "owner to merge them himself", "`--admin`, `--auto`", "`gh api`",
                                                      "still judged by Merge Without Review")))
    check("штаб и мастерская: autoMode в окне нет — классификатор у них со встроенными правилами (metis-0098)",
          "autoMode" not in hq and "autoMode" not in sw)
    mem_a = real(".claude/agent-memory/argus")
    wins = (sa, sm, sw, hq)
    check("память субагентов в песочнице всех окон: роль с memory: настоящим путём, папка создана (metis-0051)",
          os.path.isdir(mem_a) and all(mem_a in w["sandbox"]["filesystem"]["allowWrite"] for w in wins)
          and mem_a + "/.git/config" in sa["sandbox"]["filesystem"]["denyWrite"])
    check("память субагентов: роли без memory:, главной роли и ссылки в песочнице нет",
          not any(x.endswith(("/agent-memory/dev-sonnet", "/agent-memory/domain-coordinator", "/agent-memory/linked"))
                  or x == real("foreign-mem") for w in wins for x in w["sandbox"]["filesystem"]["allowWrite"])
          and not os.path.exists(os.path.join(tmp, ".claude", "agent-memory", "dev-sonnet"))
          and not os.path.exists(os.path.join(tmp, ".claude", "agent-memory", "domain-coordinator"))
          and "foreign-mem" not in json.dumps(wins))
    # «не пересобирает» напрямую не проверить: --if-changed следит и за общей /tmp/claude-<uid>, её трогают другие сессии.
    # Поэтому: сборка не трогает каталог ролей (цикла нет), а новая роль с memory: пересборку вызывает
    t0 = json.load(open(os.path.join(state, "domains.json")))["built_ts"]
    no_loop = os.path.getmtime(ag) <= t0
    open(os.path.join(ag, "prometheus.md"), "w").write("---\nname: prometheus\nmemory: user\n---\nтекст\n")
    subprocess.run([PY311, "-I", LIB, "domains", "build", "--if-changed"], env=env, capture_output=True)
    mem_p = real(".claude/agent-memory/prometheus")
    check("каталог ролей: сборка его не трогает, новая роль с memory: — пересборка и её память в окнах",
          no_loop and json.load(open(os.path.join(state, "domains.json")))["built_ts"] > t0
          and mem_p in load("athena-shop")["sandbox"]["filesystem"]["allowWrite"]
          and mem_p in load("hq")["sandbox"]["filesystem"]["allowWrite"])

    # ревью 90a, п.4: обновили плагин (installed_plugins.json новее сборки) — окна пересобираются на новый путь guard
    t1 = json.load(open(os.path.join(state, "domains.json")))["built_ts"]
    inst = os.path.join(tmp, ".claude", "plugins", "installed_plugins.json")
    os.makedirs(os.path.dirname(inst), exist_ok=True)
    open(inst, "w").write("{}")
    os.utime(inst, (t1 + 30, t1 + 30))
    subprocess.run([PY311, "-I", LIB, "domains", "build", "--if-changed"], env=env, capture_output=True)
    check("installed_plugins.json новее сборки: окна пересобраны (built_ts вырос)",
          json.load(open(os.path.join(state, "domains.json")))["built_ts"] > t1)

    # окна задач расписания (P0-3, metis-0063): clio, prometheus, iris — своя песочница
    jc, jp, ji = load("job-clio"), load("job-prometheus"), load("job-iris")
    know, scout = real("ai/knowledge"), real("pantheon/scout")
    caches = real("Library/Caches/pantheon-sandbox")
    mems = [x for x in jc["sandbox"]["filesystem"]["allowWrite"] if "/agent-memory/" in x]
    check("окно задачи: пишет только своё — clio и prometheus ~/ai/knowledge, iris scout/; память ролей и свой кэш",
          jc["sandbox"]["filesystem"]["allowWrite"] == [know] + mems + [caches + "/job-clio"]
          and jp["sandbox"]["filesystem"]["allowWrite"] == [know] + mems + [caches + "/job-prometheus"]
          and ji["sandbox"]["filesystem"]["allowWrite"] == [scout] + mems + [caches + "/job-iris"]
          and mem_p in mems and os.path.isdir(caches + "/job-iris"))
    check("окно задачи: строгая песочница, сети Bash нет, мимо неё — только pantheon alert",
          all(w["sandbox"]["enabled"] and w["sandbox"]["failIfUnavailable"] and w["sandbox"]["allowUnsandboxedCommands"] is False
              and w["sandbox"]["network"]["allowedDomains"] == [] and w["sandbox"]["excludedCommands"] == ["pantheon alert *"]
              for w in (jc, jp, ji)))
    check("окно задачи: личное закрыто на чтение и на запись (оба вида пути), .git/config — на запись",
          all(x in w["sandbox"]["filesystem"][k] for w in (jc, jp, ji) for k in ("denyRead", "denyWrite")
              for x in ("~/ai/knowledge/me", real("ai/knowledge/me"), "~/ai/pantheon/.git/git-crypt"))
          and know + "/.git/config" in jc["sandbox"]["filesystem"]["denyWrite"])
    check("окно задачи: строгий guard-хук, роль окна в env, без координаторских правил",
          all(w["hooks"]["PreToolUse"][:1] == sa["hooks"]["PreToolUse"][:1] and w["env"]["PANTHEON_ROLE"] == r
              and set(w.get("permissions", {})) == {"deny"} and "autoCompactWindow" not in w
              for w, r in ((jc, "clio"), (jp, "prometheus"), (ji, "iris"))))
    check("окно задачи: autoMode координатора нет — исключения классификатора только у окон направлений (metis-0098)",
          all("autoMode" not in w for w in (jc, jp, ji)))
    # субагенты окна задачи (P0-6): хук agents.py с заглушкой «никого» и deny Agent(...) всем известным типам
    agents_py = os.path.join(os.path.dirname(os.path.dirname(LIB)), "hooks", "agents.py")

    def job_hook(w, ev):
        hk = [h for g in w["hooks"]["PreToolUse"] if g["matcher"] == "Agent|Task|Skill" for h in g["hooks"]]
        argv = shlex.split(hk[0]["command"]) if len(hk) == 1 else []
        if len(argv) != 3 or not argv[1].endswith("/hooks/agents.py") or hk[0].get("onFailure") != "block":
            return None
        r = subprocess.run([sys.executable, "-I", agents_py, argv[2]], input=json.dumps(ev), capture_output=True, text=True)
        return r.returncode, "deny" in r.stdout
    ag = lambda t: {"tool_name": "Agent", "tool_input": {"subagent_type": t, "prompt": "x"}, "cwd": tmp}  # noqa: E731
    skill = {"tool_name": "Skill", "tool_input": {"skill": "plain-skill"}, "cwd": tmp}
    check("окно задачи: чужой субагент закрыт хуком — dev-opus, general-purpose, пустой тип, argus; обычный навык идёт",
          all(job_hook(w, ag(t)) == (0, True) for w in (jc, jp, ji) for t in ("dev-opus", "general-purpose", "", "argus"))
          and all(job_hook(w, skill) == (0, False) for w in (jc, jp, ji)))
    check("окно задачи: deny Agent(...) — встроенные, роли из ~/.claude/agents, главные роли",
          all(f"Agent({t})" in w["permissions"]["deny"] for w in (jc, jp, ji)
              for t in ("general-purpose", "claude", "Explore", "argus", "dev-sonnet", "hq", "domain-coordinator")))
    check("окно штаба: кэши задач (выдача из веба) закрыты для чтения",
          any(x.endswith("pantheon-sandbox/job-prometheus") for x in load("hq")["sandbox"]["filesystem"]["denyRead"]))
    os.remove(os.path.join(state, "settings", "job-iris.json"))
    subprocess.run([PY311, "-I", LIB, "domains", "build", "--if-changed"], env=env, capture_output=True)
    check("domains build --if-changed: пропавшее окно задачи пересобирается",
          os.path.isfile(os.path.join(state, "settings", "job-iris.json")))

    # разбор команды задачи: --settings окна роли, модель iris, роль вне таблицы
    probe = f"""
import json, sys
sys.path.insert(0, {os.path.dirname(LIB)!r})
import pantheon as p
cmds = ['claude -p --agent clio "проход"', 'claude -p --agent iris --model haiku --max-turns 5 "x"',
        'claude -p --agent iris "x"', 'claude -p --agent argus "x"', 'claude -p --agent clio --settings /tmp/a.json "x"',
        'claude -p --agent prometheus --model opus "x"']
print(json.dumps({{c: p.parse_command(c) for c in cmds}}))
"""
    got = json.loads(subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True).stdout)
    win = lambda r: os.path.join(os.path.realpath(state), "settings", f"job-{r}.json")  # noqa: E731
    check("parse_command: claude -p получает --settings окна задачи роли, -p первым",
          got['claude -p --agent clio "проход"'] == ["claude", "-p", "--settings", win("clio"), "--agent", "clio", "проход"]
          and got['claude -p --agent prometheus --model opus "x"'] == ["claude", "-p", "--settings", win("prometheus"),
                                                                       "--agent", "prometheus", "--model", "opus", "x"])
    check("parse_command: iris — --model sonnet вместо любого из команды",
          got['claude -p --agent iris --model haiku --max-turns 5 "x"'] == [
              "claude", "-p", "--settings", win("iris"), "--agent", "iris", "--model", "sonnet", "--max-turns", "5", "x"]
          and got['claude -p --agent iris "x"'] == ["claude", "-p", "--settings", win("iris"), "--agent", "iris",
                                                    "--model", "sonnet", "x"])
    check("parse_command: роль без окна задачи и --settings в команде — не разрешены",
          got['claude -p --agent argus "x"'] is None and got['claude -p --agent clio --settings /tmp/a.json "x"'] is None)

    # run-job: окна нет или это ссылка — задача не идёт (claude не вызван), одна тревога, код не 0; окно есть — идёт
    fake = os.path.join(tmp, "fakebin")
    os.makedirs(fake)
    calls = os.path.join(tmp, "claude-calls.log")
    open(os.path.join(fake, "claude"), "w").write(f'#!/bin/sh\necho "$@" >> {calls}\n')
    os.chmod(os.path.join(fake, "claude"), 0o755)
    open(os.path.join(home, "schedule.toml"), "w").write(
        '[[job]]\nname = "clio-weekly"\ncommand = "claude -p --agent clio \\"проход\\""\nevery = 10080\nnotify = false\n')
    jenv = {**env, "PATH": fake + os.pathsep + os.environ["PATH"], "PANTHEON_NO_NOTIFY": "1"}
    os.remove(win("clio"))
    al0 = open(os.path.join(home, "alerts.md")).read() if os.path.exists(os.path.join(home, "alerts.md")) else ""
    rcs = [subprocess.run([PY311, "-I", LIB, "run-job", "clio-weekly"], env=jenv, capture_output=True).returncode
           for _ in range(2)]
    al = open(os.path.join(home, "alerts.md")).read()[len(al0):]
    jobs = subprocess.run([PY311, "-I", LIB, "jobs"], env=jenv, capture_output=True, text=True)
    check("run-job: окна задачи нет — claude не вызван, код не 0, тревога одна с «pantheon domains build»",
          rcs[0] != 0 and rcs[1] != 0 and not os.path.exists(calls)
          and al.count("задача clio-weekly не идёт") == 1 and "pantheon domains build" in al)
    check("pantheon jobs: не падает и показывает причину", jobs.returncode == 0 and "нет окна песочницы" in jobs.stdout)
    os.symlink(os.path.join(tmp, "pantheon", "schedule.toml"), win("clio"))
    rc_link = subprocess.run([PY311, "-I", LIB, "run-job", "clio-weekly"], env=jenv, capture_output=True).returncode
    check("run-job: окно задачи — ссылка, а не обычный файл — claude не вызван",
          rc_link != 0 and not os.path.exists(calls))
    os.remove(win("clio"))
    subprocess.run([PY311, "-I", LIB, "domains", "build"], env=env, capture_output=True)
    # run_env ставит /opt/homebrew/bin и папку python перед PATH: настоящий claude там перехватил бы подменный
    shadow = [d for d in ("/opt/homebrew/bin", os.path.dirname(sys.executable)) if os.path.exists(os.path.join(d, "claude"))]
    if shadow:
        print(f"skip run-job с окном: настоящий claude в {shadow[0]} раньше подменного")
    else:
        rc_ok = subprocess.run([PY311, "-I", LIB, "run-job", "clio-weekly"], env=jenv,
                               capture_output=True).returncode
        called = open(calls).read() if os.path.exists(calls) else ""
        check("run-job: окно на месте — claude -p идёт с --settings окна clio",
              rc_ok == 0 and called.strip() == f"-p --settings {win('clio')} --agent clio проход")

    # архив (STATE-14)
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, "")
    open(os.path.join(home, "board.md"), "w").write(
        "# Доска\n\n## Сейчас\n\n- 2026-10-01 старое, но не в «Сделано»\n\n## Сделано\n\n"
        "- 2026-10-01 закрыт эпик A\n  подробности A\n- 13.10 закрыт эпик B\n"
        "- Claude Code 2.1.12 обновлён 12.10\n\n## Ждёт вас\n\n- карточка\n")
    open(os.path.join(home, "alerts.md"), "w").write(
        "# Тревоги\n\n2026-09-01 10:00 · watch · старая тревога\n2026-10-13 10:00 · watch · свежая тревога\n")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NOW": str(1760432400)}  # 2025-10-14 — год подставляется из «сейчас»
    env["PANTHEON_NOW"] = str(1791958800)   # 2026-10-14
    subprocess.run([PY311, "-I", LIB, "archive"], env=env, capture_output=True)
    board = open(os.path.join(home, "board.md")).read()
    arch = open(os.path.join(home, "archive", "board-2026-10.md")).read()
    check("архив: «Сделано» старше 7 дней ушло вместе с подробностями, свежее осталось",
          "эпик A" not in board and "подробности A" not in board and "эпик B" in board and "эпик A" in arch
          and "2.1.12" in board
          and "подробности A" in arch and "старое, но не в «Сделано»" in board)
    al = open(os.path.join(home, "alerts.md")).read()
    check("архив: тревоги старше 30 дней ушли", "старая тревога" not in al and "свежая тревога" in al
          and os.path.exists(os.path.join(home, "archive", "alerts-2026-09.md")))

    # критичная находка (COMM-08): строка с пометкой и уведомление; обычная — без уведомления
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, "")
    log = os.path.join(tmp, "notify.log")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NOTIFY_LOG": log}
    subprocess.run([PY311, "-I", LIB, "alert", "обычная", "--from", "athena"], env=env, capture_output=True)
    rc = subprocess.run([PY311, "-I", LIB, "alert", "ключ в логе", "--critical", "--from", "zeus"],
                        env={**env, "PANTHEON_ROLE": "hq"}, capture_output=True).returncode
    al = open(os.path.join(home, "alerts.md")).read()
    sent = open(log).read() if os.path.exists(log) else ""
    check("alert --critical: «КРИТИЧНО» в alerts.md и одно уведомление от того, кто нашёл",
          rc == 0 and "zeus · КРИТИЧНО: ключ в логе" in al and "athena · обычная" in al
          and sent.count("\n") == 1 and "Пантеон · критично|ключ в логе (со слов: zeus)" in sent)
    subprocess.run([PY311, "-I", LIB, "alert", "прод упал", "--critical", "--from", "zeus"],
                   env={**env, "PANTHEON_ROLE": "workshop"}, capture_output=True)
    sent = open(log).read()
    check("alert --critical: заголовок не называет отправителя — имя только «со слов»",
          "Пантеон · критично|прод упал (со слов: zeus)" in sent and "· zeus|" not in sent)

    # metis-0184: второй параллельный тик выходит без работы, пока первый держит блокировку
    import fcntl
    tmp = tempfile.mkdtemp(prefix="tick-test-")
    home, state = make(tmp, SCHED)
    os.makedirs(os.path.join(state, "locks"), exist_ok=True)
    with open(os.path.join(state, "locks", "tick.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        rb = tick(home, state, T0)
    check("0184: второй тик при занятой блокировке выходит с 0 без запусков и без метки last-tick",
          rb.returncode == 0 and runs(state) == [] and not os.path.exists(os.path.join(state, "last-tick")))
    tick(home, state, T0)
    check("0184: контроль: тик без чужой блокировки работает", runs(state).count("view") == 1
          and os.path.exists(os.path.join(state, "last-tick")))

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
