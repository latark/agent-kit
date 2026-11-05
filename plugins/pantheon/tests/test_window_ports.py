#!/usr/bin/env python3
"""Сокеты окнам ролей ([sb-simplify], «да» владельца 27.10).

Запуск: python3 -I plugins/pantheon/tests/test_window_ports.py  (код выхода 0 — все прошли)
- `pantheon domains build` на временном HOME: окна направлений и мастерская получают allowUnixSockets — ровно свой кэш,
  и PANTHEON_TMP — папку tmp в нём;
- allowLocalBinding нет ни у кого: он открывает весь localhost (местный прокси — прокси наружу мимо allowedDomains, 9222);
- пароль демона CDP закрыт всем окнам: denyRead песочницы и правило Read(…/**);
- окна задач расписания, Гестии и штаба сокетов не получают.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="win-ports-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def py311():
    return sys.executable


def main():
    tmp = os.path.join(ROOT, "h")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    for d in ("projects/br", "ai/knowledge", "ai/workshop"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    out = os.path.join(state, "settings")
    win = lambda n: json.load(open(os.path.join(out, n + ".json")))  # noqa: E731

    def build(*args):
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
               "PANTHEON_NO_NOTIFY": "1"}
        r = subprocess.run([py311(), "-I", RUN_PY, "domains", "build", *args], env=env, capture_output=True, text=True,
                           timeout=120)
        if r.returncode:
            print(r.stderr)
        return r.returncode == 0

    check("сборка прошла", build())
    for n in ("athena-shop", "workshop"):
        net = win(n)["sandbox"]["network"]
        cache = os.path.realpath(os.path.join(tmp, "Library", "Caches", "pantheon-sandbox", n))
        check(f"{n}: allowUnixSockets — ровно свой кэш", net.get("allowUnixSockets") == [cache])
        check(f"{n}: PANTHEON_TMP — tmp в своём кэше", win(n)["env"].get("PANTHEON_TMP") == os.path.join(cache, "tmp"))
        # allowLocalBinding открывает весь localhost: местный прокси (выход наружу мимо allowedDomains) и 9222 браузера
        check(f"{n}: allowLocalBinding нет", "allowLocalBinding" not in net)
    for n in ("athena-shop", "hq", "hestia", "job-clio"):
        if os.path.isfile(os.path.join(out, n + ".json")):
            check(f"{n}: пароль демона CDP в denyRead", any(x.endswith("/.config/cdp-daemon")
                                                           for x in win(n)["sandbox"]["filesystem"]["denyRead"]))
            check(f"{n}: пароль демона CDP закрыт правилом Read",
                  "Read(~/.config/cdp-daemon/**)" in win(n)["permissions"]["deny"])
    for n in ("hq", "hestia", "job-clio"):
        if os.path.isfile(os.path.join(out, n + ".json")):
            net = win(n)["sandbox"]["network"]
            check(f"{n}: без сокетов", "allowUnixSockets" not in net)

if __name__ == "__main__":
    main()
    print(f"\n{sum(results)}/{len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)
