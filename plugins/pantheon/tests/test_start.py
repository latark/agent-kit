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
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "pantheon.py")
HEAVY = os.path.join(ROOT, "bin", "heavy")
DEV_STOP = os.path.join(ROOT, "hooks", "dev-stop-verify.py")

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:3] == ["agents", "--json"]:
    print(open(os.environ["FAKE_AGENTS"]).read())
    sys.exit(0)
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
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
              os.path.join(home, "directions", "athena-broker", "tasks")):
        os.makedirs(d, exist_ok=True)
    open(os.path.join(bindir, "claude"), "w").write(FAKE)
    os.chmod(os.path.join(bindir, "claude"), 0o755)
    agents_file, log = os.path.join(tmp, "agents.json"), os.path.join(tmp, "claude.log")
    open(agents_file, "w").write("[]")
    open(os.path.join(home, "directions.toml"), "w").write(
        '[[direction]]\nname = "athena-broker"\nproject = "BrokerAssistant"\nfolders = ["~/projects/br"]\n'
        'leads = ["hephaestus", "apollo"]\n'
        '[[direction]]\nname = "hermes-alex"\nfolders = ["~/projects/alex"]\nleads = ["hephaestus"]\n')
    env = {"PATH": bindir + os.pathsep + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "FAKE_AGENTS": agents_file, "FAKE_LOG": log, "PANTHEON_NO_NOTIFY": "1"}

    def run(*args, stdin=None):
        return subprocess.run([sys.executable, "-I", LIB, *args], env=env, capture_output=True, text=True,
                              timeout=60, input=stdin)

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
    open(os.path.join(agents_dir, "apollo-alex.md"), "w").write("---\nname: apollo-alex\n---\nсвоя роль\n")
    open(os.path.join(agents_dir, "hephaestus-old.md"), "w").write(
        "---\nname: hephaestus-old\n---\n<!-- собрано pantheon roles build из hephaestus.tmpl — руками не править -->\n")
    r = run("domains", "build")
    hb = os.path.join(agents_dir, "hephaestus-broker.md")
    text = open(hb).read() if os.path.exists(hb) else ""
    check("roles build: лид собран из шаблона по полю leads, метка после шапки, подстановки",
          r.returncode == 0 and text.startswith("---\nname: hephaestus-broker\n")
          and "athena-broker (BrokerAssistant)" in text and "pantheon roles build" in text.split("---")[2]
          and "~/projects/br" in text and os.path.exists(os.path.join(agents_dir, "hephaestus-alex.md")))
    check("roles build: без шаблона apollo — чужой apollo-alex.md не тронут; устаревший собранный убран",
          open(os.path.join(agents_dir, "apollo-alex.md")).read().endswith("своя роль\n")
          and not os.path.exists(os.path.join(agents_dir, "apollo-broker.md"))
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
    os.remove(os.path.join(agents_dir, "argus.tmpl"))
    run("roles", "build")
    check("roles build: шаблон убран — собранная роль убрана", not os.path.exists(os.path.join(agents_dir, "argus.md")))

    # start: координатор направления
    r = run("start", "athena-broker", "закрой", "эпик", "--from", "zeus")
    c = calls()
    run_file = os.path.join(state, "settings", "run", "athena-broker.json")
    rs = json.load(open(run_file)) if os.path.exists(run_file) else {}
    check("start: claude --bg с ролью, именем, окном запуска; поручение позиционным аргументом с пометкой и /goal",
          r.returncode == 0 and len(c) == 1 and c[0]["argv"][:6] == ["--bg", "--agent", "domain-coordinator", "--name",
                                                                     "athena-broker", "--settings"]
          and c[0]["argv"][6] == run_file and c[0]["argv"][7].startswith("/goal [Пантеон: поручение от zeus] закрой эпик Цель достигнута, когда")
          and c[0]["cwd"] == os.path.join(tmp, "projects", "br"))
    check("start: окно запуска = окно направления + PANTHEON_ORIGIN и PANTHEON_SESSION; песочница на месте",
          rs.get("env", {}).get("PANTHEON_ORIGIN") == "zeus" and rs["env"].get("PANTHEON_SESSION") == "athena-broker"
          and rs["sandbox"]["enabled"] and rs["worktree"] == {"baseRef": "head"}
          and "--dangerously-skip-permissions" not in json.dumps(c))
    open(agents_file, "w").write(json.dumps([{"id": "a1", "name": "athena-broker", "state": "working",
                                              "sessionId": "s1", "cwd": "/x", "startedAt": 1}]))
    r = run("start", "athena-broker")
    check("start: работающую сессию с тем же именем не дублирует", r.returncode == 1 and "уже работает" in r.stderr
          and len(calls()) == 1)
    open(agents_file, "w").write(json.dumps([{"id": "a1", "name": "athena-broker", "state": "done", "pid": 5,
                                              "sessionId": "s1", "cwd": "/x", "startedAt": 1}]))
    r = run("start", "athena-broker", "новый эпик")
    c = calls()
    check("start: прошлый эпик «done» — его сессия останавливается, новая запускается с тем же именем",
          r.returncode == 0 and c[-2]["argv"] == ["stop", "a1"] and c[-1]["argv"][4] == "athena-broker")
    open(log, "w").close()
    r = run("start", "hermes-alex")
    check("start: направление без папки на этом Mac — отказ", r.returncode == 2 and "нет папки" in r.stderr)
    r = run("start", "nope")
    check("start: нет такого направления — отказ", r.returncode == 2 and "нет направления" in r.stderr)
    r = run("start", "athena-broker", "--from", "kto")
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

    # wake (ROLE-02)
    def task(tid, status, direction="athena-broker"):
        open(os.path.join(home, "directions", direction, "tasks", tid + ".md"), "w").write(
            f"---\ntype: task\nid: {tid}\ntitle: t\nstatus: {status}\nproject: BrokerAssistant\ndirection: {direction}\n"
            + ("next: дальше\n" if status == "doing" else "") + "created: 2026-10-14\nupdated: 2026-10-14\n"
            "schema_version: 1\n---\n\n## Журнал\n")
    task("athena-0001", "doing")
    open(agents_file, "w").write(json.dumps([
        {"id": "a1", "name": "athena-broker", "state": "failed", "sessionId": "s-a1", "cwd": tmp, "startedAt": 1},
        {"id": "b1", "name": "hermes-alex", "state": "stopped", "sessionId": "s-b1", "cwd": tmp, "startedAt": 1},
        {"id": "c1", "name": "random", "state": "failed", "sessionId": "s-c1", "cwd": tmp, "startedAt": 1},
        {"id": "d1", "name": "daedalus-site", "state": "failed", "sessionId": "s-d1", "cwd": tmp, "startedAt": 1}]))
    open(log, "w").close()
    r = run("wake")
    c = calls()
    check("wake: поднимает только прерванное направление с открытой задачей (--resume <сессия> --bg «[Пантеон: …]»)",
          r.returncode == 0 and len(c) == 1 and c[0]["argv"][:3] == ["--resume", "s-a1", "--bg"]
          and c[0]["argv"][3].startswith("[Пантеон: пробуждение]"))
    open(agents_file, "w").write(json.dumps([
        {"id": "a1", "name": "athena-broker", "state": "failed", "sessionId": "s-a1", "cwd": tmp, "startedAt": 1},
        {"id": "a2", "name": "athena-broker", "state": "working", "sessionId": "s-a2", "cwd": tmp, "startedAt": 2}]))
    open(log, "w").close()
    r = run("wake")
    check("wake: сессию, продолженную новой с тем же именем, не будит", r.returncode == 0 and not calls())
    task("athena-0001", "waiting")
    open(agents_file, "w").write(json.dumps([
        {"id": "a1", "name": "athena-broker", "state": "stopped", "sessionId": "s-a1", "cwd": tmp, "startedAt": 1}]))
    r = run("wake")
    check("wake: задача «ждёт» — не будит", r.returncode == 0 and not calls() and "будить некого" in r.stdout)

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
    marks = os.path.join(tmp, "heavy-marks")
    os.makedirs(marks)
    script = f"python3 -c 'import time,os; open(os.path.join(\"{marks}\", str(time.time())), \"w\").close(); time.sleep(1.5)'"
    ps = [subprocess.Popen([sys.executable, "-I", HEAVY, "/bin/sh", "-c", script], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
    codes = [p.wait(timeout=30) for p in ps]
    starts = sorted(float(x) for x in os.listdir(marks))
    check("heavy: места созданы сборкой; две команды сразу, третья — после освобождения места",
          os.path.exists(os.path.join(locks, "heavy-cmd-1.lock")) and codes == [0, 0, 0] and len(starts) == 3
          and starts[1] - starts[0] < 1.0 and starts[2] - starts[0] >= 1.4)
    r = subprocess.run([sys.executable, "-I", HEAVY, "/bin/sh", "-c", "exit 7"], env=env, capture_output=True)
    check("heavy: код выхода команды сохраняется", r.returncode == 7)

    # dev-stop-verify (DONE-02)
    repo = os.path.join(tmp, "projects", "br", "wt")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", "-b", "epic", repo], check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty",
                    "-m", "base"], check=True)
    ev = json.dumps({"cwd": repo, "agent_id": "dev-1", "agent_type": "dev-sonnet", "hook_event_name": "SubagentStop"})

    def stop():
        return subprocess.run([sys.executable, "-I", DEV_STOP], env=env, input=ev, capture_output=True, text=True,
                              timeout=60)
    r = stop()
    check("dev-stop: правок нет — отпускает", r.returncode == 0)
    open(os.path.join(repo, ".pantheon-verify"), "w").write("# проверка\ntest -f ok.txt\n")
    r = stop()
    check("dev-stop: правка есть, проверка красная — выход 2, команда и счёт в тексте",
          r.returncode == 2 and "test -f ok.txt" in r.stderr and "1 из 3" in r.stderr)
    stop()
    stop()
    r = stop()
    check("dev-stop: после трёх возвратов отпускает со статусом «заблокировано»",
          r.returncode == 0 and "заблокировано" in r.stderr)
    open(os.path.join(repo, "ok.txt"), "w").close()
    r = stop()
    check("dev-stop: проверка зелёная — отпускает", r.returncode == 0 and not r.stderr)

    # свежая worktree разработчика: правки только в коммите своей ветки — хук их видит
    wt = os.path.join(tmp, "projects", "br", "wt-dev")
    subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "-b", "worktree-agent-1", wt], check=True)
    open(os.path.join(wt, "b.txt"), "w").close()
    subprocess.run(["git", "-C", wt, "add", "-A"], check=True)
    subprocess.run(["git", "-C", wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "dev"], check=True)
    ev = json.dumps({"cwd": wt, "agent_id": "dev-2", "agent_type": "dev-sonnet", "hook_event_name": "SubagentStop"})
    os.remove(os.path.join(wt, "ok.txt")) if os.path.exists(os.path.join(wt, "ok.txt")) else None
    open(os.path.join(wt, ".pantheon-verify"), "w").write("test -f nope.txt\n")
    subprocess.run(["git", "-C", wt, "add", "-A"], check=True)
    subprocess.run(["git", "-C", wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "v"], check=True)
    r = stop()
    check("dev-stop: свежая worktree, правки только в коммитах своей ветки — проверка идёт (красная → 2)",
          r.returncode == 2 and "nope.txt" in r.stderr)
    # очередь: оба места заняты — проверку не запускали, это не возврат
    holders = [subprocess.Popen([sys.executable, "-I", HEAVY, "/bin/sh", "-c", "sleep 8"], env=env) for _ in range(2)]
    time.sleep(1)
    env["PANTHEON_DEV_STOP_WAIT"] = "2"
    before = open(os.path.join(state, "ctx", "dev-stop", "dev-2")).read()
    r = stop()
    env.pop("PANTHEON_DEV_STOP_WAIT")
    check("dev-stop: места heavy заняты — отпускает с «проверка не запускалась», счёт возвратов не растёт",
          r.returncode == 0 and "не запускалась" in r.stderr
          and open(os.path.join(state, "ctx", "dev-stop", "dev-2")).read() == before)
    srv = subprocess.Popen([sys.executable, "-I", HEAVY, "--server", "/bin/sh", "-c", "sleep 6"], env=env)
    for h in holders:
        h.wait()
    time.sleep(1)
    r2 = subprocess.run([sys.executable, "-I", HEAVY, "--server", "/bin/sh", "-c", "true"], env=dict(env, HEAVY_WAIT_MAX="2"),
                        capture_output=True, text=True)
    r3 = subprocess.run([sys.executable, "-I", HEAVY, "/bin/sh", "-c", "true"], env=dict(env, HEAVY_WAIT_MAX="2"),
                        capture_output=True, text=True)
    srv.wait()
    check("heavy --server: второй сервер ждёт (75 по пределу), обычная команда при этом идёт",
          r2.returncode == 75 and "сервер уже запущен" in r2.stderr and r3.returncode == 0)

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
