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
    return subprocess.run([sys.executable, "-I", LIB, *args], env=env, capture_output=True, text=True, timeout=60)


def dry(state):
    """Решения о службах (svc-…) из dryrun.log — задачи тика туда тоже пишут, их отбрасываем."""
    p = os.path.join(state, "dryrun.log")
    lines = [ln.split(None, 1)[1].strip() for ln in open(p)] if os.path.exists(p) else []
    return [ln for ln in lines if ln.startswith("svc-")]


def plist(home, name):
    return os.path.join(home, "Library", "LaunchAgents", f"com.latark.pantheon-svc.{name}.plist")


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


def hook(ti, tool="mcp__qmd__query", role=None, window=None, raw=False):
    ev = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti}
    if role:
        ev["agent_type"] = role
    env = {"PATH": os.environ["PATH"], "HOME": tempfile.gettempdir()}
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
    check("штабу другие коллекции открыты", not hook({**q, "collections": ["pantheon"]}, role="hq"))
    g = "mcp__qmd__get"
    check("штаб: get qmd://corpus/… — отказ", hook({"file": "qmd://corpus/lec.md"}, g, "hq"))
    check("штаб: get по docid — отказ", hook({"file": "#abc123"}, g, "hq"))
    check("штаб: get с .. — отказ", hook({"file": "qmd://pantheon/../corpus/x.md"}, g, "hq"))
    check("штаб: get относительным путём — отказ", hook({"file": "data/lec.md"}, g, "hq"))
    check("штаб: get qmd://pantheon/… — пропуск", not hook({"file": "qmd://pantheon/board.md:10"}, g, "hq"))
    m = "mcp__qmd__multi_get"
    check("штаб: multi_get со списком, где есть corpus — отказ",
          hook({"pattern": "qmd://pantheon/a.md,qmd://corpus/b.md"}, m, "hq"))
    check("штаб: multi_get глоб {corpus,…} — отказ", hook({"pattern": "qmd://{corpus,pantheon}/*.md"}, m, "hq"))
    # P0-1 (metis-0060): штабу закрыта и коллекция legal — право и выгрузки Telegram-каналов, только Фемиде
    check("штаб (окно hq): query по legal — отказ", hook({**q, "collections": ["legal"]}, window="hq"))
    check("штаб: query по legal и pantheon — отказ", hook({**q, "collections": ["pantheon", " legal"]}, role="hq"))
    out = hook({**q, "collections": ["legal"]}, window="hq", raw=True)
    check("штаб: отказ по legal — Фемиде (themis-sources) поручением", "themis-sources" in out and "Telegram" in out
          and "Куклин" not in out, out)
    check("штаб (окно hq): query по pantheon — пропуск", not hook({**q, "collections": ["pantheon"]}, window="hq"))
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


if __name__ == "__main__":
    test_services()
    test_qmd_config()
    test_hook()
    print(f"{len(OK)} из {len(OK) + len(FAIL)} прошли")
    sys.exit(1 if FAIL else 0)
