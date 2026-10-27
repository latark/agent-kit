#!/usr/bin/env python3
"""Порт и сокеты окнам ролей ([sb-simplify], «да» владельца 27.10).

Запуск: python3 -I plugins/pantheon/tests/test_window_ports.py  (код выхода 0 — все прошли)
- `pantheon domains build` на временном HOME: окна направлений и мастерская получают allowUnixSockets — ровно свой кэш;
- allowLocalBinding — только когда демон CDP заперт: есть ~/.config/cdp-daemon/token и каждый слушающий порт из
  PANTHEON_CDP_PORTS на POST /eval без пароля отвечает 401. Демон без пароля (200), пароля нет — порта нет;
- пароль закрыт всем окнам: denyRead песочницы и правило Read(…/**);
- --if-changed пересобирает окна, когда демон заперли (поле ports в domains.json);
- окна задач расписания, Гестии и штаба порта и сокетов не получают.
"""
import atexit
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="win-ports-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def py311():
    if sys.version_info >= (3, 11):
        return sys.executable
    for v in ("3.14", "3.13", "3.12", "3.11"):
        p = shutil.which("python" + v)
        if p:
            return p
    sys.exit("нет Python 3.11+ для pantheon.py")


def daemon(code):
    """Поддельный демон CDP: на любой POST отвечает code."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(code)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    tmp = os.path.join(ROOT, "h")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    for d in ("projects/br", "ai/knowledge", "projects/workshop"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    out = os.path.join(state, "settings")
    win = lambda n: json.load(open(os.path.join(out, n + ".json")))  # noqa: E731
    token_dir = os.path.join(tmp, ".config", "cdp-daemon")

    def build(ports, *args):
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
               "PANTHEON_NO_NOTIFY": "1", "PANTHEON_CDP_PORTS": ",".join(map(str, ports))}
        r = subprocess.run([py311(), "-I", LIB, "domains", "build", *args], env=env, capture_output=True, text=True,
                           timeout=120)
        if r.returncode:
            print(r.stderr)
        return r.returncode == 0

    closed = free_port()
    check("сборка без пароля демона прошла", build([closed]))
    net = win("athena-shop")["sandbox"]["network"]
    cache = os.path.realpath(os.path.join(tmp, "Library", "Caches", "pantheon-sandbox", "athena-shop"))
    check("направление: allowUnixSockets — ровно свой кэш", net.get("allowUnixSockets") == [cache])
    check("нет пароля демона — allowLocalBinding нет", "allowLocalBinding" not in net)
    fs = win("athena-shop")["sandbox"]["filesystem"]
    check("пароль демона в denyRead песочницы", any(x.endswith("/.config/cdp-daemon") for x in fs["denyRead"]))
    check("пароль демона закрыт правилом Read",
          "Read(~/.config/cdp-daemon/**)" in win("athena-shop")["permissions"]["deny"])

    os.makedirs(token_dir)
    with open(os.path.join(token_dir, "token"), "w") as fh:
        fh.write("x" * 64)
    open_d = daemon(200)
    check("демон без пароля (200) — сборка прошла", build([open_d.server_port, closed]))
    check("демон без пароля — allowLocalBinding нет",
          "allowLocalBinding" not in win("athena-shop")["sandbox"]["network"])
    open_d.shutdown()

    locked = daemon(401)
    check("демон заперт (401) — --if-changed пересобрал окна", build([locked.server_port, closed], "--if-changed"))
    for n in ("athena-shop", "workshop"):
        check(f"{n}: демон заперт — allowLocalBinding", win(n)["sandbox"]["network"].get("allowLocalBinding") is True)
    check("domains.json помнит ports=true", json.load(open(os.path.join(state, "domains.json"))).get("ports") is True)
    for n in ("hq", "hestia", "job-clio"):
        if os.path.isfile(os.path.join(out, n + ".json")):
            net = win(n)["sandbox"]["network"]
            check(f"{n}: без порта и сокетов", "allowLocalBinding" not in net and "allowUnixSockets" not in net)
            check(f"{n}: пароль демона закрыт", any(x.endswith("/.config/cdp-daemon")
                                                    for x in win(n)["sandbox"]["filesystem"]["denyRead"]))
    locked.shutdown()


if __name__ == "__main__":
    main()
    print(f"\n{sum(results)}/{len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)
