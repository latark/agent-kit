#!/usr/bin/env python3
"""Размер песочницы окон (15.10, hq: 4359 путей, профиль Seatbelt > 64 КБ — Bash штаба не запускался).

Запуск: python3 -I plugins/pantheon/tests/test_sandbox_size.py  (код выхода 0 — все прошли)
Проверяет на временных папках (HOME, PANTHEON_*, PANTHEON_CLAUDE_TMP — подменены, настоящие не трогаются):
- список запретов штаба не растёт с числом папок в /tmp/claude-<uid>: 50 и 5000 папок дают одинаковый hq.json;
- чужие папки закрыты и песочницей, и правилом Read; свои (папка штаба и его worktree) и временные файлы\n  в корне $TMPDIR (heredoc, mktemp) — открыты;
- предохранитель: окно с песочницей больше предела не пересобирается, приходит одна тревога.
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="sandbox-size-test-"))
atexit.register(shutil.rmtree, ROOT, True)
dash = lambda p: re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(p))  # noqa: E731


def glob_re(g, sandbox=False):
    """Шаблон пути Claude Code → regex: «**» — любые папки, «*» — внутри одного имени. sandbox — как запрет-шаблон
    denyRead в Seatbelt (Claude Code 2.1.300): хвост «/**» срезан, совпадает и всё поддерево."""
    if sandbox and g.endswith("/**"):
        g = g[:-3]
    out, i = "", 0
    while i < len(g):
        if g.startswith("/**", i):
            out, i = out + "(/.*)?", i + 3
        elif g[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(g[i]), i + 1
    return re.compile(out + "(/.*)?")


def setup(tmp):
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    open(os.path.join(home, "directions.toml"), "w").write(
        '[[direction]]\nname = "athena-broker"\nfolders = ["~/projects/br"]\n')
    os.makedirs(os.path.join(tmp, "projects", "br"))
    os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
    open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w").write("")
    tasks = os.path.join(tmp, "ctmp", f"claude-{os.getuid()}")
    os.makedirs(tasks)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_CLAUDE_TMP": tasks, "PANTHEON_NO_NOTIFY": "1"}
    return home, state, tasks, env


def build(env):
    return subprocess.run([PY311, "-I", LIB, "domains", "build"], env=env, capture_output=True, text=True,
                          timeout=120)


def main():
    results = []

    def check(name, cond):
        cond = bool(cond)
        results.append(cond)
        print(("ok  " if cond else "FAIL") + " " + name)

    tmp = os.path.join(ROOT, "a")
    os.makedirs(tmp)
    home, state, tasks, env = setup(tmp)
    own = dash(home)
    projects = os.path.join(tmp, ".claude", "projects")
    mine = [own, own + "--claude-worktrees-x"]
    foreign = [dash(tmp) + "-projects-br", dash(tmp), own + "-view", "-private-tmp-x", "tick-test-ab12", "zz"]
    for n in mine + foreign:
        os.makedirs(os.path.join(tasks, n))
        os.makedirs(os.path.join(projects, n, "s1", "tool-results"))
    for i in range(50):
        os.makedirs(os.path.join(tasks, f"guard-test-{i:05d}"))
    for n in ("cfgcheck-00000", "watch-test-00000"):
        os.makedirs(os.path.join(tasks, n))
    r = build(env)
    hq1 = json.load(open(os.path.join(state, "settings", "hq.json")))
    fs = hq1["sandbox"]["filesystem"]
    check("сборка прошла, hq.json собран", r.returncode == 0 and fs["denyRead"])

    for i in range(50, 5000):
        os.makedirs(os.path.join(tasks, f"guard-test-{i:05d}"))
    for i in range(1, 300):
        os.makedirs(os.path.join(tasks, f"cfgcheck-{i:05d}"))
        os.makedirs(os.path.join(tasks, f"watch-test-{i:05d}"))
    r = build(env)
    hq2 = json.load(open(os.path.join(state, "settings", "hq.json")))
    fs2 = hq2["sandbox"]["filesystem"]
    size = len(json.dumps(fs2["denyRead"]) + json.dumps(hq2["permissions"]["deny"]))
    print(f"     denyRead {len(fs2['denyRead'])} путей, deny {len(hq2['permissions']['deny'])}, {size} байт")
    check("5600 папок в /tmp/claude-<uid>: denyRead и правила Read штаба те же, что при 50 (не O(n))",
          r.returncode == 0 and fs2["denyRead"] == fs["denyRead"]
          and hq2["permissions"]["deny"] == hq1["permissions"]["deny"] and len(fs2["denyRead"]) < 80)

    deny_sb = [glob_re(x, sandbox=True) for x in fs2["denyRead"] if x.startswith("/")]
    deny_sb += [glob_re("/" + x[len("Read(//"):-1], sandbox=True) for x in hq2["permissions"]["deny"]
                if x.startswith("Read(//")]  # правила Read Claude Code вливает в песочницу
    deny_rd = [glob_re("/" + x[len("Read(//"):-1]) for x in hq2["permissions"]["deny"] if x.startswith("Read(//")]
    deny_rd += [glob_re(os.path.join(tmp, x[len("Read(~/"):-1])) for x in hq2["permissions"]["deny"]
                if x.startswith("Read(~/")]

    sb_closed = lambda p: any(m.fullmatch(p) for m in deny_sb)  # noqa: E731

    rd_closed = lambda p: any(m.fullmatch(p) for m in deny_rd)  # noqa: E731
    junk = [f"guard-test-{i:05d}" for i in (0, 4999)] + ["cfgcheck-00001", "watch-test-00299"]
    others = [os.path.join(tasks, n, "s", "tasks", "b1.output") for n in foreign + junk]
    check("чужие выводы в /tmp/claude-<uid> (сессии, мусор тестов) закрыты песочницей и правилом Read",
          all(sb_closed(p) and rd_closed(p) for p in others))
    ours = [os.path.join(tasks, n, "s", "tasks", "b1.output") for n in mine]
    check("свои выводы штаба и его worktree открыты и песочницей, и правилом Read; allowRead нет",
          all(not sb_closed(p) and not rd_closed(p) for p in ours) and "allowRead" not in fs2)
    # корень CLAUDE_TMP — $TMPDIR песочницы: heredoc zsh ($TMPPREFIX=$TMPDIR/zsh), mktemp, tempfile (argus 15.10)
    roots = [os.path.join(tasks, n) for n in ("zshAbC123", "tmp.Xy12ab", "tmpk3j_x9", "guard-test-x.log", "a.txt")]
    roots += [os.path.join(tasks, n, "f.txt") for n in ("tmp.Zeus1", "tmpk3j_x9", "tmp")]  # mktemp -d, mkdtemp
    check("временные файлы и папки штаба в корне $TMPDIR (heredoc, mktemp, mktemp -d, mkdtemp) читаются",
          all(not sb_closed(p) and not rd_closed(p) for p in roots))
    check("чужие папки на «t» (tick-test-*) закрыты, шаблон не задевает tmp*",
          sb_closed(os.path.join(tasks, "tick-test-ab12", "x")) and rd_closed(os.path.join(tasks, "tick-test-ab12", "x")))
    check("tool-results: чужие закрыты правилом Read, свои — нет",
          all(rd_closed(os.path.join(projects, n, "s1", "tool-results", "x.txt")) for n in foreign)
          and not any(rd_closed(os.path.join(projects, n, "s1", "tool-results", "x.txt")) for n in mine))
    # P0-1 (metis-0060): выгрузки Telegram legal-watch (cache, inbox) штабу закрыты — песочница и правило Read
    tg = ("~/projects/legal-watch/cache", "~/projects/legal-watch/inbox")
    check("окно штаба: legal-watch/cache и inbox — в denyRead песочницы и в правилах Read",
          all(x in fs2["denyRead"] and f"Read({x}/**)" in hq2["permissions"]["deny"] for x in tg)
          and all(os.path.join(tmp, x[2:]) in fs2["denyRead"] for x in tg))
    deny_tg = [glob_re(os.path.join(tmp, x[len("Read(~/"):-1])) for x in hq2["permissions"]["deny"]
               if x.startswith("Read(~/projects/legal-watch")]
    check("окно штаба: файл выгрузки legal-watch/cache/telegram/… закрыт правилом Read, папка src/ — нет",
          any(m.fullmatch(os.path.join(tmp, "projects/legal-watch/cache/telegram/ch.json")) for m in deny_tg)
          and not any(m.fullmatch(os.path.join(tmp, "projects/legal-watch/src/a.py")) for m in deny_tg))
    sa = json.load(open(os.path.join(state, "settings", "athena-broker.json")))
    check("окно направления: legal-watch штабу закрыт, координатору — нет",
          not any("legal-watch" in x for x in sa["sandbox"]["filesystem"]["denyRead"]))
    gm = [g["matcher"] for w in (hq2, sa) for g in w["hooks"]["PreToolUse"]
          if any("guard.py" in h.get("command", "") for h in g.get("hooks") or [])]  # без хука agents.py (P0-6)
    check("строгий guard окон штаба и направления: matcher с Agent|Task|Skill (hq-telegram, chiron)",
          len(gm) == 2 and all({"Agent", "Task", "Skill", "Bash", "Read"} <= set(m.split("|")) for m in gm))
    check("окно направления: allowRead нет, запретов чтения — единицы (координаторы не раздуваются)",
          "allowRead" not in sa["sandbox"]["filesystem"] and len(sa["sandbox"]["filesystem"]["denyRead"]) < 20)

    # предохранитель: песочница направления больше предела — файл не переписан, одна тревога; вернулась в предел —
    # пересобран и тревога снова возможна
    pol = os.path.join(tmp, ".claude", "pantheon", "policy.toml")
    big = ", ".join(f'"~/private/{"x" * 40}-{i}"' for i in range(1500))
    open(pol, "w").write(f"[private]\npaths = [{big}]\n")
    before = open(os.path.join(state, "settings", "athena-broker.json")).read()
    r1, r2 = build(env), build(env)
    alerts = open(os.path.join(home, "alerts.md")).read() if os.path.exists(os.path.join(home, "alerts.md")) else ""
    after = open(os.path.join(state, "settings", "athena-broker.json")).read()
    check("предохранитель: окно больше предела не пересобрано, прежний файл на месте, одна тревога",
          after == before and alerts.count("песочница окна athena-broker") == 1 and "не пересобрано" in r1.stderr)
    open(pol, "w").write('[private]\npaths = ["~/private/one"]\n')
    build(env)
    sa = json.load(open(os.path.join(state, "settings", "athena-broker.json")))
    open(pol, "w").write(f"[private]\npaths = [{big}]\n")
    build(env)
    alerts = open(os.path.join(home, "alerts.md")).read()
    check("предохранитель: в пределе окно пересобрано; новый выход за предел — новая тревога",
          "~/private/one" in sa["sandbox"]["filesystem"]["denyRead"] and alerts.count("песочница окна athena-broker") == 2)

    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
