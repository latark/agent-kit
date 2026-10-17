#!/usr/bin/env python3
"""Тесты команд запуска шага 1.2: pantheon start, wake, roles build, approve; обёртка heavy; Stop-хук разработчика.

Запуск: python3 -I plugins/pantheon/tests/test_start.py  (код выхода 0 — все прошли)
claude подменён скриптом в PATH: `claude agents --json --all` отдаёт список из FAKE_AGENTS, остальные вызовы пишет
в FAKE_LOG (argv и папку запуска). Строки карты: SEC-26, COMM-10, ROLE-02, ROLE-15, DONE-02, DONE-11, MEM-03.
"""
import json
import os
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
_ROOT = tempfile.mkdtemp(prefix="start-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "pantheon.py")
HEAVY = os.path.join(ROOT, "bin", "heavy")
DEV_STOP = os.path.join(ROOT, "hooks", "dev-stop-verify.py")

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
af, seq = os.environ["FAKE_AGENTS"], os.environ.get("FAKE_SEQ") or ""
def pending():
    try:
        return json.load(open(seq))
    except (OSError, ValueError):
        return []
def save(p, data):
    with open(p + ".tmp", "w") as fh:
        json.dump(data, fh)
    os.replace(p + ".tmp", p)
if os.environ.get("FAKE_ALL"):  # все вызовы за файл: в конце — ни одного --resume без --settings
    with open(os.environ["FAKE_ALL"], "a") as fh:
        fh.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")
if sys.argv[1:3] == ["agents", "--json"]:
    if os.environ.get("FAKE_RM"):  # окно пропадает между проверкой pantheon start и записью файла запуска
        try:
            os.remove(os.environ["FAKE_RM"])
        except OSError:
            pass
    steps = pending()  # сценарий по шагам: каждый вызов claude agents берёт следующий список, последний остаётся
    if steps:
        save(af, steps[0])
        save(seq, steps[1:])
    print(open(af).read())
    sys.exit(0)
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
args = sys.argv[1:]
if args[:1] == ["respawn"] and os.environ.get("FAKE_RESPAWN_RC"):
    sys.exit(int(os.environ["FAKE_RESPAWN_RC"]))
if not pending():  # без сценария: stop делает сессию stopped, --bg --name добавляет новую (имя — FAKE_BG_NAME или своё)
    try:
        agents = json.load(open(af))
    except (OSError, ValueError):
        agents = []
    if isinstance(agents, list) and args[:1] == ["stop"]:
        for a in agents:
            if a.get("id") == args[1]:
                a["state"] = "stopped"
        save(af, agents)
    elif isinstance(agents, list) and "--bg" in args and "--name" in args and not os.environ.get("FAKE_BG_SKIP"):
        name = os.environ.get("FAKE_BG_NAME") or args[args.index("--name") + 1]
        agents.append({"id": "n" + os.urandom(3).hex(), "name": name, "state": "working", "kind": "background"})
        save(af, agents)
'''


def main():
    results = []

    def check(name, cond):
        results.append(bool(cond))
        print(("ok   " if cond else "FAIL ") + name)

    tmp = os.path.realpath(tempfile.mkdtemp(prefix="start-test-"))
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    bindir = os.path.join(tmp, "bin")
    for d in (home, bindir, os.path.join(tmp, "projects", "br"), os.path.join(tmp, ".claude", "agents"),
              os.path.join(home, "directions", "athena-shop", "tasks")):
        os.makedirs(d, exist_ok=True)
    open(os.path.join(bindir, "claude"), "w").write(FAKE)
    os.chmod(os.path.join(bindir, "claude"), 0o755)
    agents_file, log = os.path.join(tmp, "agents.json"), os.path.join(tmp, "claude.log")
    open(agents_file, "w").write("[]")
    open(os.path.join(home, "directions.toml"), "w").write(
        '[[direction]]\nname = "athena-shop"\nproject = "ExampleApp"\nfolders = ["~/projects/br"]\n'
        'leads = ["hephaestus", "apollo"]\npnpm_store = "~/projects/br/.pnpm-store"\n'
        '[[direction]]\nname = "hermes-site"\nfolders = ["~/projects/site"]\nleads = ["hephaestus"]\n'
        'pnpm_store = "~/elsewhere/.pnpm-store"\n')
    env = {"PATH": bindir + os.pathsep + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "FAKE_AGENTS": agents_file, "FAKE_LOG": log, "PANTHEON_NO_NOTIFY": "1",
           "FAKE_SEQ": os.path.join(tmp, "agents-seq.json"), "PANTHEON_STOP_WAIT": "3", "PANTHEON_STOP_POLL": "0.02",
           "PANTHEON_STOP_SETTLE": "0.5", "PANTHEON_NAME_WAIT": "1", "FAKE_ALL": os.path.join(tmp, "claude-all.log"),
           # здесь проверяется личный слой ролей: общий слой плагина пуст (оба слоя вместе — test_roles.py)
           "PANTHEON_PLUGIN_ROLES": os.path.join(tmp, "plugin-roles-empty")}

    def run(*args, stdin=None, extra=None, tty=False):
        if not tty:
            return subprocess.run([PY311, "-I", LIB, *args], env=dict(env, **(extra or {})),
                                  capture_output=True, text=True, timeout=60, input=stdin)
        # pantheon start zeus идёт только из терминала; псевдотерминалов в песочнице нет — stdin подменён на «терминал»
        boot = ("import runpy, sys\nclass T:\n    def isatty(self):\n        return True\n"
                f"sys.stdin = T()\nsys.argv = [{LIB!r}] + {list(args)!r}\nrunpy.run_path({LIB!r}, run_name='__main__')\n")
        return subprocess.run([PY311, "-I", "-c", boot], env=dict(env, **(extra or {})), capture_output=True,
                              text=True, timeout=60)

    def calls():
        return [json.loads(x) for x in open(log)] if os.path.exists(log) else []

    agents_dir = os.path.join(tmp, ".claude", "agents")
    open(os.path.join(agents_dir, "hephaestus.tmpl"), "w").write(
        "---\nname: hephaestus-{{short}}\ndescription: Лид разработки направления {{direction}} ({{project}})\n"
        "model: opus\n---\n\nТы — лид направления {{direction}}, папки: {{folders}}.\n\n{{> report}}\n")
    os.makedirs(os.path.join(agents_dir, "_parts"))
    open(os.path.join(agents_dir, "_parts", "report.part"), "w").write("## Отчёт\n\nСтатус: готово\n")
    open(os.path.join(agents_dir, "argus.tmpl"), "w").write("---\nname: argus\n---\n\nРевьюер.\n{{> report}}\n")
    open(os.path.join(agents_dir, "iris.tmpl"), "w").write("---\nname: iris\n---\n{{> nope}}\n")
    open(os.path.join(agents_dir, "tg-reader.md"), "w").write("---\nname: tg-reader\n---\nчужая\n")
    open(os.path.join(agents_dir, "apollo-site.md"), "w").write("---\nname: apollo-site\n---\nсвоя роль\n")
    open(os.path.join(agents_dir, "hephaestus-old.md"), "w").write(
        "---\nname: hephaestus-old\n---\n<!-- собрано pantheon roles build из hephaestus.tmpl — руками не править -->\n")
    br = os.path.join(tmp, "projects", "br")
    for sub, store in (("app", "/elsewhere/pnpm/store/v3"), ("ok", os.path.join(br, ".pnpm-store", "v3"))):
        os.makedirs(os.path.join(br, sub, "node_modules"))
        open(os.path.join(br, sub, "node_modules", ".modules.yaml"), "w").write(f"layoutVersion: 5\nstoreDir: {store}\n")
    os.makedirs(os.path.join(br, "fifo", "node_modules"))
    os.mkfifo(os.path.join(br, "fifo", "node_modules", ".modules.yaml"))  # роль подложила FIFO: тик не должен повиснуть
    os.symlink("/etc", os.path.join(br, "link"))
    r = run("domains", "build")
    alerts = open(os.path.join(home, "alerts.md")).read() if os.path.exists(os.path.join(home, "alerts.md")) else ""
    check("domains build: node_modules с чужим хранилищем — тревога с командой; со своим — молчит",
          "br/app/node_modules собраны с хранилищем /elsewhere/pnpm/store/v3" in alerts and "CI=true pnpm install" in alerts
          and "br/ok/node_modules" not in alerts)
    win = lambda n: json.load(open(os.path.join(state, "settings", n + ".json")))
    check("domains build: pnpm_store внутри папок направления — npm_config_store_dir окна; вне папок — нет",
          win("athena-shop")["env"].get("npm_config_store_dir") == os.path.realpath(os.path.join(tmp, "projects", "br"))
          + "/.pnpm-store" and "npm_config_store_dir" not in win("workshop")["env"]
          and "npm_config_store_dir" not in win("hermes-site")["env"])
    hb = os.path.join(agents_dir, "hephaestus-shop.md")
    text = open(hb).read() if os.path.exists(hb) else ""
    check("roles build: лид собран из шаблона по полю leads, метка после шапки, подстановки",
          r.returncode == 0 and text.startswith("---\nname: hephaestus-shop\n")
          and "athena-shop (ExampleApp)" in text and "pantheon roles build" in text.split("---")[2]
          and "~/projects/br" in text and os.path.exists(os.path.join(agents_dir, "hephaestus-site.md")))
    check("roles build: без шаблона apollo — чужой apollo-site.md не тронут; устаревший собранный убран",
          open(os.path.join(agents_dir, "apollo-site.md")).read().endswith("своя роль\n")
          and not os.path.exists(os.path.join(agents_dir, "apollo-shop.md"))
          and not os.path.exists(os.path.join(agents_dir, "hephaestus-old.md")))
    argus = open(os.path.join(agents_dir, "argus.md")).read() if os.path.exists(os.path.join(agents_dir, "argus.md")) else ""
    check("roles build: обычная роль из шаблона, общая часть подставлена и в роль, и в лида",
          argus.startswith("---\nname: argus\n---\n<!-- собрано") and "Статус: готово" in argus and "Статус: готово" in text)
    al = open(os.path.join(home, "alerts.md")).read() if os.path.exists(os.path.join(home, "alerts.md")) else ""
    check("roles build: шаблон с неизвестной частью не собран, тревога; чужой tg-reader.md не тронут",
          not os.path.exists(os.path.join(agents_dir, "iris.md")) and "нет части nope" in al
          and open(os.path.join(agents_dir, "tg-reader.md")).read().endswith("чужая\n"))
    r = run("roles", "build")
    check("roles build: повтор без изменений", r.returncode == 0 and "без изменений" in r.stdout)
    # реестр правит штаб из песочницы: перевод строки в project не должен дописать в шапку лида хук
    reg = open(os.path.join(home, "directions.toml")).read()
    open(os.path.join(home, "directions.toml"), "w").write(reg + (
        '[[direction]]\nname = "eris-evil"\nproject = "X)\\nhooks:\\n  Stop:\\n    - hooks:\\n'
        '        - {type: command, command: touch /tmp/pwned}\\nx: (y"\nfolders = ["~/projects/e"]\n'
        'leads = ["hephaestus"]\n'
        '[[direction]]\nname = "eris-dir"\nproject = "E"\nfolders = ["~/p\\n  - x"]\nleads = ["hephaestus"]\n'))
    r = run("roles", "build")
    check("roles build: project или folders с переводом строки — лид не собран, тревога, остальные целы",
          not os.path.exists(os.path.join(agents_dir, "hephaestus-evil.md"))
          and not os.path.exists(os.path.join(agents_dir, "hephaestus-dir.md"))
          and "не по образцу" in r.stderr and os.path.exists(hb))
    open(os.path.join(home, "directions.toml"), "w").write(reg)
    os.remove(os.path.join(agents_dir, "argus.tmpl"))
    run("roles", "build")
    check("roles build: шаблон убран — собранная роль убрана", not os.path.exists(os.path.join(agents_dir, "argus.md")))

    # roles build --out (metis-0097): проба в чужую папку, живые роли не трогает
    def snap(d):
        return {f: open(os.path.join(d, f), encoding="utf-8").read() for f in sorted(os.listdir(d))
                if os.path.isfile(os.path.join(d, f))}
    psrc, pout = os.path.join(tmp, "probe-src"), os.path.join(tmp, "probe-out")
    os.makedirs(os.path.join(psrc, "_parts"))
    os.makedirs(pout)
    open(os.path.join(psrc, "_parts", "report.part"), "w").write("## Отчёт\n\nСтатус: проба\n")
    open(os.path.join(psrc, "argus.tmpl"), "w").write("---\nname: argus\n---\n\nПробный ревьюер.\n{{> report}}\n")
    open(os.path.join(pout, "gone.md"), "w").write("---\nname: gone\n---\n<!-- собрано pantheon roles build из gone.tmpl — x -->\n")
    open(os.path.join(pout, "mine.md"), "w").write("---\nname: mine\n---\nчужая\n")
    before = snap(agents_dir)
    r = run("roles", "build", "--out", pout, "--src", psrc)
    got = snap(pout)
    check("roles build --out: роли собраны из --src в --out, устаревшая собранная убрана, чужая цела",
          r.returncode == 0 and "Пробный ревьюер" in got.get("argus.md", "") and "Статус: проба" in got["argus.md"]
          and "gone.md" not in got and got.get("mine.md", "").endswith("чужая\n"))
    check("roles build --out: ~/.claude/agents до и после — тот же состав и содержимое", snap(agents_dir) == before)
    open(os.path.join(psrc, "iris.tmpl"), "w").write("---\nname: iris\n---\n{{> nope}}\n")
    al0 = open(os.path.join(home, "alerts.md")).read()
    r = run("roles", "build", "--out", pout, "--src", psrc)
    check("roles build --out: ошибка шаблона — в stderr, сигнала владельцу нет",
          "нет части nope" in r.stderr and open(os.path.join(home, "alerts.md")).read() == al0)
    before = snap(agents_dir)
    for bad in (agents_dir, os.path.join(agents_dir, "sub"), os.path.join(tmp, ".claude", "x", "..", "agents")):
        r = run("roles", "build", "--out", bad)
        check(f"roles build --out {os.path.relpath(bad, tmp)}: внутри ~/.claude/agents — код 2",
              r.returncode == 2 and snap(agents_dir) == before and not os.path.exists(os.path.join(agents_dir, "sub")))
    link = os.path.join(tmp, "agents-link")
    os.symlink(agents_dir, link)
    r = run("roles", "build", "--out", link)
    check("roles build --out: симлинк на ~/.claude/agents — код 2", r.returncode == 2 and snap(agents_dir) == before)
    r = run("roles", "build", "--src", psrc)
    check("roles build --src без --out — код 2", r.returncode == 2 and snap(agents_dir) == before)

    # start: координатор направления
    r = run("start", "athena-shop", "закрой", "эпик", "--from", "zeus")
    c = calls()
    run_file = os.path.join(state, "settings", "run", "athena-shop.json")
    rs = json.load(open(run_file)) if os.path.exists(run_file) else {}
    check("start: claude --bg с ролью, именем, окном запуска; поручение позиционным аргументом с пометкой и /goal",
          r.returncode == 0 and len(c) == 1 and c[0]["argv"][:6] == ["--bg", "--agent", "domain-coordinator", "--name",
                                                                     "athena-shop", "--settings"]
          and c[0]["argv"][6] == run_file and c[0]["argv"][7].startswith("/goal [Пантеон: поручение от zeus] закрой эпик Цель достигнута, когда")
          and "критерий «готово» этого поручения" in c[0]["argv"][7] and "чек-листа эпика" not in c[0]["argv"][7]
          and c[0]["cwd"] == os.path.join(tmp, "projects", "br"))
    check("start: окно запуска = окно направления + PANTHEON_ORIGIN и PANTHEON_SESSION; песочница на месте",
          rs.get("env", {}).get("PANTHEON_ORIGIN") == "zeus" and rs["env"].get("PANTHEON_SESSION") == "athena-shop"
          and rs["sandbox"]["enabled"] and rs["worktree"] == {"baseRef": "head"}
          and "--dangerously-skip-permissions" not in json.dumps(c))
    open(agents_file, "w").write(json.dumps([{"id": "a1", "name": "athena-shop", "state": "working",
                                              "sessionId": "s1", "cwd": "/x", "startedAt": 1}]))
    r = run("start", "athena-shop")
    check("start: работающую сессию с тем же именем не дублирует", r.returncode == 1 and "уже работает" in r.stderr
          and len(calls()) == 1)
    open(agents_file, "w").write(json.dumps([{"id": "a9", "name": "athena-shop-glimmering-valiant", "state": "blocked",
                                              "sessionId": "s9", "cwd": "/x", "startedAt": 1}]))
    r = run("start", "athena-shop")
    check("start: копию под другим именем («имя-два-слова») тоже видит — не дублирует",
          r.returncode == 1 and "athena-shop-glimmering-valiant a9" in r.stderr and len(calls()) == 1)
    open(agents_file, "w").write(json.dumps([{"name": "athena-shop (2)", "kind": "interactive", "pid": 77}]))
    r = run("start", "athena-shop", "--restart")
    check("start --restart: копия открыта во вкладке — не трогает, просит перейти в неё",
          r.returncode == 1 and "во вкладке" in r.stderr and len(calls()) == 1)
    open(agents_file, "w").write(json.dumps([{"id": "a8", "name": "athena-shop", "state": "blocked", "sessionId": "s8",
                                              "cwd": "/x", "startedAt": 1},
                                             {"id": "z1", "name": "athena-shop-x", "state": "working"}]))
    r = run("start", "athena-shop", "заново", "--restart")
    c = calls()
    check("start --restart: живую копию останавливает и запускает новую; чужое имя «athena-shop-x» не трогает",
          r.returncode == 0 and c[-2]["argv"] == ["stop", "a8"] and c[-1]["argv"][4] == "athena-shop"
          and ["stop", "z1"] not in [x["argv"] for x in c])
    open(agents_file, "w").write(json.dumps([{"id": "a1", "name": "athena-shop", "state": "done", "pid": 5,
                                              "sessionId": "s1", "cwd": "/x", "startedAt": 1}]))
    r = run("start", "athena-shop", "новый эпик")
    c = calls()
    check("start: прошлый эпик «done» — его сессия останавливается, новая запускается с тем же именем",
          r.returncode == 0 and c[-2]["argv"] == ["stop", "a1"] and c[-1]["argv"][4] == "athena-shop")
    alerts_md = os.path.join(home, "alerts.md")
    said = lambda: open(alerts_md).read().count("без вашего слова") if os.path.exists(alerts_md) else 0
    check("start --from zeus без вашего слова в окне Зевса — тревога (лазейка видна)", said() == 1)
    os.makedirs(os.path.join(state, "owner-log"), exist_ok=True)
    with open(os.path.join(state, "owner-log", "zeus.md"), "w") as fh:
        fh.write(time.strftime("## %Y-%m-%d %H:%M:%S\nзапусти athena\n\n"))
    open(agents_file, "w").write("[]")
    run("start", "athena-shop", "проверка", "--from", "zeus")
    check("start --from zeus сразу после вашего слова — без тревоги", said() == 1)
    open(agents_file, "w").write("[]")
    r = run("start", "athena-shop")
    c = calls()
    check("start: без поручения — продолжать эпик, цель по чек-листу эпика в STATUS.md",
          r.returncode == 0 and "STATUS.md" in c[-1]["argv"][7] and "чек-листа эпика" in c[-1]["argv"][7])
    open(log, "w").close()
    r = run("start", "hermes-site")
    check("start: направление без папки на этом Mac — отказ", r.returncode == 2 and "нет папки" in r.stderr)
    r = run("start", "nope")
    check("start: нет такого направления — отказ", r.returncode == 2 and "нет направления" in r.stderr)
    r = run("start", "athena-shop", "--from", "kto")
    check("start: --from только zeus|tick|owner", r.returncode == 2)
    os.makedirs(os.path.join(state, "stopped"), exist_ok=True)
    open(os.path.join(state, "stopped", "daedalus-site"), "w").close()
    r = run("start", "workshop", "site")
    check("start: остановленную вами не запускает", r.returncode == 1 and "остановлена вами" in r.stderr)
    r = run("start", "workshop", "../etc")
    check("start workshop: имя задачи по образцу", r.returncode == 2)
    r = run("start", "workshop", "avito-scan", "--from", "tick")
    c = calls()[-1]
    check("start workshop: daedalus-<задача> в ~/projects/workshop/<задача>, поручение по умолчанию",
          r.returncode == 0 and c["argv"][2:5] == ["workshop", "--name", "daedalus-avito-scan"]
          and c["cwd"] == os.path.join(tmp, "projects", "workshop", "avito-scan")
          and c["argv"][-1].startswith("[Пантеон: поручение от tick] Прочитай ~/ai/pantheon/workshop/avito-scan.md"))
    r = run("start", "zeus", "--dry-run")
    check("start zeus: интерактивная сессия hq с окном hq.json (без --bg)",
          r.returncode == 0 and "--agent hq --name zeus --settings" in r.stdout and "hq.json" in r.stdout
          and "--bg" not in r.stdout)
    r = run("start", "zeus")
    check("start zeus: без терминала не запускается", r.returncode == 2)

    # metis-0041: после claude stop имя освобождается не сразу, копия может ожить, новая — получить чужое имя
    seq_file, start_log = env["FAKE_SEQ"], os.path.join(state, "logs", "start.log")

    def scenario(*steps):  # каждый вызов claude agents берёт следующий шаг; последний остаётся
        json.dump(list(steps), open(seq_file, "w"))

    def slog():
        return open(start_log).read() if os.path.exists(start_log) else ""

    def argvs():
        return [c["argv"] for c in calls()]

    def bg_started(name):
        return any(a[:1] == ["--bg"] and name in a for a in argvs())

    def ab(state_, aid="a8", sid="s8", name="athena-shop"):
        return {"id": aid, "name": name, "state": state_, "sessionId": sid, "cwd": "/x", "startedAt": 1}

    open(log, "w").close()
    scenario()
    open(agents_file, "w").write(json.dumps([ab("stopped", "a1", "s1")]))
    n0 = slog().count("name-ok")
    r = run("start", "athena-shop", "дальше")
    check("live_copies: state stopped (после claude stop) — не живая: обычный start без --restart запускает, "
          "её не трогает; имя новой проверено",
          r.returncode == 0 and ["stop", "a1"] not in argvs() and bg_started("athena-shop")
          and slog().count("name-ok") == n0 + 1)

    open(log, "w").close()
    scenario([ab("working")], [ab("working")], [ab("working")], [ab("stopped")])
    r = run("start", "athena-shop", "заново", "--restart")
    a = argvs()
    check("start --restart: после stop ждёт, пока копия отпустит имя (working → stopped), и только потом запускает",
          r.returncode == 0 and a[0] == ["stop", "a8"] and len(a) == 2 and bg_started("athena-shop")
          and "stop-wait-free\tathena-shop" in slog())

    open(log, "w").close()
    scenario([ab("working")], [ab("working")])
    r = run("start", "athena-shop", "заново", "--restart", extra={"PANTHEON_STOP_WAIT": "0.5"})
    check("start --restart: копия не отпустила имя за предел — отказ, код 1, новая не запущена, строка в start.log",
          r.returncode == 1 and argvs() == [["stop", "a8"]] and "не отпустили имя" in r.stderr
          and "athena-shop a8 (working)" in r.stderr and "stop-wait-timeout\tathena-shop" in slog())

    # имя держит живой процесс реестра ~/.claude/sessions, хотя claude agents уже пишет stopped
    sessions = os.path.join(tmp, ".claude", "sessions")
    os.makedirs(sessions, exist_ok=True)
    held = os.path.join(sessions, f"{os.getpid()}.json")
    json.dump({"pid": os.getpid(), "sessionId": "s8", "name": "athena-shop", "kind": "bg"}, open(held, "w"))
    dead = subprocess.Popen(["true"])
    dead.wait()
    json.dump({"pid": dead.pid, "sessionId": "s7", "name": "athena-shop", "kind": "bg"},
              open(os.path.join(sessions, f"{dead.pid}.json"), "w"))
    open(log, "w").close()
    scenario()
    open(agents_file, "w").write(json.dumps([ab("working")]))
    r = run("start", "athena-shop", "заново", "--restart", extra={"PANTHEON_STOP_WAIT": "0.5"})
    check("start --restart: claude agents пишет stopped, но процесс в реестре жив и держит имя — ждёт, отказ",
          r.returncode == 1 and argvs() == [["stop", "a8"]] and f"pid {os.getpid()}" in r.stderr)
    os.remove(held)
    open(log, "w").close()
    open(agents_file, "w").write(json.dumps([ab("working")]))
    r = run("start", "athena-shop", "заново", "--restart")
    check("start --restart: запись реестра с мёртвым процессом имени не держит — запуск",
          r.returncode == 0 and argvs()[0] == ["stop", "a8"] and bg_started("athena-shop"))

    open(log, "w").close()
    scenario([ab("working")], [ab("stopped")], [ab("working")], [ab("working")], [ab("stopped")], [])
    r = run("start", "athena-shop", "заново", "--restart")
    a = argvs()
    check("start --restart: копия ожила после stop (stopped → working) — повторный stop, дождался — запуск",
          r.returncode == 0 and a[:2] == [["stop", "a8"], ["stop", "a8"]] and len(a) == 3 and bg_started("athena-shop")
          and "stop-revived\tathena-shop" in slog())

    open(log, "w").close()
    scenario([ab("working")], [ab("stopped")], [ab("blocked")], [ab("stopped")], [ab("working")])
    r = run("start", "athena-shop", "заново", "--restart")
    check("start --restart: ожила и после повторного stop — отказ, код 1, новая не запущена",
          r.returncode == 1 and argvs() == [["stop", "a8"], ["stop", "a8"]] and "ожила и после повторного" in r.stderr
          and "claude stop a8" in r.stderr and "stop-revived-again\tathena-shop\ta8" in slog())

    open(log, "w").close()
    scenario([ab("working")], [ab("stopped"), {"id": "t1", "name": "athena-shop (2)", "kind": "interactive"}])
    r = run("start", "athena-shop", "заново", "--restart")
    check("start --restart: пока ждали, появилась чужая живая копия — отказ, её не трогает",
          r.returncode == 1 and argvs() == [["stop", "a8"]] and "athena-shop (2) t1" in r.stderr)

    open(log, "w").close()
    scenario()
    open(agents_file, "w").write("[]")
    al0 = open(alerts_md).read() if os.path.exists(alerts_md) else ""
    r = run("start", "athena-shop", "дальше", extra={"FAKE_BG_NAME": "athena-shop-sparkling-cat"})
    al1 = open(alerts_md).read()[len(al0):] if os.path.exists(alerts_md) else ""
    new_id = next((x["id"] for x in json.load(open(agents_file)) if x["name"] == "athena-shop-sparkling-cat"), "?")
    check("start: новая сессия получила чужое имя («имя-два-слова») — тревога с id и что делать, код не 0, её не трогает",
          r.returncode != 0 and "чужое имя" in al1 and new_id in al1 and "athena-shop-sparkling-cat" in al1
          and "--restart" in al1 and ["stop", new_id] not in argvs() and "name-mismatch\tathena-shop" in slog())
    open(log, "w").close()
    open(agents_file, "w").write("[]")
    r = run("start", "athena-shop", "дальше", extra={"FAKE_BG_NAME": "athena-shop (2)"})
    check("start: новая сессия «имя (2)» — тоже тревога, код не 0", r.returncode != 0 and "«athena-shop (2)»" in r.stderr)
    open(agents_file, "w").write("[]")
    r = run("start", "athena-shop", "дальше")
    check("start: новая сессия со своим именем — код 0, без тревоги", r.returncode == 0 and "чужое имя" not in r.stderr)
    open(log, "w").close()
    open(agents_file, "w").write("[]")
    al0 = open(alerts_md).read() if os.path.exists(alerts_md) else ""
    r = run("start", "athena-shop", "дальше", extra={"FAKE_BG_SKIP": "1", "PANTHEON_NAME_WAIT": "0.3"})
    al1 = open(alerts_md).read()[len(al0):] if os.path.exists(alerts_md) else ""
    open(log, "w").close()
    scenario([], [], [ab("stopped", "x9", "s9", "athena-shop-old-cat"), ab("working", "n1", "s1")])
    r = run("start", "athena-shop", "дальше")
    check("start: остановленная копия с чужим именем, которой не было в списке до запуска, — не тревога, код 0",
          r.returncode == 0 and "чужое имя" not in r.stderr and "name-ok\tathena-shop" in slog())
    scenario()
    check("start: новой сессии не видно в claude agents — код 0 (это ловит дежурный), строка в start.log, без тревоги",
          r.returncode == 0 and bg_started("athena-shop") and "name-unseen\tathena-shop" in slog() and not al1)

    # Зевс: execv — имя после запуска не проверить, ждать до
    zeus = lambda s, aid="z1": {"id": aid, "name": "zeus", "state": s, "sessionId": "sz", "cwd": "/x", "startedAt": 1}
    open(log, "w").close()
    scenario([zeus("working")], [zeus("working")], [zeus("stopped")])
    r = run("start", "zeus", "--restart", tty=True)
    a = argvs()
    check("start zeus --restart: stop, ждёт освобождения имени, затем execv claude --agent hq --name zeus",
          r.returncode == 0 and a[0] == ["stop", "z1"] and len(a) == 2 and a[1][:4] == ["--agent", "hq", "--name", "zeus"]
          and "stop-wait-free\tzeus" in slog())
    open(log, "w").close()
    scenario([zeus("working")], [zeus("working")])
    r = run("start", "zeus", "--restart", tty=True, extra={"PANTHEON_STOP_WAIT": "0.5"})
    check("start zeus --restart: старый Зевс не отпустил имя — отказ без execv, код 1",
          r.returncode == 1 and argvs() == [["stop", "z1"]] and "не отпустили имя" in r.stderr)
    open(log, "w").close()
    scenario()
    open(agents_file, "w").write(json.dumps([{"name": "zeus", "kind": "interactive", "pid": 77}]))
    r = run("start", "zeus", "--restart", tty=True)
    check("start zeus --restart: имя держит вкладка терминала — отказ с copies_message, ничего не останавливает",
          r.returncode == 1 and not argvs() and "во вкладке" in r.stderr)
    open(agents_file, "w").write("[]")

    # wake (ROLE-02)
    def task(tid, status, direction="athena-shop"):
        open(os.path.join(home, "directions", direction, "tasks", tid + ".md"), "w").write(
            f"---\ntype: task\nid: {tid}\ntitle: t\nstatus: {status}\nproject: ExampleApp\ndirection: {direction}\n"
            + ("next: дальше\n" if status == "doing" else "") + "created: 2026-10-14\nupdated: 2026-10-14\n"
            "schema_version: 1\n---\n\n## Журнал\n")
    task("athena-0001", "doing")
    open(agents_file, "w").write(json.dumps([
        {"id": "a1", "name": "athena-shop", "state": "failed", "sessionId": "5a1a1a1a-0001", "cwd": tmp, "startedAt": 1},
        {"id": "b1", "name": "hermes-site", "state": "stopped", "sessionId": "s-b1", "cwd": tmp, "startedAt": 1},
        {"id": "c1", "name": "random", "state": "failed", "sessionId": "s-c1", "cwd": tmp, "startedAt": 1},
        {"id": "d1", "name": "daedalus-site", "state": "failed", "sessionId": "s-d1", "cwd": tmp, "startedAt": 1}]))
    open(log, "w").close()
    r = run("wake")
    c = calls()
    check("wake: поднимает только прерванное направление с открытой задачей (--resume <сессия> --bg «[Пантеон: …]»)",
          r.returncode == 0 and len(c) == 1 and c[0]["argv"] == ["respawn", "a1"])
    open(agents_file, "w").write(json.dumps([
        {"id": "a1", "name": "athena-shop", "state": "failed", "sessionId": "5a1a1a1a-0001", "cwd": tmp, "startedAt": 1},
        {"id": "a2", "name": "athena-shop", "state": "working", "sessionId": "s-a2", "cwd": tmp, "startedAt": 2}]))
    open(log, "w").close()
    r = run("wake")
    check("wake: сессию, продолженную новой с тем же именем, не будит", r.returncode == 0 and not calls())
    task("athena-0001", "waiting")
    open(agents_file, "w").write(json.dumps([
        {"id": "a1", "name": "athena-shop", "state": "stopped", "sessionId": "5a1a1a1a-0001", "cwd": tmp, "startedAt": 1}]))
    r = run("wake")
    check("wake: задача «ждёт» — не будит", r.returncode == 0 and not calls() and "будить некого" in r.stdout)

    # metis-0147 п. 2: контекст > 100 тыс. и простой > 60 мин — свежая сессия с файла состояния, иначе respawn
    task("athena-0001", "doing")
    tr_dir = os.path.join(tmp, ".claude", "projects", "".join(ch if ch.isalnum() else "-" for ch in tmp))
    os.makedirs(tr_dir, exist_ok=True)
    tr = os.path.join(tr_dir, "5a1a1a1a-0001.jsonl")

    def transcript(tokens, idle_min):
        with open(tr, "w") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "шаг"}}) + "\n")
            fh.write(json.dumps({"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "usage": {
                "input_tokens": 10, "cache_read_input_tokens": tokens - 10, "cache_creation_input_tokens": 0}}}) + "\n")
        t = time.time() - idle_min * 60
        os.utime(tr, (t, t))

    def wake_case(tokens, idle_min, *args, extra=None):
        transcript(tokens, idle_min)
        open(agents_file, "w").write(json.dumps([{"id": "a1", "name": "athena-shop", "state": "stopped",
                                                  "sessionId": "5a1a1a1a-0001", "cwd": tmp, "startedAt": 1}]))
        open(log, "w").close()
        return run("wake", *args, extra=extra), calls()

    r, c = wake_case(120_000, 120)
    bg = [x["argv"] for x in c if "--bg" in x["argv"]]
    check("wake: контекст 120 тыс. и простой 2 ч — свежая сессия (claude --bg --agent --name --settings окно запуска, "
          "«[Пантеон: пробуждение] … Прочитай STATUS.md»), не respawn",
          r.returncode == 0 and not [x for x in c if x["argv"][:1] in (["respawn"], ["--resume"])] and len(bg) == 1
          and bg[0][:6] == ["--bg", "--agent", "domain-coordinator", "--name", "athena-shop", "--settings"]
          and bg[0][6] == os.path.join(state, "settings", "run", "athena-shop.json")
          and "[Пантеон: пробуждение]" in bg[0][7] and "Прочитай ~/ai/pantheon/directions/athena-shop/STATUS.md" in bg[0][7]
          and "свежей сессией (контекст 120 тыс., простой 120 мин)" in r.stdout)
    r, c = wake_case(120_000, 10)
    check("wake: контекст 120 тыс., простой 10 мин — как раньше: respawn", [x["argv"] for x in c] == [["respawn", "a1"]])
    r, c = wake_case(90_000, 120)
    check("wake: контекст 90 тыс., простой 2 ч — как раньше: respawn", [x["argv"] for x in c] == [["respawn", "a1"]])
    r, c = wake_case(120_000, 120, "--dry-run")
    check("wake --dry-run: говорит, что поднимет свежей сессией и какой файл прочитает, ничего не запускает",
          r.returncode == 0 and not c and "будет поднята: athena-shop" in r.stdout
          and "свежей сессией (контекст 120 тыс., простой 120 мин), прочитает "
              "~/ai/pantheon/directions/athena-shop/STATUS.md" in r.stdout)
    r, c = wake_case(90_000, 120, extra={"FAKE_RESPAWN_RC": "1"})
    res = [x["argv"] for x in c if "--resume" in x["argv"]]
    check("wake: respawn не вышел — --resume с --settings файла запуска окна",
          [x["argv"] for x in c][:1] == [["respawn", "a1"]] and len(res) == 1
          and res[0][res[0].index("--settings") + 1] == os.path.join(state, "settings", "run", "athena-shop.json"))

    # ревью argus PR #32: окно не собрано из-за allow проекта (metis-0137) — сессию не поднимает ни wake (respawn
    # взял бы прежние флаги с прежним файлом запуска, --resume ушёл бы без --settings), ни свежий старт
    run_file = os.path.join(state, "settings", "run", "athena-shop.json")
    win_file = os.path.join(state, "settings", "athena-shop.json")
    bad_allow = os.path.join(br, ".claude", "settings.json")
    os.makedirs(os.path.dirname(bad_allow), exist_ok=True)
    open(run_file, "w").write(json.dumps(win("athena-shop")))  # как после прежнего pantheon start
    open(bad_allow, "w").write(json.dumps({"permissions": {"allow": ["Bash(gh *)"]}}))
    r = run("domains", "build")
    check("domains build: allow проекта с gh pr merge — убраны и окно, и файл запуска settings/run/<имя>.json",
          not os.path.exists(win_file) and not os.path.exists(run_file) and "окно не собрано" in r.stderr)
    al0 = open(alerts_md).read() if os.path.exists(alerts_md) else ""
    for tokens, idle, how in ((90_000, 10, "resume"), (90_000, 10, "resume"), (120_000, 120, "fresh")):
        r, c = wake_case(tokens, idle, extra={"FAKE_RESPAWN_RC": "1"})
        check(f"wake без окна ({how}): ни respawn, ни --resume, ни --bg, ни stop; файл запуска не появился; "
              f"строка {how}-skip в start.log",
              r.returncode == 0 and not c and not os.path.exists(run_file)
              and f"{how}-skip\tathena-shop\twake\tнет окна: окно не собрано" in slog())
    al1 = open(alerts_md).read()[len(al0):] if os.path.exists(alerts_md) else ""
    check("wake без окна: одна тревога на причину — называет файл и правило; без тревоги «не поднялась (код …)»",
          al1.count("athena-shop: не поднимаю (wake)") == 1 and "Bash(gh *)" in al1
          and "без песочницы окна" in al1 and "не поднялась" not in al1)

    # живое окно: Claude Code перечитывает настройки на ходу — allow, добавленный в работающем окне, уже действует.
    # Тик останавливает живую сессию; ручная сборка — нет (её зовут и тесты с настоящим claude в PATH)
    live_a1 = [{"id": "a1", "name": "athena-shop", "state": "working", "sessionId": "5a1a1a1a-0001", "cwd": tmp,
                "startedAt": 1}]
    stops = lambda: [x["argv"] for x in calls() if x["argv"][:1] == ["stop"]]  # noqa: E731
    open(agents_file, "w").write(json.dumps(live_a1))
    open(log, "w").close()
    run("domains", "build")
    check("ручной domains build с проблемой allow — живую сессию не останавливает", not stops())
    future = time.time() + 30  # --if-changed пересобирает, когда проектные настройки новее прошлой сборки
    os.utime(bad_allow, (future, future))
    al0 = open(alerts_md).read() if os.path.exists(alerts_md) else ""
    r = run("domains", "build", "--if-changed")
    al1 = open(alerts_md).read()[len(al0):] if os.path.exists(alerts_md) else ""
    check("тик (domains build --if-changed): живая сессия направления с проблемой allow остановлена claude stop, "
          "тревога называет её и правило",
          r.returncode == 0 and stops() == [["stop", "a1"]] and "stop-project-allow\tathena-shop" in slog()
          and "athena-shop: остановлена работающая сессия (a1)" in al1 and "Bash(gh *)" in al1)
    open(agents_file, "w").write(json.dumps(live_a1))
    open(log, "w").close()
    r = run("check", "--quiet")
    check("тик (check --quiet): окно убрала ручная сборка, а сессия работает — остановлена", stops() == [["stop", "a1"]])
    os.remove(bad_allow)
    run("domains", "build")
    open(agents_file, "w").write(json.dumps(live_a1))
    open(log, "w").close()
    run("check", "--quiet")
    run("domains", "build", "--if-changed")
    check("allow убран — окно и файл запуска снова собираются, живую сессию тик не трогает",
          os.path.exists(win_file) and not stops())
    r, c = wake_case(90_000, 10)
    check("allow убран — wake снова поднимает respawn", [x["argv"] for x in c] == [["respawn", "a1"]])

    # ревью argus PR #32 (c6eb7e1): allow со старым mtime (cp -p, rsync -a, tar) сборка --if-changed не видит —
    # правило перепроверяют каждый подъём сессии и check --quiet
    run("domains", "build")
    open(run_file, "w").write(json.dumps(win("athena-shop")))  # как после прежнего pantheon start
    open(bad_allow, "w").write(json.dumps({"permissions": {"allow": ["Bash(gh *)"]}}))
    old = time.time() - 86400
    os.utime(bad_allow, (old, old))
    open(log, "w").close()
    run("domains", "build", "--if-changed")
    check("allow со старым mtime: domains build --if-changed окно не пересобирает — оба файла окна на месте",
          os.path.exists(win_file) and os.path.exists(run_file) and not calls())
    saved = {f: open(f).read() for f in (win_file, run_file)}

    def restore():  # каждый путь подъёма — с собранным окном, как его оставила сборка
        for f, body in saved.items():
            open(f, "w").write(body)

    al0 = open(alerts_md).read() if os.path.exists(alerts_md) else ""
    for tokens, idle, rc_, how in ((90_000, 10, None, "resume"), (90_000, 10, "1", "resume"), (120_000, 120, None, "fresh")):
        restore()
        n0 = slog().count(f"{how}-skip\tathena-shop\twake\tнет окна: окно не собрано")
        r, c = wake_case(tokens, idle, extra={"FAKE_RESPAWN_RC": rc_} if rc_ else None)
        check(f"allow со старым mtime, wake ({how}{', respawn с ошибкой' if rc_ else ''}): ни respawn, ни --resume, "
              f"ни --bg; оба файла окна убраны; строка {how}-skip",
              r.returncode == 0 and not c and not os.path.exists(win_file) and not os.path.exists(run_file)
              and slog().count(f"{how}-skip\tathena-shop\twake\tнет окна: окно не собрано") == n0 + 1)
    al1 = open(alerts_md).read()[len(al0):] if os.path.exists(alerts_md) else ""
    check("allow со старым mtime, wake: одна тревога «не поднимаю» с файлом и правилом",
          al1.count("athena-shop: не поднимаю (wake)") == 1 and "Bash(gh *)" in al1 and "не поднялась" not in al1)
    restore()
    open(agents_file, "w").write("[]")
    open(log, "w").close()
    r = run("start", "athena-shop", "дальше")
    check("allow со старым mtime: pantheon start — код 1, не запускает, оба файла окна убраны",
          r.returncode == 1 and not calls() and "окно не собрано" in r.stderr and "Bash(gh *)" in r.stderr
          and not os.path.exists(win_file) and not os.path.exists(run_file))
    restore()
    run("check", "--quiet")
    check("allow со старым mtime: check --quiet убирает оба файла окна — следующий wake её не поднимет",
          not os.path.exists(win_file) and not os.path.exists(run_file))
    os.remove(bad_allow)
    run("domains", "build")
    # respawn и --resume поднимают сессию в её cwd из claude agents: папка не папка запуска и пускает gh pr merge —
    # не поднимаем; окно остаётся (start и свежий старт идут из папки запуска)
    sub = os.path.join(br, "wt-cwd")
    os.makedirs(os.path.join(sub, ".claude"), exist_ok=True)
    open(os.path.join(sub, ".claude", "settings.local.json"), "w").write(
        json.dumps({"permissions": {"allow": ["Bash(gh pr *)"]}}))
    transcript(90_000, 10)
    open(agents_file, "w").write(json.dumps([{"id": "a1", "name": "athena-shop", "state": "stopped",
                                              "sessionId": "5a1a1a1a-0001", "cwd": sub, "startedAt": 1}]))
    open(log, "w").close()
    al0 = open(alerts_md).read() if os.path.exists(alerts_md) else ""
    r = run("wake", extra={"FAKE_RESPAWN_RC": "1"})
    al1 = open(alerts_md).read()[len(al0):] if os.path.exists(alerts_md) else ""
    check("wake: папка сессии (cwd) не папка запуска и её allow пускает gh pr merge — ни respawn, ни --resume; "
          "resume-skip, тревога; окно цело",
          r.returncode == 0 and not calls() and "resume-skip\tathena-shop\twake\tпапка сессии" in slog()
          and "сессия работала в" in al1 and "Bash(gh pr *)" in al1 and "не поднялась" not in al1
          and os.path.exists(win_file))
    _shutil.rmtree(sub)
    r, c = wake_case(90_000, 10)
    check("allow убран отовсюду — wake снова поднимает respawn", [x["argv"] for x in c] == [["respawn", "a1"]])

    # pantheon start: окно пропало между проверкой и записью файла запуска — прежний файл запуска не берётся
    open(agents_file, "w").write("[]")
    open(log, "w").close()
    r = run("start", "athena-shop", "дальше", extra={"FAKE_RM": win_file})
    check("start: окно пропало после проверки — не запускает, код 1", r.returncode == 1 and not bg_started("athena-shop")
          and "нет окна" in r.stderr)
    run("domains", "build")
    # мастерская: та же защита — без workshop.json daedalus-* не поднимается (daedalus-site остановлена вами выше)
    open(os.path.join(home, "directions", "athena-shop", "tasks", "athena-0002.md"), "w").write(
        "---\ntype: task\nid: athena-0002\ntitle: t\nstatus: doing\nproject: ExampleApp\ndirection: athena-shop\n"
        "owner: daedalus-shop\nnext: дальше\ncreated: 2026-10-14\nupdated: 2026-10-14\nschema_version: 1\n---\n\n## Журнал\n")
    os.remove(os.path.join(state, "settings", "workshop.json"))
    open(agents_file, "w").write(json.dumps([{"id": "d1", "name": "daedalus-shop", "state": "failed",
                                              "sessionId": "5d1d1d1d-0001", "cwd": tmp, "startedAt": 1}]))
    open(log, "w").close()
    r = run("wake", extra={"FAKE_RESPAWN_RC": "1"})
    check("wake мастерской без окна workshop.json: ни respawn, ни --resume; тревога «не поднимаю»",
          r.returncode == 0 and not calls() and "daedalus-shop: не поднимаю (wake)" in open(alerts_md).read())
    os.remove(os.path.join(home, "directions", "athena-shop", "tasks", "athena-0002.md"))
    run("domains", "build")
    os.remove(tr)
    open(agents_file, "w").write("[]")

    # approve (DONE-11)
    r = run("approve", "add", "--site", "avito.ru", "--allow", "поднимать объявления", "--limits", "не чаще раза в день")
    ap = os.path.join(tmp, ".claude", "pantheon", "approvals.toml")
    body = open(ap).read() if os.path.exists(ap) else ""
    check("approve add: запись в ~/.claude/pantheon/approvals.toml, читается как TOML",
          r.returncode == 0 and 'site = "avito.ru"' in body and "1. avito.ru: поднимать объявления" in r.stdout)
    r = run("approve", "add", "--site", "x", "--allow", "оплата заказа")
    check("approve: деньги заранее не разрешаются", r.returncode == 2 and "x" not in open(ap).read().split("avito")[0][-5:])
    r = run("approve", "remove", "1")
    check("approve remove: убрано", r.returncode == 0 and "avito" not in open(ap).read() and "нет" in r.stdout)

    # heavy (MEM-03): два места, третья команда ждёт
    locks = os.path.join(state, "locks")
    journal = os.path.join(tmp, "heavy-journal")
    # каждая команда дописывает в журнал «s» при старте и «e» перед выходом; порядок строк — порядок событий, а не время
    script = (f"python3 -c 'import time; open(\"{journal}\", \"a\").write(\"s\\n\"); time.sleep(1.5); "
              f"open(\"{journal}\", \"a\").write(\"e\\n\")'")
    ps = [subprocess.Popen([sys.executable, "-I", HEAVY, "/bin/sh", "-c", script], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
    codes = [p.wait(timeout=30) for p in ps]
    events = open(journal).read().split()
    running, peak = 0, 0
    for ev in events:
        running += 1 if ev == "s" else -1
        peak = max(peak, running)
    check("heavy: места созданы сборкой; больше двух команд разом не идёт, третья стартует после первого выхода",
          os.path.exists(os.path.join(locks, "heavy-cmd-1.lock")) and codes == [0, 0, 0] and sorted(events) == ["e"] * 3 + ["s"] * 3
          and peak == 2 and events.index("e") < [i for i, x in enumerate(events) if x == "s"][2])
    r = subprocess.run([sys.executable, "-I", HEAVY, "/bin/sh", "-c", "exit 7"], env=env, capture_output=True)
    check("heavy: код выхода команды сохраняется", r.returncode == 7)

    # dev-stop-verify (DONE-02): код проекта не запускает, смотрит транскрипт разработчика
    repo = os.path.join(tmp, "projects", "br", "wt")
    os.makedirs(repo)
    git = lambda *a, cwd=repo: subprocess.run(["git", "-C", cwd, "-c", "user.email=t@t", "-c", "user.name=t", *a],
                                              check=True, capture_output=True)
    git("init", "-q", "-b", "epic")
    open(os.path.join(repo, ".pantheon-verify"), "w").write("# проверка\npnpm test\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    wt = os.path.join(tmp, "projects", "br", "wt-dev")
    git("worktree", "add", "-q", "-b", "worktree-agent-1", wt)
    tr = os.path.join(tmp, "agent.jsonl")
    pwned = os.path.join(tmp, "pwned")

    def transcript(*steps):
        with open(tr, "w") as fh:
            for i, (name, inp, err) in enumerate(steps):
                fh.write(json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}}) + "\n")
                fh.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": f"t{i}", "is_error": err, "content": "x"}]}}) + "\n")

    def stop(agent="dev-1"):
        ev = json.dumps({"cwd": wt, "agent_id": agent, "agent_type": "dev-sonnet", "hook_event_name": "SubagentStop",
                         "agent_transcript_path": tr})
        return subprocess.run([sys.executable, "-I", DEV_STOP], env=env, input=ev, capture_output=True, text=True,
                              timeout=60)
    transcript()
    r = stop()
    check("dev-stop: правок нет — отпускает", r.returncode == 0)
    # разработчик меняет проверку на свою команду — хук её не запускает и берёт проверку из точки ответвления
    open(os.path.join(wt, ".pantheon-verify"), "w").write(f"touch {pwned}\n")
    open(os.path.join(wt, "a.txt"), "w").write("x")
    git("add", "-A", cwd=wt)
    git("commit", "-q", "-m", "dev", cwd=wt)
    transcript(("Write", {"file_path": "a.txt"}, False), ("Bash", {"command": f"touch {pwned}"}, False))
    r = stop()
    check("dev-stop: код проекта не запускается (подменённый .pantheon-verify — нет), прогона нет — выход 2",
          r.returncode == 2 and not os.path.exists(pwned) and "heavy pnpm test" in r.stderr and "1 из 3" in r.stderr)
    transcript(("Write", {"file_path": "a.txt"}, False), ("Bash", {"command": "heavy pnpm test"}, True))
    r = stop()
    check("dev-stop: последний прогон после правки красный — выход 2", r.returncode == 2 and "красный" in r.stderr)
    transcript(("Bash", {"command": "heavy pnpm  test"}, False), ("Edit", {"file_path": "a.txt"}, False))
    r = stop()
    check("dev-stop: зелёный прогон был, но до правки — выход 2", r.returncode == 2 and "не прогнал" in r.stderr)
    r = stop()
    check("dev-stop: после трёх возвратов отпускает со статусом «заблокировано»",
          r.returncode == 0 and "заблокировано" in r.stderr)
    transcript(("Edit", {"file_path": "a.txt"}, False), ("Bash", {"command": "cd x && heavy pnpm test"}, False),
               ("Bash", {"command": "git status"}, False))
    r = stop("dev-2")
    check("dev-stop: зелёный прогон после последней правки — отпускает", r.returncode == 0 and not r.stderr)
    transcript(("Bash", {"command": "heavy pnpm test"}, False), ("Bash", {"command": "sed -i '' s/a/b/ a.txt"}, False))
    r = stop("dev-3")
    check("dev-stop: правка через Bash после прогона — снова нужен прогон", r.returncode == 2)

    # heavy --server: один долгий процесс, второе место — сборкам
    srv = subprocess.Popen([sys.executable, "-I", HEAVY, "--server", "/bin/sh", "-c", "sleep 4"], env=env)
    time.sleep(1)
    r2 = subprocess.run([sys.executable, "-I", HEAVY, "--server", "/bin/sh", "-c", "true"], env=dict(env, HEAVY_WAIT_MAX="2"),
                        capture_output=True, text=True)
    r3 = subprocess.run([sys.executable, "-I", HEAVY, "/bin/sh", "-c", "true"], env=dict(env, HEAVY_WAIT_MAX="2"),
                        capture_output=True, text=True)
    srv.wait()
    check("heavy --server: второй сервер ждёт (75 по пределу), обычная команда при этом идёт",
          r2.returncode == 75 and "сервер уже запущен" in r2.stderr and r3.returncode == 0)

    # sync-answers: ответ на доске по карантину ~/.claude — тик запускает sync.sh сам
    cl = os.path.join(tmp, ".claude")
    mark = os.path.join(tmp, "sync-ran")
    open(os.path.join(cl, "sync.sh"), "w").write(f"#!/bin/sh\ntouch {mark}\n")
    os.chmod(os.path.join(cl, "sync.sh"), 0o755)
    r = run("sync-answers")
    check("sync-answers: держания нет — sync.sh не запускается", r.returncode == 0 and not os.path.exists(mark))
    open(os.path.join(cl, ".sync-held"), "w").write("hash=abc\ntask=metis-0099\nfiles=1\n")
    os.makedirs(os.path.join(state, "owner-log"), exist_ok=True)
    olog = os.path.join(state, "owner-log", "board.jsonl")
    open(olog, "w").write(json.dumps({"kind": "answer", "id": "metis-0099", "answer": "Пока держать"}) + "\n")
    r = run("sync-answers")
    check("sync-answers: «пока держать» — не запускает", r.returncode == 0 and not os.path.exists(mark))
    open(olog, "a").write(json.dumps({"kind": "answer", "id": "metis-0098", "answer": "Отправить на другие Mac"}) + "\n")
    run("sync-answers")
    check("sync-answers: ответ по другой задаче — не запускает", not os.path.exists(mark))
    open(olog, "a").write(json.dumps({"kind": "answer", "id": "metis-0099", "answer": "Отправить на другие Mac"}) + "\n")
    r = run("sync-answers")
    check("sync-answers: «отправить» по своей задаче — sync.sh запущен", r.returncode == 0 and os.path.exists(mark))

    # status: один экран, только читает
    open(agents_file, "w").write(json.dumps([
        {"id": "a1", "kind": "background", "state": "blocked", "name": "athena-shop", "waitingFor": "разрешение Bash"},
        {"id": "a2", "kind": "background", "state": "working", "name": "hermes-site"},
        {"kind": "interactive", "state": None, "name": "user-1"}]))
    r = run("status")
    check("status: итог сверху, ждущая сессия названа, терминальные — отдельно, код 1 при проблемах",
          r.returncode == 1 and r.stdout.startswith("Пантеон · ") and "athena-shop — разрешение Bash" in r.stdout
          and "открыты в терминале: 1" in r.stdout and "фоновые работают: 1" in r.stdout and "Тик" in r.stdout)

    every = [json.loads(x) for x in open(env["FAKE_ALL"])] if os.path.exists(env["FAKE_ALL"]) else []
    resumes = [a for a in every if "--resume" in a]
    check("за весь файл: --resume был и ни разу без --settings", resumes and all("--settings" in a for a in resumes))

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
