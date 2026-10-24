#!/usr/bin/env python3
"""Переключатель координатора направления (metis-0155, вариант Б): `coordinator = false` в directions.toml —
направление ведёт Пританей. start/wake координатора не поднимают, `pantheon wake <направление> --task <id>` поднимает
фоновое окно лида hephaestus-<коротко> с окном координатора, пульт пишет «ведёт Пританей», `pantheon check` сверяет
поле и открытого координатора, самозапуск такое направление пропускает.

Запуск: python3 -I plugins/pantheon/tests/test_coord_switch.py  (код выхода 0 — все прошли)
claude подменён скриптом в PATH, как в test_start.py: `claude agents --json --all` отдаёт FAKE_AGENTS, остальные
вызовы пишет в FAKE_LOG (argv и папку запуска).
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="coord-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(ROOT, "lib")
LIB = os.path.join(LIB_DIR, "pantheon.py")
sys.path.insert(0, LIB_DIR)
import tasks as T  # noqa: E402  — пульт проверяется и на системном 3.9

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
af = os.environ["FAKE_AGENTS"]
def save(p, data):
    with open(p + ".tmp", "w") as fh:
        json.dump(data, fh)
    os.replace(p + ".tmp", p)
if sys.argv[1:3] == ["agents", "--json"]:
    print(open(af).read())
    sys.exit(0)
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
args = sys.argv[1:]
agents = json.load(open(af))
if "--bg" in args and "--name" in args:
    agents.append({"id": "n" + os.urandom(3).hex(), "name": args[args.index("--name") + 1], "state": "working",
                   "kind": "background"})
    save(af, agents)
'''

REG = ('[[direction]]\nname = "athena-shop"\nproject = "ExampleApp"\nfolders = ["~/projects/br"]\n'
       'leads = ["hephaestus"]\n'
       '[[direction]]\nname = "hermes-site"\nproject = "Site"\nfolders = ["~/projects/site"]\nleads = ["hephaestus"]\n'
       'coordinator = false\n'
       '[[direction]]\nname = "iris-x"\nfolders = ["~/projects/x"]\ncoordinator = false\n')

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else f"  [{detail}]"))


def board_tests():
    """Пульт: проект направления с coordinator = false — «ведёт Пританей» вместо ссылки на координатора."""
    reg = T.project_registry([{"name": "athena-shop", "project": "Shop"},
                              {"name": "hermes-site", "project": "Site", "coordinator": False},
                              {"name": "iris-x", "coordinator": "false"}])
    check("пульт: coordinator = false — hq_led у проекта; не задан и не булево — координатор включён",
          reg["Site"]["hq_led"] is True and reg["Shop"]["hq_led"] is False and reg["iris-x"]["hq_led"] is False,
          {k: v["hq_led"] for k, v in reg.items()})
    t = time.time()
    site = T.render_project_note("Site", reg["Site"], {}, t)
    shop = T.render_project_note("Shop", reg["Shop"], {}, t)
    check("пульт: заметка проекта, который ведёт Пританей, — «Координатор: ведёт Пританей» в шапке и в тексте",
          "**Координатор:** ведёт Пританей" in site and "Координатор: ведёт Пританей" in site, site[:400])
    check("пульт: проект с координатором — ссылка на координатора, без «ведёт Пританей»",
          "ведёт Пританей" not in shop and "**Координатор:** [[" in shop, shop[:400])


def cli_tests():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="coord-test-"))
    home, state, bindir = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state"), os.path.join(tmp, "bin")
    agents_dir = os.path.join(tmp, ".claude", "agents")
    for d in (home, bindir, agents_dir, os.path.join(agents_dir, "_parts"), os.path.join(tmp, "projects", "br"),
              os.path.join(tmp, "projects", "site"), os.path.join(tmp, "projects", "x"),
              *(os.path.join(home, "directions", n, "tasks") for n in ("athena-shop", "hermes-site", "iris-x"))):
        os.makedirs(d, exist_ok=True)
    open(os.path.join(bindir, "sysctl"), "w").write(
        '#!/bin/sh\ncase "$*" in\n *vm.swapusage*) echo "vm.swapusage: total = 4096.00M  used = 100.00M'
        '  free = 3000.00M  (encrypted)";;\n *pressure_level*) echo 1;;\n *) exit 1;;\nesac\n')
    open(os.path.join(bindir, "memory_pressure"), "w").write('#!/bin/sh\necho "System-wide memory free percentage: 60%"\n')
    open(os.path.join(bindir, "claude"), "w").write(FAKE)
    for f in ("sysctl", "memory_pressure", "claude"):
        os.chmod(os.path.join(bindir, f), 0o755)
    agents_file, log = os.path.join(tmp, "agents.json"), os.path.join(tmp, "claude.log")
    open(agents_file, "w").write("[]")
    reg_path = os.path.join(home, "directions.toml")
    open(reg_path, "w").write(REG)
    open(os.path.join(agents_dir, "hephaestus.tmpl"), "w").write(
        "---\nname: hephaestus-{{short}}\ndescription: Лид кода {{direction}}\n---\n\nЛид {{direction}}.\n")
    env = {"PATH": bindir + os.pathsep + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "FAKE_AGENTS": agents_file, "FAKE_LOG": log, "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_STOP_WAIT": "3", "PANTHEON_STOP_POLL": "0.02", "PANTHEON_STOP_SETTLE": "0.5",
           "PANTHEON_NAME_WAIT": "1", "PANTHEON_PLUGIN_ROLES": os.path.join(tmp, "plugin-roles-empty")}

    def run(*args, extra=None):
        e = dict(env, **(extra or {}))
        return subprocess.run([PY311, "-I", LIB, *args], env=e, capture_output=True, text=True, timeout=120)

    def calls():
        return [json.loads(x) for x in open(log)] if os.path.exists(log) else []

    def bg():
        return [c for c in calls() if "--bg" in c["argv"]]

    def task(tid, status, direction):
        open(os.path.join(home, "directions", direction, "tasks", tid + ".md"), "w").write(
            f"---\ntype: task\nid: {tid}\ntitle: t\nstatus: {status}\nproject: P\ndirection: {direction}\n"
            + ("next: дальше\n" if status == "doing" else "") + ("closed: 2026-10-14\n" if status == "done" else "") + "created: 2026-10-14\nupdated: 2026-10-14\n"
            "schema_version: 1\n---\n\n## Журнал\n")

    zlog = os.path.join(state, "owner-log", "zeus.md")

    def word():
        os.makedirs(os.path.dirname(zlog), exist_ok=True)
        open(zlog, "w").write(time.strftime("## %Y-%m-%d %H:%M:%S\nподними лида\n\n"))

    r = run("domains", "build")
    check("domains build: окно hermes-site собрано и лид hephaestus-site собран — как у любого направления",
          r.returncode == 0 and os.path.isfile(os.path.join(state, "settings", "hermes-site.json"))
          and os.path.isfile(os.path.join(agents_dir, "hephaestus-site.md")), r.stderr[-400:])
    task("hermes-0001", "doing", "hermes-site")
    task("hermes-0002", "done", "hermes-site")
    task("athena-0001", "doing", "athena-shop")
    task("iris-0001", "todo", "iris-x")
    lrun = os.path.join(state, "settings", "run", "hephaestus-site.json")

    # start и wake координатора выключенного направления — отказ, claude не зовётся
    rs = [run("start", "hermes-site"), run("start", "hermes-site", "--dry-run"), run("start", "hermes-site", "--at", "23:59"),
          run("wake", "hermes-site")]
    check("start, start --dry-run, start --at и wake выключенного направления — код 2 «ведёт Пританей», claude не звали",
          all(x.returncode == 2 and "ведёт Пританей" in x.stderr and "--task" in x.stderr for x in rs) and not calls()
          and not os.path.exists(os.path.join(state, "settings", "run", "hermes-site.json"))
          and not os.path.exists(os.path.join(state, "oneshot.json")), [(x.returncode, x.stderr[-200:]) for x in rs])
    r = run("start", "athena-shop", "--dry-run")
    check("start --dry-run направления с координатором — как раньше: --agent domain-coordinator --name athena-shop",
          r.returncode == 0 and "--agent domain-coordinator --name athena-shop" in r.stdout, r.stdout + r.stderr)

    # wake --task: задача должна быть открытой задачей этого направления
    rs = [run("wake", "hermes-site", "--task"), run("wake", "hermes-site", "--task", "nonsense"),
          run("wake", "hermes-site", "--task", "hermes-9999"), run("wake", "hermes-site", "--task", "hermes-0002"),
          run("wake", "hermes-site", "--task", "athena-0001"), run("wake", "hermes-site", "--task", "hermes-0001", "x")]
    check("wake <направление> --task: без id, не по образцу, несуществующая, закрытая, чужого направления — код 2 "
          "«нет задачи», claude не звали",
          all(x.returncode == 2 and "отказ — нет задачи" in x.stderr
              and x.stderr.strip().splitlines()[-1].endswith("claude не запускался") for x in rs)
          and "не открыта (done)" in rs[3].stderr and "направления athena-shop, не hermes-site" in rs[4].stderr
          and not calls() and not os.path.exists(lrun), [(x.returncode, x.stderr[-160:]) for x in rs])
    r = run("wake", "athena-shop", "--task", "athena-0001")
    check("wake --task у направления со своим координатором — код 2 «свой координатор», claude не звали",
          r.returncode == 2 and "свой координатор" in r.stderr and not calls(), r.stderr)
    r = run("wake", "nobody-here", "--task", "athena-0001")
    check("wake --task не направления — код 2", r.returncode == 2 and "не направление" in r.stderr and not calls())
    r = run("wake", "iris-x", "--task", "iris-0001")
    check("wake --task направления без лида hephaestus в leads — код 1 «нет лида кода», claude не звали",
          r.returncode == 1 and "нет лида кода" in r.stderr and not calls(), r.stderr)

    # слово владельца — как у wake hestia: из hq без свежей записи в owner-log/zeus.md отказ
    r = run("wake", "hermes-site", "--task", "hermes-0001", extra={"PANTHEON_ROLE": "hq"})
    check("wake --task из hq без вашего слова — код 2 «без вашего слова», claude не звали",
          r.returncode == 2 and "без вашего слова" in r.stderr and not bg(), r.stderr)
    r = run("wake", "hermes-site", "--task", "hermes-0001", extra={"PANTHEON_ROLE": "athena-shop"})
    check("wake --task из окна другой роли без вашего слова — код 2 «только по вашему слову», claude не звали",
          r.returncode == 2 and "только по вашему слову" in r.stderr and not bg(), r.stderr)
    stopped = os.path.join(state, "stopped")
    os.makedirs(stopped, exist_ok=True)
    open(os.path.join(stopped, "hermes-site"), "w").close()
    r = run("wake", "hermes-site", "--task", "hermes-0001")
    os.remove(os.path.join(stopped, "hermes-site"))
    check("wake --task: направление остановлено вами — код 1, claude не звали",
          r.returncode == 1 and "остановлено вами" in r.stderr and not bg(), r.stderr)
    os.rename(os.path.join(agents_dir, "hephaestus-site.md"), os.path.join(tmp, "lead.md"))
    r = run("wake", "hermes-site", "--task", "hermes-0001")
    os.rename(os.path.join(tmp, "lead.md"), os.path.join(agents_dir, "hephaestus-site.md"))
    check("wake --task: роли hephaestus-site.md нет — код 1 «pantheon roles build»",
          r.returncode == 1 and "pantheon roles build" in r.stderr and not bg(), r.stderr)

    r = run("wake", "hermes-site", "--task", "hermes-0001", "--dry-run")
    check("wake --task --dry-run: печатает запуск лида, claude --bg не звали",
          r.returncode == 0 and "--agent hephaestus-site --name hephaestus-site" in r.stdout and not bg(), r.stdout)
    word()
    r = run("wake", "hermes-site", "--task", "hermes-0001", extra={"PANTHEON_ROLE": "hq"})
    b = bg()
    lr = json.load(open(lrun)) if os.path.exists(lrun) else {}
    win = json.load(open(os.path.join(state, "settings", "hermes-site.json")))
    coord_like = dict(win, env=dict(win.get("env") or {}, PANTHEON_ORIGIN="zeus", PANTHEON_SESSION="hephaestus-site",
                                    PANTHEON_ROLE="domain-coordinator"))
    check("wake --task из hq со словом: claude --bg --agent hephaestus-site --name hephaestus-site --settings окно "
          "запуска, папка — папка координатора, /goal по поручению с id задачи",
          r.returncode == 0 and len(b) == 1
          and b[0]["argv"][:6] == ["--bg", "--agent", "hephaestus-site", "--name", "hephaestus-site", "--settings"]
          and b[0]["argv"][6] == lrun and b[0]["cwd"] == os.path.join(tmp, "projects", "site")
          and b[0]["argv"][7].startswith("/goal ") and "pantheon task show hermes-0001" in b[0]["argv"][7]
          and "Другие задачи и пункты эпика в эту цель не входят" in b[0]["argv"][7],
          (r.returncode, r.stderr[-300:], b))
    check("окно лида равно окну координатора: settings/hermes-site.json + PANTHEON_ROLE=domain-coordinator, "
          "PANTHEON_SESSION=hephaestus-site, PANTHEON_ORIGIN=zeus — песочница и правила те же",
          lr == coord_like and lr.get("sandbox") == win.get("sandbox") and lr.get("sandbox"),
          json.dumps(lr.get("env")))
    r = run("wake", "hermes-site", "--task", "hermes-0001")
    check("wake --task, когда окно лида уже работает, — код 1, второй claude --bg не звали",
          r.returncode == 1 and len(bg()) == 1, r.stderr)

    # pantheon wake (все): уснувшего координатора выключенного направления не поднимает
    open(agents_file, "w").write(json.dumps([{"id": "c1", "name": "hermes-site", "state": "failed",
                                              "sessionId": "5a1a1a1a-0001", "cwd": tmp, "startedAt": 1}]))
    open(log, "w").close()
    r = run("wake")
    check("pantheon wake: упавший координатор направления, которое ведёт Пританей, с открытой задачей — не поднят",
          r.returncode == 0 and "будить некого" in r.stdout and not calls(), r.stdout + r.stderr)

    # pantheon check: открытый координатор выключенного направления, нет лида, coordinator не булево
    open(agents_file, "w").write(json.dumps([{"id": "c2", "name": "hermes-site", "state": "working", "startedAt": 2}]))
    r = run("check")
    check("check: открытый координатор у направления с coordinator = false — предупреждение с pantheon stop",
          "предупреждение · у направления hermes-site coordinator = false, а его координатор открыт (c2)" in r.stdout
          and "pantheon stop hermes-site" in r.stdout, r.stdout[-800:])
    check("check: у выключенного направления нет лида hephaestus — предупреждение; ошибки нет, код 0",
          "предупреждение · directions.toml: iris-x ведёт Пританей, но лида кода нет" in r.stdout and "ОШИБКА" not in r.stdout
          and r.returncode == 0, (r.returncode, r.stdout[-800:]))
    alerts = os.path.join(home, "alerts.md")
    r = run("check", "--quiet")
    al = open(alerts).read() if os.path.exists(alerts) else ""
    check("check --quiet: открытый координатор — тревога «координатор открыт у направления, которое ведёт Пританей»",
          "координатор открыт у направления, которое ведёт Пританей: hermes-site" in al and "предупреждение" not in r.stdout,
          al[-400:])
    open(agents_file, "w").write("[]")
    r = run("check")
    check("check: координатор не открыт — предупреждения о нём нет", "координатор открыт" not in r.stdout, r.stdout[-400:])
    open(reg_path, "w").write(REG + '[[direction]]\nname = "clio-y"\nfolders = ["~/projects/y"]\ncoordinator = "false"\n')
    r = run("check")
    check("check: coordinator = \"false\" строкой — ОШИБКА «нужно true или false», код 1",
          r.returncode == 1 and "ОШИБКА · directions.toml: у направления clio-y coordinator = 'false' — нужно true или "
          "false" in r.stdout, (r.returncode, r.stdout[-600:]))
    open(reg_path, "w").write(REG)

    # самозапуск: отметка владельца у задачи выключенного направления координатора не поднимает
    os.makedirs(os.path.join(state, "owner-log"), exist_ok=True)
    open(os.path.join(state, "autostart-since"), "w").write(f"{int(time.time()) - 3600}\n")
    with open(os.path.join(state, "owner-log", "board.jsonl"), "w") as fh:
        for tid in ("hermes-0001", "athena-0001"):
            fh.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "id": tid, "kind": "move",
                                 "dst": "В работе"}) + "\n")
    probe = ("import importlib.util, sys, time\nsys.path.insert(0, %r)\nimport pantheon as P\n"
             "spec = importlib.util.spec_from_file_location('w', %r)\nw = importlib.util.module_from_spec(spec)\n"
             "spec.loader.exec_module(w)\nw.set_core(P)\n"
             "w.autostart([], [], {'athena-shop': ['~/projects/br'], 'hermes-site': ['~/projects/site']}, time.time(),"
             " dry=True)\n") % (LIB_DIR, os.path.join(LIB_DIR, "watch.py"))
    r = subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True, timeout=120)
    check("самозапуск --dry-run: направление, которое ведёт Пританей, пропущено строкой «самозапуск не поднимает»; "
          "направление с координатором рассматривается",
          "hermes-site: ведёт Пританей (coordinator = false) — самозапуск не поднимает, задачи hermes-0001" in r.stdout
          and "hermes-site: ждёт" not in r.stdout and "hermes-site: поднял бы" not in r.stdout
          and "athena-shop:" in r.stdout, (r.returncode, r.stdout[-600:], r.stderr[-400:]))


def main():
    board_tests()
    if PY311:
        cli_tests()
    else:
        print("пропуск CLI: нет Python 3.11+")
    print(f"{sum(results)}/{len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
