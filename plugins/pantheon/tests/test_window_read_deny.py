#!/usr/bin/env python3
"""Чтение, закрытое окнам ролей: разборы личных чатов (metis-0270) и ключи демона Claude Code (metis-0287).

Запуск: python3 -I plugins/pantheon/tests/test_window_read_deny.py  (код выхода 0 — все прошли)
- `pantheon domains build` на временном HOME;
- всем окнам (направление, мастерская, задача расписания, Гестия, штаб) закрыты raw.md, answer.md, item.md и
  summary.md заявок STATE/read/<rid>/: denyRead песочницы (Bash) и правило Read (инструменты Read, Grep, Glob), в виде
  «~/…» и настоящим путём; шаблон совпадает с путём, который пишет read.py;
- approved.md заявки не закрыт никому: его по указателю из inbox читает направление;
- ~/.claude/daemon закрыт окнам направлений, мастерской и задач расписания (denyRead и Read(…/**)), штабу и Гестии
  открыт: их `claude agents` и `pantheon who` читают реестр демона.
"""
import atexit
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="win-read-deny-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def main():
    tmp = os.path.join(ROOT, "h")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    for d in ("projects/br", "ai/knowledge", "projects/workshop", ".claude/pantheon"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    with open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w") as fh:
        fh.write('[hq]\nclosed_dirs = []\n')
    out = os.path.join(state, "settings")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    r = subprocess.run([sys.executable, "-I", LIB, "domains", "build"], env=env, capture_output=True, text=True,
                       timeout=120)
    check("сборка прошла", r.returncode == 0)
    if r.returncode:
        print(r.stderr)
        return
    windows = ["athena-shop", "workshop", "job-clio", "job-prometheus", "hestia", "hq"]
    for n in windows:
        check(f"{n}: окно собрано", os.path.isfile(os.path.join(out, n + ".json")))
    win = lambda n: json.load(open(os.path.join(out, n + ".json")))  # noqa: E731
    # путь, который пишет read.py: STATE/read/<rid>/<файл>; номер заявки — по образцу RID_RE
    rid_dir = os.path.join(state, "read", "20261028-1435-abcd")
    for n in windows:
        if not os.path.isfile(os.path.join(out, n + ".json")):
            continue
        data = win(n)
        deny_fs = data["sandbox"]["filesystem"]["denyRead"]
        rules = data["permissions"]["deny"]
        reads = [x[5:-1] for x in rules if x.startswith("Read(")]
        reads = [x[1:] if x.startswith("//") else x for x in reads]  # «//abs» — абсолютный путь правила
        for f in ("raw.md", "answer.md", "item.md", "summary.md"):
            p = os.path.join(rid_dir, f)
            check(f"{n}: {f} заявки — в denyRead песочницы", any(fnmatch.fnmatchcase(p, x) for x in deny_fs))
            check(f"{n}: {f} заявки — правило Read", any(fnmatch.fnmatchcase(p, x) for x in reads))
            check(f"{n}: {f} заявки — и в виде ~/", f"Read(~/state/read/*/{f})" in rules)
        ap = os.path.join(rid_dir, "approved.md")
        check(f"{n}: approved.md открыт (denyRead)", not any(fnmatch.fnmatchcase(ap, x) for x in deny_fs))
        check(f"{n}: approved.md открыт (Read)", not any(fnmatch.fnmatchcase(ap, x) for x in reads))
        daemon = os.path.join(tmp, ".claude", "daemon")
        closed = n not in ("hq", "hestia")
        check(f"{n}: ~/.claude/daemon в denyRead — {'да' if closed else 'нет'}",
              (daemon in deny_fs and "~/.claude/daemon" in deny_fs) == closed)
        check(f"{n}: правило Read(~/.claude/daemon/**) — {'да' if closed else 'нет'}",
              ("Read(~/.claude/daemon/**)" in rules and f"Read(/{daemon}/**)" in rules) == closed)
        check(f"{n}: без повторов в denyRead", len(deny_fs) == len(set(deny_fs)))


if __name__ == "__main__":
    main()
    print(f"\n{sum(results)}/{len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)
