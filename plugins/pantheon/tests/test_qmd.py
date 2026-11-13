#!/usr/bin/env python3
"""Тесты шага 1.5: службы планировщика (SCHED-05), конфиг qmd из qmd.toml (QMD-01…03), хук qmd-query (QMD-04).

Запуск: python3 -I plugins/pantheon/tests/test_qmd.py  (код выхода 0 — все прошли)
Всё во временных папках: launchd не трогается (PANTHEON_DRYRUN — решения пишутся в dryrun.log), qmd подменён
скриптом, который записывает свои аргументы.
"""
import json
import os
import stat
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
_ROOT = tempfile.mkdtemp(prefix="qmd-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(HERE, "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
CTX = os.path.join(HERE, "hooks", "ctx.py")
T0 = 1_792_000_000
OK, FAIL = [], []

SCHED = """primary_host = "mac-b"
[[job]]
name = "view"
command = "pantheon view --quiet"
every = "tick"
[[service]]
name = "qmd"
description = "сервер MCP qmd"
command = "pantheon qmd serve"
hosts = "all"
[[service]]
name = "bad-claude"
command = "claude -p --agent clio \\"x\\""
[[service]]
name = "only-b"
command = "pantheon qmd serve"
hosts = "primary"
[[service]]
name = "view"
command = "pantheon qmd serve"
"""


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    if not cond:
        print(f"НЕ ПРОШЁЛ: {name} {detail}")


def setup(tmp, schedule=SCHED, qmd_toml=None):
    home = os.path.join(tmp, "home")
    pan, state = os.path.join(home, "ai", "pantheon"), os.path.join(tmp, "state")
    os.makedirs(pan, exist_ok=True)
    open(os.path.join(pan, "schedule.toml"), "w").write(schedule)
    if qmd_toml is not None:
        open(os.path.join(pan, "qmd.toml"), "w").write(qmd_toml)
    return home, pan, state


def run(home, pan, state, *args, extra=None, host="mac-a"):
    env = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pan, "PANTHEON_STATE": state,
           "PANTHEON_NOW": str(T0), "PANTHEON_HOST": host, "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_WAKE": str(T0 - 7200), "PANTHEON_FAKE_AC": "1", "PANTHEON_FAKE_IDLE": "1200",
           "PANTHEON_ALERTS_IN_DRYRUN": "1"}
    env.update(extra or {})
    return subprocess.run([PY311, "-I", RUN_PY, *args], env=env, capture_output=True, text=True, timeout=60)


def dry(state):
    """Решения о службах (svc-…) из dryrun.log — задачи тика туда тоже пишут, их отбрасываем."""
    p = os.path.join(state, "dryrun.log")
    lines = [ln.split(None, 1)[1].strip() for ln in open(p)] if os.path.exists(p) else []
    return [ln for ln in lines if ln.startswith("svc-")]


def plist(home, name):
    return os.path.join(home, "Library", "LaunchAgents", f"pantheon.svc.{name}.plist")


def test_services():
    with tempfile.TemporaryDirectory() as tmp:
        home, pan, state = setup(tmp)
        r = run(home, pan, state, "tick")
        log = dry(state)
        check("SCHED-05: служба поднимается тиком", "svc-bootstrap qmd" in log, f"{log} {r.stderr}")
        check("SCHED-05: plist службы с service-run и KeepAlive",
              os.path.exists(plist(home, "qmd")) and "<string>service-run</string><string>qmd</string>"
              in open(plist(home, "qmd")).read() and "<key>KeepAlive</key><true/>" in open(plist(home, "qmd")).read())
        check("служба с claude -p не запускается", "svc-bootstrap bad-claude" not in log)
        check("служба hosts=primary — не на чужом Mac", "svc-bootstrap only-b" not in log)
        alerts = open(os.path.join(pan, "alerts.md")).read() if os.path.exists(os.path.join(pan, "alerts.md")) else ""
        check("служба с именем задачи — отброшена с тревогой", "svc-bootstrap view" not in log and "'view'" in alerts,
              alerts)
        run(home, pan, state, "tick")
        check("второй тик не перезапускает идущую службу", dry(state).count("svc-bootstrap qmd") == 1, str(dry(state)))
        r = run(home, pan, state, "jobs", "pause", "qmd")
        check("pantheon jobs pause <служба> снимает её сразу",
              r.returncode == 0 and dry(state)[-1] == "svc-bootout qmd" and not os.path.exists(plist(home, "qmd")),
              f"{dry(state)} {r.stderr}")
        run(home, pan, state, "tick")
        check("на паузе тик службу не поднимает", dry(state)[-1] == "svc-bootout qmd", str(dry(state)))
        out = run(home, pan, state, "jobs").stdout
        check("pantheon jobs показывает службу и паузу", "qmd" in out and "пауза" in out, out)
        run(home, pan, state, "jobs", "resume", "qmd")
        check("resume поднимает службу сразу", dry(state)[-1] == "svc-bootstrap qmd", str(dry(state)))
        r = run(home, pan, state, "jobs", "renew", "qmd")
        check("у служб нет аренды", r.returncode == 2)
        # убрали из расписания — снимается
        open(os.path.join(pan, "schedule.toml"), "w").write('primary_host = "mac-b"\n')
        run(home, pan, state, "tick")
        check("служба, убранная из расписания, снимается", dry(state)[-1] == "svc-bootout qmd"
              and not os.path.exists(plist(home, "qmd")), str(dry(state)))
        # главный Mac — поднимает only-b
        home2, pan2, state2 = setup(os.path.join(tmp, "b"))
        run(home2, pan2, state2, "tick", host="mac-b")
        check("hosts=primary — на главном Mac идёт", "svc-bootstrap only-b" in dry(state2), str(dry(state2)))
        # service-run: служба не разрешена — не исполняется (ждёт 60 с — не ждём: только проверяем отказ разбора)
        open(os.path.join(pan, "schedule.toml"), "a").write(
            '[[service]]\nname = "inst"\ncommand = "pantheon qmd install"\n')
        run(home, pan, state, "tick")
        check("служба pantheon qmd install не разрешена", "svc-bootstrap inst" not in dry(state), str(dry(state)))
        r = run(home, pan, state, "service-run", "../x")
        check("service-run: имя не по образцу — отказ", r.returncode == 2)


QMD_TOML = """port = 8199
[[collection]]
name = "notes"
path = "~/notes"
mask = "a/*.md,b/*.md"
ignore = ["drafts/**"]
context = "Заметки \\"с кавычками\\": и двоеточием"
[[collection]]
name = "gone"
path = "~/nope"
"""


def fake_qmd(tmp):
    p = os.path.join(tmp, "fakeqmd")
    open(p, "w").write("#!/bin/sh\nprintf '%s|' \"$@\" >> \"$FAKE_LOG\"; printf '\\n%s\\n%s\\n' \"$QMD_CONFIG_DIR\" "
                       "\"$PWD\" >> \"$FAKE_LOG\"\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
    return p


def test_qmd_config():
    with tempfile.TemporaryDirectory() as tmp:
        home, pan, state = setup(tmp, qmd_toml=QMD_TOML)
        os.makedirs(os.path.join(home, "notes"))
        cfgdir = os.path.join(home, ".config", "qmd")
        os.makedirs(cfgdir)
        yml = os.path.join(cfgdir, "index.yml")
        open(yml, "w").write('collections:\n  x:\n    path: /tmp\n    pattern: "**/*.md"\n    update: "touch /tmp/pwned"\n')
        flog = os.path.join(tmp, "fake.log")
        extra = {"PANTHEON_QMD_BIN": fake_qmd(tmp), "FAKE_LOG": flog}
        r = run(home, pan, state, "qmd", "update", extra=extra)
        text = open(yml).read()
        check("qmd update: подменённый index.yml с update: перезаписан", "update:" not in text.replace(
            "Ключа update", "") and "pwned" not in text, text)
        check("index.yml: коллекция с маской, ignore и контекстом",
              '"notes":' in text and 'pattern: "a/*.md,b/*.md"' in text and '- "drafts/**"' in text
              and '"/": "Заметки \\"с кавычками\\": и двоеточием"' in text, text)
        check("index.yml: коллекция без папки на этом Mac пропущена", '"gone"' not in text and "gone" in r.stdout,
              r.stdout)
        check("index.yml: права 0600", stat.S_IMODE(os.stat(yml).st_mode) == 0o600)
        lines = open(flog).read().splitlines()
        check("qmd update: вызван fake qmd с update, QMD_CONFIG_DIR и своей папкой",
              lines[:1] == ["--index|index|update|"] and lines[1] == cfgdir and lines[2].endswith("/qmd"), str(lines))
        # личное исключено маской или ignore — коллекция принимается
        os.makedirs(os.path.join(home, "ai", "knowledge", "Inbox"), exist_ok=True)
        os.makedirs(os.path.join(home, ".claude", "pantheon"), exist_ok=True)
        open(os.path.join(home, ".claude", "pantheon", "policy.toml"), "w").write(
            '[private]\npaths = ["~/ai/pantheon/.git/git-crypt"]\n')
        for ok_toml in ('[[collection]]\nname = "k"\npath = "~/ai/knowledge"\nmask = "Inbox/research-*.md"\n',
                        '[[collection]]\nname = "k"\npath = "~/ai/knowledge"\nignore = ["me/**"]\n',
                        '[[collection]]\nname = "k"\npath = "~/ai/knowledge"\nmask = "Inbox/*.md"\n'
                        '[[collection]]\nname = "p"\npath = "~/ai/pantheon"\n'):
            open(os.path.join(pan, "qmd.toml"), "w").write(ok_toml)
            r = run(home, pan, state, "qmd", "config", extra=extra)
            check("коллекция над личным с исключением me/ — принята", r.returncode == 0, r.stderr)
        open(os.path.join(pan, "qmd.toml"), "w").write(QMD_TOML)
        # ссылка вместо index.yml — не пишем через неё
        os.remove(yml)
        target = os.path.join(tmp, "elsewhere.yml")
        open(target, "w").write("x")
        os.symlink(target, yml)
        run(home, pan, state, "qmd", "config", extra=extra)
        check("index.yml-ссылка заменяется файлом, цель не тронута",
              not os.path.islink(yml) and open(target).read() == "x")
        # сервер: только 127.0.0.1 и порт из qmd.toml
        open(flog, "w").close()
        run(home, pan, state, "qmd", "serve", extra=extra)
        first = open(flog).read().splitlines()[0]
        check("qmd serve: mcp --http на 127.0.0.1 и порт из qmd.toml",
              first == "--index|index|mcp|--http|--port|8199|--host|127.0.0.1|", first)
        # плохие qmd.toml
        for bad, why in (('[[collection]]\nname = "Bad Name"\npath = "~/notes"\n', "имя"),
                         ('[[collection]]\nname = "x"\npath = "/etc"\n', "путь вне дома"),
                         ('[[collection]]\nname = "x"\npath = "~/notes"\ncontext = "a\\nb"\n', "перевод строки"),
                         ('port = 80\n', "порт"),
                         ('[[collection]]\nname = "k"\npath = "~/ai/knowledge"\n', "накрывает личное me/"),
                         ('[[collection]]\nname = "k"\npath = "~/ai/knowledge"\nmask = "**/*.md,Inbox/*.md"\n',
                          "маска с ** накрывает me/"),
                         ('[[collection]]\nname = "k"\npath = "~/ai/knowledge/me/fin"\n', "коллекция внутри me/"),
                         ('[[collection]]\nname = "k"\npath = "~/ai/knowledge"\nignore = ["me/"]\n',
                          "ignore «me/» fast-glob не исключает"),
                         ('[[collection]]\nname = "k"\npath = "~/ai/knowledge"\nmask = "ME/**/*.md"\n',
                          "маска ME/ без учёта регистра"),
                         ('[[collection]]\nname = "k"\npath = "~/ai/knowledge/ME"\n', "путь ME = me/"),
                         ('[[collection]]\nname = "k"\npath = "~/AI/knowledge"\n', "~/AI/knowledge накрывает me/"),
                         ('[[collection]]\nname = "k"\npath = "~/ai/knowledge"\nignore = [" me/**"]\n',
                          "ignore с пробелом"),
                         ('[[collection]]\nname = "k"\npath = "~/ai/knowledge"\nmask = "@(me)/**/*.md"\n',
                          "расширенный глоб @(me)"),
                         ('[[collection]]\nname = "x"\npath = "~/.claude"\n', "скрытая папка ~/.claude"),
                         ('[[collection]]\nname = "x"\npath = "~/notes/.git"\n', "скрытая часть пути"),
                         ('[[collection]]\nname = "x"\npath = "~/Library/Mobile Documents"\n', "~/Library"),
                         ('[[collection]]\nname = "x"\npath = "~/notes"\nmask = "**/*.jsonl"\n', "маска не .md"),
                         ('[[collection]]\nname = "x"\npath = "~/notes"\nmask = "**/*.{md,txt}"\n',
                          "маска со скобками"),
                         ('[[collection]]\nname = "x"\npath = "~/notes"\nmask = "a/*.md,**/*"\n', "вторая маска — всё")):
            open(os.path.join(pan, "qmd.toml"), "w").write(bad)
            r = run(home, pan, state, "qmd", "update", extra=extra)
            check(f"qmd.toml с ошибкой ({why}) — отказ без запуска qmd", r.returncode == 1 and "qmd.toml" in r.stderr,
                  r.stderr)


# закрытые штабу коллекции — только из [hq] policy.toml (metis-0182); в домашней папке тестов — две
HQ_HOME = tempfile.mkdtemp(prefix="qmd-hq-")
os.makedirs(os.path.join(HQ_HOME, ".claude", "pantheon"))
with open(os.path.join(HQ_HOME, ".claude", "pantheon", "policy.toml"), "w") as _fh:
    _fh.write('[hq]\nclosed_dirs = []\nclosed_collections = ["corpus", "legal"]\n')


def hq_open(denied):
    """Штабу пропуск — нет отказа."""
    return not denied


def hook(ti, tool="mcp__qmd__query", role=None, window=None, raw=False, home=None):
    ev = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti}
    if role:
        ev["agent_type"] = role
    env = {"PATH": os.environ["PATH"], "HOME": home or HQ_HOME}
    if window:
        env["PANTHEON_ROLE"] = window
    r = subprocess.run([sys.executable, CTX, "qmd-query"], input=json.dumps(ev),
        capture_output=True, text=True, timeout=30, env=env)
    return r.stdout if raw else "deny" in r.stdout


def test_hook():
    vec = [{"type": "vec", "query": "задаток"}]
    check("QMD-04: полный режим (query) — отказ", hook({"query": "задаток"}))
    check("QMD-04: без rerank=false — отказ", hook({"searches": vec, "collections": ["legal"]}))
    check("QMD-04: без коллекции — отказ", hook({"searches": vec, "rerank": False}))
    check("QMD-04: hyde — отказ", hook({"searches": [{"type": "hyde", "query": "x"}], "collections": ["legal"],
                                         "rerank": False}))
    check("QMD-04: vec в коллекции без доранжирования — пропуск",
          not hook({"searches": vec, "collections": ["legal"], "rerank": False}))
    check("QMD-04: lex по коду — пропуск",
          not hook({"searches": [{"type": "lex", "query": "И-12"}], "collections": ["corpus"], "rerank": False}))
    q = {"searches": vec, "collections": ["corpus"], "rerank": False}
    check("штабу корпус закрыт: query по corpus — отказ", hook(q, role="hq"))
    check("координатору корпус открыт", not hook(q, role="domain-coordinator"))
    check("штабу другие коллекции открыты", hq_open(hook({**q, "collections": ["pantheon"]}, role="hq")))
    g = "mcp__qmd__get"
    check("штаб: get qmd://corpus/… — отказ", hook({"file": "qmd://corpus/lec.md"}, g, "hq"))
    check("штаб: get по docid — отказ", hook({"file": "#abc123"}, g, "hq"))
    check("штаб: get с .. — отказ", hook({"file": "qmd://pantheon/../corpus/x.md"}, g, "hq"))
    check("штаб: get относительным путём — отказ", hook({"file": "data/lec.md"}, g, "hq"))
    check("штаб: get qmd://pantheon/… — пропуск", hq_open(hook({"file": "qmd://pantheon/board.md:10"}, g, "hq")))
    m = "mcp__qmd__multi_get"
    check("штаб: multi_get со списком, где есть corpus — отказ",
          hook({"pattern": "qmd://pantheon/a.md,qmd://corpus/b.md"}, m, "hq"))
    check("штаб: multi_get глоб {corpus,…} — отказ", hook({"pattern": "qmd://{corpus,pantheon}/*.md"}, m, "hq"))
    # P0-1 (metis-0060): штабу закрыта и коллекция legal — право и выгрузки Telegram-каналов, только Фемиде
    check("штаб (окно hq): query по legal — отказ", hook({**q, "collections": ["legal"]}, window="hq"))
    check("штаб: query по legal и pantheon — отказ", hook({**q, "collections": ["pantheon", " legal"]}, role="hq"))
    out = hook({**q, "collections": ["legal"]}, window="hq", raw=True)
    check("штаб: отказ по legal — нейтральный текст: координатору направления поручением, без имён",
          "координатору направления" in out and "поручением" in out and "legal" in out
          and "themis" not in out and "Telegram" not in out, out)
    check("штаб (окно hq): query по pantheon — пропуск",
          hq_open(hook({**q, "collections": ["pantheon"]}, window="hq")))
    check("штаб: get qmd://legal/… — отказ", hook({"file": "qmd://legal/x.md"}, g, window="hq"))
    check("штаб: multi_get qmd://legal/… — отказ", hook({"pattern": "qmd://legal/2026-09*.md"}, m, "hq"))
    check("координатор: query по legal — пропуск", not hook({**q, "collections": ["legal"]}, role="domain-coordinator",
                                                             window="domain-coordinator"))
    check("координатор: get qmd://legal/… — пропуск", not hook({"file": "qmd://legal/x.md"}, g, "domain-coordinator"))
    check("координатор: get по docid — пропуск", not hook({"file": "#abc123"}, g, "domain-coordinator"))
    check("штаб: get с %2e%2e — отказ", hook({"file": "qmd://pantheon/%2e%2e/corpus/x.md"}, g, "hq"))
    check("штаб: get с обратной косой — отказ", hook({"file": "qmd://pantheon\\..\\corpus/x.md"}, g, "hq"))
    check("аргументы не объект — отказ", hook(["x"]))
    corpus_q = {"searches": vec, "collections": ["corpus"], "rerank": False}
    check("помощник Зевса (Explore в окне штаба): corpus — отказ", hook(corpus_q, role="Explore", window="hq"))
    check("Explore вне окна штаба: corpus — пропуск", not hook(corpus_q, role="Explore"))
    check("помощник Зевса: get qmd://corpus/… — отказ",
          hook({"file": "qmd://corpus/x.md"}, g, "general-purpose", window="hq"))
    rr = "ReadMcpResourceTool"
    check("штаб: ресурс qmd://corpus/… — отказ", hook({"server": "qmd", "uri": "qmd://corpus/x.md"}, rr, "hq"))
    check("штаб: ресурс с %2e%2e — отказ",
          hook({"server": "qmd", "uri": "qmd://pantheon/%2e%2e/corpus/x.md"}, rr, "hq"))
    check("штаб: любой ресурс qmd — отказ (поиск по окончанию пути)",
          hook({"server": "qmd", "uri": "qmd://pantheon/a.md"}, rr, "hq"))
    check("штаб: ресурс другого сервера — пропуск", not hook({"server": "x", "uri": "qmd://corpus/a.md"}, rr, "hq"))
    check("координатор: ресурс qmd://corpus/… — пропуск",
          not hook({"server": "qmd", "uri": "qmd://corpus/x.md"}, rr, "domain-coordinator"))

    test_hook_policy(vec)
    test_hook_projects(vec)


def test_hook_projects(vec):
    """metis-0778 (строка 8 модели угроз 0771): коллекция qmd, чья папка внутри проекта направления или содержит его,
    штабу закрыта сама, без [hq].closed_collections. Открыты ~/ai (pantheon, knowledge), metis-pantheon и
    направления, которые ведёт Пританей (coordinator = false). Битый qmd.toml — штабу qmd закрыт целиком."""
    h = tempfile.mkdtemp(prefix="qmd-proj-")
    proj = os.path.join(h, "projects")
    for d in ("broker", "broker/docs", "agent-kit", "solo"):
        os.makedirs(os.path.join(proj, d))
    for d in (".claude/pantheon", "ai/pantheon", "ai/knowledge", ".local/state/pantheon", ".hidden/proj"):
        os.makedirs(os.path.join(h, d), exist_ok=True)
    with open(os.path.join(h, ".claude", "pantheon", "policy.toml"), "w") as fh:
        fh.write('[hq]\nclosed_dirs = []\nclosed_collections = []\n')
    with open(os.path.join(h, ".local", "state", "pantheon", "domains.json"), "w") as fh:
        json.dump({"domains": {"athena-proja": [os.path.join(proj, "broker")],
                               "metis-pantheon": [os.path.join(proj, "agent-kit")],
                               "mnemo-brain": [os.path.join(h, "ai", "knowledge")],
                               "solo-led": [os.path.join(proj, "solo")],
                               "hidden-dir": [os.path.join(h, ".hidden", "proj")]}}, fh)
    with open(os.path.join(h, "ai", "pantheon", "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-proja"\n[[direction]]\nname = "solo-led"\ncoordinator = false\n')
    colls = {"pantheon": "~/ai/pantheon", "knowledge": "~/ai/knowledge", "broker": "~/projects/broker",
             "brokerdocs": "~/projects/broker/docs", "wide": "~/projects", "agentkit": "~/ai/agent-kit",
             "solo": "~/projects/solo", "hidden": "~/.hidden/proj"}
    qmd_toml = os.path.join(h, "ai", "pantheon", "qmd.toml")
    with open(qmd_toml, "w") as fh:
        fh.write("".join(f'[[collection]]\nname = "{n}"\npath = "{p}"\n' for n, p in colls.items()))
    q = {"searches": vec, "rerank": False}
    g, m = "mcp__qmd__get", "mcp__qmd__multi_get"
    out = hook({**q, "collections": ["broker"]}, window="hq", home=h, raw=True)
    check("0778: штаб — query по коллекции проекта направления — отказ с причиной",
          '"deny"' in out and "broker" in out and "координатору направления" in out, out)
    check("0778: штаб (помощник, agent_type hq) — query по коллекции проекта — отказ",
          hook({**q, "collections": ["broker"]}, role="hq", home=h))
    check("0778: штаб — get и multi_get qmd://broker/… — отказ",
          hook({"file": "qmd://broker/a.md"}, g, "hq", home=h)
          and hook({"pattern": "qmd://broker/*.md"}, m, window="hq", home=h))
    # metis-0856: отказ называет направление-хозяина и готовую команду поручения, get — тоже отказ, но с той же подсказкой
    check("0856: отказ hq по коллекции проекта называет направление и команду поручения",
          "broker — направление athena-proja" in out
          and "pantheon task new --direction athena-proja" in out and "pantheon qmd where" in out, out)
    outg = hook({"file": "qmd://broker/a.md"}, g, window="hq", home=h, raw=True)
    check("0856: get по коллекции проекта из hq — по-прежнему отказ, с подсказкой хозяина",
          '"deny"' in outg and "pantheon task new --direction athena-proja" in outg, outg)
    check("0856: коллекция шире проекта (~/projects) — хозяева-направления внутри неё названы",
          "pantheon task new --direction athena-proja" in hook({**q, "collections": ["wide"]}, window="hq", home=h,
                                                                 raw=True))
    outp = hook({**q, "collections": ["pantheon"]}, window="hq", home=h, raw=True)
    check("0856: открытая коллекция — пропуск, подсказки нет", hq_open(outp) and "task new" not in outp, outp)
    check("0778: коллекция внутри проекта — отказ", hook({**q, "collections": ["brokerdocs"]}, window="hq", home=h))
    check("0778: коллекция, содержащая проект (~/projects), — отказ",
          hook({**q, "collections": ["wide"]}, window="hq", home=h))
    for name in ("pantheon", "knowledge"):
        check(f"0778: штаб — коллекция {name} (~/ai) открыта",
              hq_open(hook({**q, "collections": [name]}, window="hq", home=h))
              and hq_open(hook({"file": f"qmd://{name}/a.md"}, g, window="hq", home=h)))
    check("0778: штаб — коллекция agent-kit (metis-pantheon) открыта",
          hq_open(hook({**q, "collections": ["agentkit"]}, window="hq", home=h)))
    check("0778: штаб — коллекция направления, которое ведёт Пританей, открыта",
          hq_open(hook({**q, "collections": ["solo"]}, window="hq", home=h)))
    check("0778: штаб — коллекция папки направления в скрытой папке (~/.claude и т. п.) не закрывается",
          hq_open(hook({**q, "collections": ["hidden"]}, window="hq", home=h)))
    check("0778: координатору коллекция проекта открыта",
          not hook({**q, "collections": ["broker"]}, role="domain-coordinator", home=h))
    with open(qmd_toml, "w") as fh:
        fh.write('[[collection]\nname = "broker"\n')
    out = hook({**q, "collections": ["pantheon"]}, window="hq", home=h, raw=True)
    check("0778: qmd.toml не TOML — штабу qmd закрыт целиком с причиной, координатору открыт",
          '"deny"' in out and "qmd.toml" in out
          and not hook({**q, "collections": ["pantheon"]}, role="domain-coordinator", home=h), out)


class _Fake:
    """Подставная служба qmd: POST /query отдаёт заготовленный ответ и запоминает тело запроса."""

    def __init__(self, results):
        import http.server
        import threading
        outer = self
        outer.body, outer.results = None, results

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                outer.body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                data = json.dumps({"results": outer.results}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def test_where():
    """metis-0856: `pantheon qmd where` — коллекция, путь, заголовок, хозяин; тела документов в выводе нет."""
    body_line, ctx_line = "СТРОКА-ИЗ-ТЕЛА-ДОКУМЕНТА-77", "КОНТЕКСТ-КОЛЛЕКЦИИ-88"
    evil = "Заголовок\x1b[31m\n\u202eс ловушкой\u200b" + "ы" * 300
    res = [
        {"docid": "#a1", "file": "qmd://site-b/docs/a%20b.md", "title": evil, "score": 0.9, "context": ctx_line,
         "line": 3, "snippet": "@@ -2 @@\n" + body_line},
        {"docid": "#a2", "file": "qmd://site-b/x.md", "title": "Обычный", "score": 0.8, "context": ctx_line,
         "line": 1, "snippet": body_line},
        {"docid": "#a3", "file": "qmd://legal/secret.md", "title": "ЗАКРЫТО-LEGAL", "snippet": body_line},
        {"docid": "#a4", "file": "qmd://pantheon/board.md", "title": "Доска", "snippet": body_line},
        {"docid": "#a5", "file": "qmd://site-b/../../etc/p.md", "title": "Обход", "snippet": body_line},
    ]
    fake = _Fake(res)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            pan, state = os.path.join(home, "ai", "pantheon"), os.path.join(tmp, "state")
            for d in (pan, state, os.path.join(home, ".claude", "pantheon"), os.path.join(home, "projects", "site-b")):
                os.makedirs(d)
            with open(os.path.join(pan, "qmd.toml"), "w") as fh:
                fh.write(f'port = {fake.port}\n[[collection]]\nname = "site-b"\npath = "~/projects/site-b"\n'
                         f'[[collection]]\nname = "legal"\npath = "~/projects/legal"\n'
                         f'[[collection]]\nname = "pantheon"\npath = "~/ai/pantheon"\n')
            with open(os.path.join(home, ".claude", "pantheon", "policy.toml"), "w") as fh:
                fh.write('[hq]\nclosed_dirs = []\nclosed_collections = ["legal"]\n')
            with open(os.path.join(state, "domains.json"), "w") as fh:
                json.dump({"domains": {"hermes-siteb": [os.path.join(home, "projects", "site-b")]}}, fh)
            r = run(home, pan, state, "qmd", "where", "где лежит задаток", "--collection", "site-b")
            out = r.stdout
            lines = out.splitlines()
            check("0856 where: код 0, строки «коллекция | путь | заголовок | хозяин»",
                  r.returncode == 0 and any(ln.startswith("site-b | docs/a b.md | ") and ln.endswith(" | hermes-siteb")
                                            for ln in lines) and "site-b | x.md | Обычный | hermes-siteb" in lines,
                  r.stdout + r.stderr)
            check("0856 where: строки из тела (snippet) и context в выводе нет",
                  body_line not in out and ctx_line not in out and "@@" not in out, out)
            first = next((ln for ln in lines if "docs/a b.md" in ln), "")
            title = first.split(" | ")[2] if first.count(" | ") == 3 else ""
            check("0856 where: заголовок без управляющих и bidi, не длиннее 120",
                  title.startswith("Заголовок") and "\x1b" not in out and "\u202e" not in out and "\u200b" not in out
                  and 0 < len(title) <= 120 and all(ord(c) >= 32 for c in first), repr(first))
            check("0856 where: чужие коллекции, закрытая legal и путь с «..» в вывод не попали",
                  "legal" not in out and "ЗАКРЫТО" not in out and "Обход" not in out, out)
            check("0856 where: запрос — vec, rerank false, одна названная коллекция",
                  fake.body and fake.body["searches"] == [{"type": "vec", "query": "где лежит задаток"}]
                  and fake.body["rerank"] is False and fake.body["collections"] == ["site-b"], fake.body)
            fake.body = None
            r = run(home, pan, state, "qmd", "where", "задаток")
            check("0856 where: без --collection — все коллекции, кроме закрытых [hq].closed_collections",
                  r.returncode == 0 and fake.body["collections"] == ["site-b", "pantheon"]
                  and "pantheon | board.md | Доска | -" in r.stdout.splitlines(), f"{fake.body} {r.stdout}")
            r = run(home, pan, state, "qmd", "where", "x", "--collection", "legal")
            check("0856 where: закрытая коллекция — код 2, службу не спрашивали", r.returncode == 2 and fake.body is not None
                  and "legal" not in fake.body["collections"] and "Traceback" not in r.stderr, r.stderr)
            r = run(home, pan, state, "qmd", "where")
            check("0856 where: без вопроса — код 2", r.returncode == 2, r.stderr)
    finally:
        fake.close()
    with tempfile.TemporaryDirectory() as tmp:
        home, pan, state = setup(tmp, qmd_toml='port = 1999\n')
        r = run(home, pan, state, "qmd", "where", "x")
        check("0856 where: служба не отвечает — код 1 и причина последней строкой",
              r.returncode == 1 and r.stderr.strip().splitlines()[-1].startswith("qmd where: служба qmd"), r.stderr)


def test_hook_policy(vec):
    """Закрытые штабу коллекции — только [hq].closed_collections (metis-0182): без раздела — пусто, свой список —
    закрыт он, битое значение или битый TOML — штабу qmd закрыт целиком с причиной, остальным роли не мешает."""
    def home_with(text):
        h = tempfile.mkdtemp(prefix="qmd-pol-")
        if text is not None:
            os.makedirs(os.path.join(h, ".claude", "pantheon"))
            with open(os.path.join(h, ".claude", "pantheon", "policy.toml"), "w") as fh:
                fh.write(text)
        return h
    q = {"searches": vec, "rerank": False}
    g, m = "mcp__qmd__get", "mcp__qmd__multi_get"
    nofile = home_with(None)
    check("[hq]: нет policy.toml — штабу ничего не закрыто (в коде своих коллекций нет)",
          not hook({**q, "collections": ["corpus"]}, role="hq", home=nofile)
          and not hook({**q, "collections": ["legal"]}, window="hq", home=nofile)
          and not hook({"file": "qmd://corpus/x.md"}, g, "hq", home=nofile))
    nosec = home_with('[private]\nroles = ["hq"]\n')
    check("[hq]: нет раздела — штабу ничего не закрыто",
          hq_open(hook({**q, "collections": ["corpus"]}, role="hq", home=nosec)))
    own = home_with('[hq]\nclosed_collections = ["notes"]\n')
    check("[hq]: свой список — закрыт он, прочее открыто",
          hook({**q, "collections": ["notes"]}, role="hq", home=own)
          and hook({"file": "qmd://notes/a.md"}, g, "hq", home=own)
          and hq_open(hook({**q, "collections": ["corpus"]}, role="hq", home=own)))
    for name, text in (("строка вместо списка", '[hq]\nclosed_collections = "notes"\n'),
                       ("не строка в списке", '[hq]\nclosed_collections = ["notes", 1]\n'),
                       ("пустая строка", '[hq]\nclosed_collections = [" "]\n'),
                       ("папка не от ~/", '[hq]\nclosed_dirs = ["projects/x"]\n'),
                       ("[hq] не таблица", 'hq = ["notes"]\n'),
                       ("policy.toml не TOML", '[hq\nclosed_collections = []\n')):
        h = home_with(text)
        out = hook({**q, "collections": ["pantheon"]}, role="hq", home=h, raw=True)
        ok = ('"deny"' in out and "[hq]" in out and "policy.toml" in out
              and hook({"file": "qmd://pantheon/a.md"}, g, "hq", home=h)
              and hook({"pattern": "qmd://pantheon/*.md"}, m, window="hq", home=h)
              and not hook({**q, "collections": ["pantheon"]}, role="domain-coordinator", home=h))
        check(f"[hq] битый ({name}) — штабу qmd закрыт целиком с причиной, координатору открыт", ok, out)


def test_old_labels():
    """Переезд меток launchd: прежние plist тика и служб (com.<кто-то>.pantheon-…) снимаются, встают новые."""
    with tempfile.TemporaryDirectory() as tmp:
        home, pan, state = setup(tmp)
        agents = os.path.join(home, "Library", "LaunchAgents")
        os.makedirs(agents)
        old_tick = os.path.join(agents, "com.zorba.pantheon-tick.plist")
        old_svc = os.path.join(agents, "com.zorba.pantheon-svc.qmd.plist")
        stranger = os.path.join(agents, "com.zorba.other.plist")
        for f in (old_tick, old_svc, stranger):
            open(f, "w").write("<plist/>")
        out = run(home, pan, state, "jobs").stdout
        check("только старый тик: «старая метка — pantheon install», а не «не установлено»",
              "старая метка" in out and "pantheon install" in out, out)
        run(home, pan, state, "tick")
        log = open(os.path.join(state, "dryrun.log")).read()
        check("тик: старая служба снята (bootout, plist удалён), новая поднята",
              "old-bootout com.zorba.pantheon-svc.qmd" in log and not os.path.exists(old_svc)
              and os.path.exists(plist(home, "qmd")) and "svc-bootstrap qmd" in log, log)
        check("тик: старая служба снята раньше, чем поднята новая",
              log.index("old-bootout com.zorba.pantheon-svc.qmd") < log.index("svc-bootstrap qmd"), log)
        check("тик: старый тик не трогает (его снимает install), чужой plist — тем более",
              os.path.exists(old_tick) and os.path.exists(stranger))
        r = run(home, pan, state, "install")
        log = open(os.path.join(state, "dryrun.log")).read()
        new_tick = os.path.join(agents, "pantheon.tick.plist")
        check("install: старый тик снят (bootout, plist удалён), новый записан",
              r.returncode == 0 and "old-bootout com.zorba.pantheon-tick" in log and not os.path.exists(old_tick)
              and os.path.exists(new_tick) and "<string>pantheon.tick</string>" in open(new_tick).read()
              and "install-bootstrap pantheon.tick" in log, f"{r.stderr} {log}")
        check("install: чужой plist не тронут", os.path.exists(stranger))
        open(old_svc, "w").write("<plist/>")
        r = run(home, pan, state, "uninstall")
        check("uninstall: снимает и старые, и новые",
              r.returncode == 0 and not os.path.exists(old_svc) and not os.path.exists(new_tick)
              and not os.path.exists(plist(home, "qmd")) and os.path.exists(stranger), r.stderr)


def test_old_drop_bootout_fails():
    """drop_old: bootout упал, а задача ещё загружена (print → 0) — plist остаётся и в счёт не идёт; «нет такой» (113) — удалён."""
    for print_rc, loaded in ((0, True), (113, False)):
        with tempfile.TemporaryDirectory() as tmp:
            home, pan, state = setup(tmp)
            agents = os.path.join(home, "Library", "LaunchAgents")
            os.makedirs(agents)
            old = os.path.join(agents, "com.zorba.pantheon-svc.qmd.plist")
            open(old, "w").write("<plist/>")
            bindir = os.path.join(tmp, "bin")
            os.makedirs(bindir)
            fake = os.path.join(bindir, "launchctl")
            open(fake, "w").write(f'#!/bin/sh\nif [ "$1" = bootout ]; then exit 5; fi\n'
                                  f'if [ "$1" = print ]; then exit {print_rc}; fi\nexit 0\n')
            os.chmod(fake, 0o755)
            env = {"PATH": bindir + ":" + os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pan,
                   "PANTHEON_STATE": state, "PANTHEON_NOW": str(T0), "TMPDIR": _ROOT}
            code = ("import importlib.util,sys;s=importlib.util.spec_from_file_location('pan',sys.argv[1]);"
                    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(m.drop_old(m.OLD_SVC_GLOB))")
            r = subprocess.run([PY311, "-I", "-c", code, LIB], env=env, capture_output=True, text=True, timeout=60)
            tag = "служба ещё загружена" if loaded else "службы нет"
            if loaded:
                check(f"drop_old, {tag}: plist остался, в счёт не включён, предупреждение в stderr",
                      os.path.exists(old) and r.stdout.strip() == "0" and "com.zorba.pantheon-svc.qmd" in r.stderr,
                      f"{r.stdout} {r.stderr}")
            else:
                check(f"drop_old, {tag}: plist удалён и посчитан",
                      not os.path.exists(old) and r.stdout.strip() == "1", f"{r.stdout} {r.stderr}")


def test_pause_drops_only_own_old():
    """Пульт снимает одну службу (jobs pause qmd): прежняя служба с другим именем остаётся, с этим — снята."""
    with tempfile.TemporaryDirectory() as tmp:
        home, pan, state = setup(tmp)
        agents = os.path.join(home, "Library", "LaunchAgents")
        os.makedirs(agents)
        mine = os.path.join(agents, "com.zorba.pantheon-svc.qmd.plist")
        other = os.path.join(agents, "com.zorba.pantheon-svc.only-b.plist")
        wild = os.path.join(agents, "com.zorba.pantheon-svc.qmd2.plist")
        for f in (mine, other, wild):
            open(f, "w").write("<plist/>")
        r = run(home, pan, state, "jobs", "pause", "qmd")
        log = open(os.path.join(state, "dryrun.log")).read()
        check("пульт: прежняя служба с этим именем снята, остальные прежние нетронуты",
              r.returncode == 0 and not os.path.exists(mine) and os.path.exists(other) and os.path.exists(wild)
              and "old-bootout com.zorba.pantheon-svc.qmd\n" in log and "only-b" not in log, f"{r.stderr} {log}")


if __name__ == "__main__":
    test_services()
    test_qmd_config()
    test_hook()
    test_where()
    test_old_labels()
    test_old_drop_bootout_fails()
    test_pause_drops_only_own_old()
    print(f"{len(OK)} из {len(OK) + len(FAIL)} прошли")
    sys.exit(1 if FAIL else 0)
