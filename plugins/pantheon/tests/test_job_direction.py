#!/usr/bin/env python3
"""metis-0886: задача расписания окном координатора направления (`direction = "<имя>"` и `text`), а не `claude -p`.

Запуск: python3 -I plugins/pantheon/tests/test_job_direction.py  (код выхода 0 — все прошли)
Проверяет на временных папках: run-job задачи с direction ставит разовый запуск окна этого направления
(STATE/oneshot.json — его поднимает дежурный, как заявку Зевса), claude не вызывается; направления нет в реестре
(domains.json) — запуск не ставится, одна тревога, код ALERTED; тик пускает задачу направления из реестра и пропускает
чужую; задача без direction — как раньше (роль из JOB_ROLES идёт, роль вне таблицы — нет). Мутанты: тест сам
копирует плагин, ломает по одному правилу и ждёт, что соответствующая проверка покраснеет.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot, copy_plugin  # CLI pantheon — только на Python 3.11+
import atexit

_ROOT = mkroot("tmp-jobdir-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1_792_000_000
ALERTED = 76
results = []





def check(name, ok):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name)


SCHED = '''[[job]]
name = "fin"
direction = "plutus-x"
text = "Обзор финансов: выполни процедуру обзора по шагам."
every = 20160
[[job]]
name = "ghost"
direction = "nobody-here"
text = "x"
every = 20160
[[job]]
name = "both"
direction = "plutus-x"
command = "pantheon view"
text = "x"
every = 20160
[[job]]
name = "clio-weekly"
command = "claude -p --agent clio \\"проход\\""
every = 10080
[[job]]
name = "plain"
command = "pantheon view"
every = 5
[[job]]
name = "argus-job"
command = "claude -p --agent argus \\"x\\""
every = 10080
'''


def scenario(lib):
    """Прогон на копии плагина с папкой lib → {проверка: прошла ли}."""
    run_py = os.path.join(lib, "run.py")
    tmp = tempfile.mkdtemp(prefix="tmp-jobdir-")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    folder = os.path.join(tmp, "projects", "finances")
    for d in (home, state, folder):
        os.makedirs(d)
    open(os.path.join(home, "schedule.toml"), "w").write(SCHED)
    # реестр: domains.json из directions.toml (pantheon domains build) — папки направления; первой папки нет на Mac
    json.dump({"domains": {"plutus-x": [os.path.join(tmp, "moved-away"), folder]}},
              open(os.path.join(state, "domains.json"), "w"))
    fake = os.path.join(tmp, "fakebin")
    os.makedirs(fake)
    calls = os.path.join(tmp, "claude-calls.log")
    open(os.path.join(fake, "claude"), "w").write(f'#!/bin/sh\necho "$@" >> {calls}\n')
    os.chmod(os.path.join(fake, "claude"), 0o755)
    env = {"PATH": fake + os.pathsep + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "PANTHEON_NO_NOTIFY": "1", "PANTHEON_NOW": str(T0)}

    def run(*args, extra=None):
        return subprocess.run([PY311, "-I", run_py, *args], env={**env, **(extra or {})}, capture_output=True,
                              text=True, timeout=60)

    def items():
        p = os.path.join(state, "oneshot.json")
        return json.load(open(p)).get("items", []) if os.path.exists(p) else []

    def alerts():
        p = os.path.join(home, "alerts.md")
        return open(p).read() if os.path.exists(p) else ""

    out = {}
    r = run("run-job", "fin")
    it = [x for x in items() if x.get("job") == "fin"]
    out["запуск окна"] = (r.returncode == 0 and len(it) == 1 and it[0]["target"] == "plutus-x"
                          and "Обзор финансов" in it[0]["text"] and not it[0].get("done_at")
                          and not os.path.exists(calls))
    # папку окна задача не называет: её берёт start из реестра — первая существующая (metis-0899)
    probe = (f"import sys; sys.path.insert(0, {lib!r}); import pantheon as p; "
             "print(p.start_target('plutus-x', [])[2])")
    out["папка из реестра"] = subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True,
                                             text=True).stdout.strip() == os.path.realpath(folder)
    # без direction — разбор команды прежний: роль из JOB_ROLES получает окно задачи, роль вне таблицы не идёт
    probe = (f"import sys, json; sys.path.insert(0, {lib!r}); import pantheon as p; "
             "print(json.dumps([p.direction_job(j) for j in p.load_schedule()['job'] if j['name'] in "
             "('clio-weekly', 'argus-job')] + [p.parse_command('claude -p --agent clio x'), "
             "p.parse_command('claude -p --agent argus x')]))")
    pr = json.loads(subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True).stdout or "0")
    out["без direction: JOB_ROLES"] = (isinstance(pr, list) and pr[:2] == [None, None]
                                     and pr[2] == ["claude", "-p", "--settings",
                                                   os.path.join(os.path.realpath(state), "settings", "job-clio.json"),
                                                   "--agent", "clio", "x"] and pr[3] is None)
    n = len(items())
    rg = [run("run-job", "ghost").returncode for _ in range(2)]
    al = alerts()
    out["нет в реестре"] = (rg == [ALERTED, ALERTED] and len(items()) == n
                            and al.count("задача ghost не идёт: окно направления не поднять") == 1
                            and "nobody-here" in al)
    rb = run("run-job", "both")
    out["direction и command"] = rb.returncode == ALERTED and len(items()) == n and "нет command" in alerts()
    jobs = run("jobs")
    out["pantheon jobs"] = (jobs.returncode == 0 and "окно направления не поднять" in jobs.stdout
                            and "nobody-here" in jobs.stdout)

    # тик (решения в dryrun.log): direction из реестра идёт, чужое направление и direction+command — нет;
    # без direction — как раньше: роль из JOB_ROLES идёт, роль вне таблицы пропущена с тревогой «команда»
    t_state = os.path.join(tmp, "state-tick")
    os.makedirs(t_state)
    shutil.copy(os.path.join(state, "domains.json"), t_state)
    a0 = len(alerts())
    rt = run("tick", extra={"PANTHEON_STATE": t_state, "PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1",
                            "PANTHEON_FAKE_WAKE": str(T0 - 7200), "PANTHEON_FAKE_AC": "1",
                            "PANTHEON_FAKE_IDLE": "1200", "PANTHEON_HOST": "mac-a"})
    log = os.path.join(t_state, "dryrun.log")
    ran = [ln.split()[1] for ln in open(log)] if os.path.exists(log) else []
    tal = alerts()[a0:]
    out["тик: направление из реестра"] = rt.returncode == 0 and "fin" in ran
    out["тик: нет в реестре"] = "ghost" not in ran and "both" not in ran and "задача ghost: окно направления" in tal
    out["тик: без direction как раньше"] = ("plain" in ran and "argus-job" not in ran
                                           and "задача argus-job: команда не разрешённого вида" in tal)
    return out


def copy_with(edit):
    """Копия плагина, в одном файле lib которой подменена строка: (файл, было, стало) → путь lib копии или None."""
    fname, old, new = edit
    dst = tempfile.mkdtemp(prefix="tmp-jobdir-mut-")
    copy_plugin(PLUGIN, os.path.join(dst, "pantheon"))
    lib = os.path.join(dst, "pantheon", "lib")
    p = os.path.join(lib, fname)
    src = open(p, encoding="utf-8").read()
    if src.count(old) != 1:
        return None
    open(p, "w", encoding="utf-8").write(src.replace(old, new))
    return lib


MUTANTS = [
    ("run-job без ветки направления", "запуск окна",
     ("jobs.py", "    if P.direction_job(job) is not None:\n        return run_direction_job(name, job)\n", "")),
    ("реестр не сверяется", "нет в реестре",
     ("pantheon.py", "    got = start_target(dj[0], [])\n", "    got = None\n")),
    ("тик не знает задач направления", "тик: направление из реестра",
     ("pantheon.py", "            if direction_job(job) is not None:  # окно направления",
      "            if False:  # окно направления")),
    ("тик не сверяет реестр", "тик: нет в реестре",
     ("pantheon.py", "                bad = direction_job_problem(job)\n                if bad:\n",
      "                bad = None\n                if bad:\n")),
    ("задача без direction считается задачей направления", "тик: без direction как раньше",
     ("pantheon.py", '    d = job.get("direction")\n    if d is None:\n        return None\n',
      '    d = job.get("direction")\n')),
]


def main():
    got = scenario(os.path.join(PLUGIN, "lib"))
    for k, v in got.items():
        check(k, v)
    for title, key, edit in MUTANTS:
        lib = copy_with(edit)
        if lib is None:
            check(f"мутант «{title}»: строка для подмены найдена", False)
            continue
        m = scenario(lib)
        check(f"мутант «{title}» убит проверкой «{key}»", m.get(key) is False)
    print(f"\n{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
