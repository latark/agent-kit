#!/usr/bin/env python3
"""Синтетические тесты планировщика: подменённые время, Mac, пробуждение, питание, простой и лимит.

Запуск: python3 -I plugins/pantheon/tests/test_tick.py  (код выхода 0 — все прошли)
Проверяет строки карты решений SCHED-02, SCHED-03, SCHED-06, SCHED-14, STATE-14 на временных папках:
задачи не запускаются (PANTHEON_DRYRUN), решения тика пишутся в dryrun.log.
"""
import json
import os
import subprocess
import sys
import tempfile
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
    return subprocess.run([sys.executable, "-I", LIB, "tick"], env=env, capture_output=True, text=True, timeout=30)


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
    rc = subprocess.run([sys.executable, "-I", LIB, "run-job", "bad"], env=env, capture_output=True).returncode
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
    commit = lambda clone, now=None: subprocess.run([sys.executable, "-I", LIB, "commit"], capture_output=True, text=True,
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
        '[[direction]]\nname = "athena-broker"\nfolders = ["~/projects/br", "~/projects/agent-kit"]\n'
        '[[direction]]\nname = "metis-pantheon"\nfolders = ["~/projects/agent-kit"]\n')
    os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
    open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w").write('[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state}
    subprocess.run([sys.executable, "-I", LIB, "domains", "build"], env=env, capture_output=True)
    dj = json.load(open(os.path.join(state, "domains.json")))["domains"]
    check("реестр: папка Метиды у athena пропущена, у Метиды осталась",
          dj["athena-broker"] == ["~/projects/br"] and dj["metis-pantheon"] == ["~/projects/agent-kit"])

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
    subprocess.run([sys.executable, "-I", LIB, "archive"], env=env, capture_output=True)
    board = open(os.path.join(home, "board.md")).read()
    arch = open(os.path.join(home, "archive", "board-2026-10.md")).read()
    check("архив: «Сделано» старше 7 дней ушло вместе с подробностями, свежее осталось",
          "эпик A" not in board and "подробности A" not in board and "эпик B" in board and "эпик A" in arch
          and "2.1.12" in board
          and "подробности A" in arch and "старое, но не в «Сделано»" in board)
    al = open(os.path.join(home, "alerts.md")).read()
    check("архив: тревоги старше 30 дней ушли", "старая тревога" not in al and "свежая тревога" in al
          and os.path.exists(os.path.join(home, "archive", "alerts-2026-09.md")))

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
