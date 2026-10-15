#!/usr/bin/env python3
"""pantheon direction check (навык new-direction, ROLE-05, STATE-11): что готово у нового направления.
Временный HOME: реестр, журнал решений, папка штаба, domains.json, окно, доверие, autoMode, names.part, репозиторий."""
import json
import os
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="direction-test-"))
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    repo = os.path.join(tmp, "projects", "demo")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin", "git@github.com:latark/demo.git"], check=True)
    write(os.path.join(repo, "AGENTS.md"), "# demo\n")
    write(os.path.join(home, "directions.toml"),
          '[[direction]]\nname = "iris-demo"\nproject = "demo"\nfolders = ["~/projects/demo"]\nleads = ["hephaestus"]\n'
          'does = "Демо"\ndoes_not = "Чужое — соседям"\nexamples = ["раз", "два", "три"]\n')
    decisions = os.path.join(home, "decisions.md")
    write(decisions, "| Дата | Решение |\n| --- | --- |\n"
                     "| 15.10.2026 | Новое направление `iris-demo`. Ваши слова: «да» | — |\n")
    for x in ("inbox/.keep", "tasks/.keep", "STATUS.md"):
        write(os.path.join(home, "directions", "iris-demo", x), "")
    write(os.path.join(state, "domains.json"), json.dumps({"domains": {"iris-demo": [repo]}}))
    write(os.path.join(state, "settings", "iris-demo.json"), "{}")
    write(os.path.join(tmp, ".claude.json"), json.dumps({"projects": {repo: {"hasTrustDialogAccepted": True}}}))
    settings = os.path.join(tmp, ".claude", "settings.json")
    write(settings, json.dumps({"autoMode": {"environment": ["**Source control**: GitHub `github.com/latark/*`"]}}))
    write(os.path.join(tmp, ".claude", "agents", "_parts", "names.part"), "- она: Ирида (iris-demo)\n")
    write(os.path.join(tmp, ".claude", "agents", "hephaestus-demo.md"), "x")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    run = lambda name: subprocess.run([sys.executable, "-I", LIB, "direction", "check", name], env=env,
                                      capture_output=True, text=True)

    r = run("iris-demo")
    check("всё готово — код 0, ни одного «НЕТ»", r.returncode == 0 and "НЕТ" not in r.stdout)

    write(decisions, "| 15.10.2026 | Новое направление `iris-demo` — совет Зевса | — |\n")
    r = run("iris-demo")
    check("без ваших слов в decisions.md — код 1, «НЕТ» на строке «да»",
          r.returncode == 1 and "НЕТ     ваше «да»" in r.stdout)
    write(decisions, "| 15.10.2026 | Направление `iris-demo-old` закрыто. Ваши слова: «да» | — |\n")
    check("«да» другому направлению с тем же началом имени не засчитывается", run("iris-demo").returncode == 1)
    write(decisions, "| 15.10.2026 | Новое направление `iris-demo`. Ваши слова: «да» | — |\n")

    r = run("Iris_Demo")
    check("имя не по образцу — «НЕТ» на имени", r.returncode == 1 and "НЕТ     имя" in r.stdout)

    write(os.path.join(repo, "CLAUDE.md"), "# свои правила\n")
    check("CLAUDE.md без @AGENTS.md — не готово", "НЕТ     AGENTS.md" in run("iris-demo").stdout)
    write(os.path.join(repo, "CLAUDE.md"), "@AGENTS.md\n\nТолько для Claude.\n")
    check("CLAUDE.md, который начинается с @AGENTS.md, — готово", run("iris-demo").returncode == 0)

    write(settings, json.dumps({"autoMode": {"environment": ["**Source control**: GitHub `github.com/other/*`"]}}))
    check("владелец remote не описан в autoMode.environment — не готово",
          "НЕТ     владелец remote" in run("iris-demo").stdout)

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
