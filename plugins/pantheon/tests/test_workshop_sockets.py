#!/usr/bin/env python3
"""Окно мастерской слушает Unix-сокеты только в своём кэше (metis-0278, решение владельца «А» 19.10).

Запуск: python3 -I plugins/pantheon/tests/test_workshop_sockets.py  (код выхода 0 — все прошли)
- `pantheon domains build` на временном HOME: у workshop.json sandbox.network.allowUnixSockets — ровно [настоящий путь
  ~/Library/Caches/pantheon-sandbox/workshop], без allowLocalBinding и allowAllUnixSockets (на macOS он открыл бы все
  порты 127.0.0.1, в том числе демон CDP); у окон координаторов и задач расписания allowUnixSockets нет;
- проба seatbelt тем же правилом, что ставит Claude Code на allowUnixSockets (subpath для bind и connect): bind
  AF_UNIX в кэше проходит, во второй папке рядом — EPERM. Внутри чужой песочницы (sandbox_apply: EPERM) — skip.
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


def _root():
    # короткий корень для пробы: путь сокета на macOS — до 104 байт; в песочнице /tmp закрыт — тогда $TMPDIR
    try:
        return tempfile.mkdtemp(prefix="ws-sock-", dir="/tmp")
    except OSError:
        return tempfile.mkdtemp(prefix="ws-sock-")


ROOT = os.path.realpath(_root())
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


BIND = """
import os, socket, sys
s = socket.socket(socket.AF_UNIX)
try:
    s.bind(os.path.join(sys.argv[1], "probe.sock"))
    s.listen(1)
    c = socket.socket(socket.AF_UNIX)
    c.connect(os.path.join(sys.argv[1], "probe.sock"))
    print("ok")
except OSError as e:
    print("errno", e.errno)
"""


def seatbelt_probe(allowed, outside):
    """bind+connect под профилем: сеть закрыта, Unix-сокеты — только subpath из allowUnixSockets (как в Claude Code)."""
    sb = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
    if sys.platform != "darwin" or not os.path.exists(sb):
        return None
    rules = "".join(f'(allow network-bind (local unix-socket (subpath "{p}")))'
                    f'(allow network-outbound (remote unix-socket (subpath "{p}")))' for p in allowed)
    profile = ("(version 1)(allow default)(deny network*)(allow system-socket (socket-domain AF_UNIX))" + rules)
    out = []
    for d in (allowed[0], outside):
        r = subprocess.run([sb, "-p", profile, "/usr/bin/python3", "-I", "-c", BIND, d], capture_output=True,
                           text=True, timeout=60)
        if "sandbox_apply" in r.stderr:
            return None  # уже внутри песочницы: вложенный seatbelt macOS не даёт
        out.append(r.stdout.strip() or r.stderr.strip())
    return out


def main():
    tmp = os.path.join(ROOT, "h")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    for d in ("projects/br", "ai/knowledge", "projects/workshop"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n'
                 '[[direction]]\nname = "mnemo-brain"\nfolders = ["~/ai/knowledge"]\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    r = subprocess.run([py311(), "-I", LIB, "domains", "build"], env=env, capture_output=True, text=True, timeout=120)
    check("domains build на временном HOME прошёл", r.returncode == 0)
    if r.returncode != 0:
        print(r.stderr)
        return
    out = os.path.join(state, "settings")
    win = lambda n: json.load(open(os.path.join(out, n + ".json")))  # noqa: E731
    cache = os.path.realpath(os.path.join(tmp, "Library", "Caches", "pantheon-sandbox", "workshop"))
    net = win("workshop")["sandbox"]["network"]
    check("workshop: allowUnixSockets — ровно настоящий путь кэша окна", net.get("allowUnixSockets") == [cache])
    check("workshop: кэш окна существует (Claude Code ставит subpath на настоящий путь)", os.path.isdir(cache))
    check("workshop: allowLocalBinding и allowAllUnixSockets нет",
          "allowLocalBinding" not in net and "allowAllUnixSockets" not in net)
    check("workshop: сеть по-прежнему по списку доменов", isinstance(net.get("allowedDomains"), list))
    others = sorted(f[:-5] for f in os.listdir(out) if f.endswith(".json") and f != "workshop.json")
    check("координаторы athena-shop и mnemo-brain собраны", {"athena-shop", "mnemo-brain"} <= set(others))
    bad = [n for n in others if set(win(n)["sandbox"].get("network", {})) - {"allowedDomains"}]
    check(f"остальные окна ({len(others)}): в network только allowedDomains — без сокетов и местных портов", not bad)
    print(f"     путь кэша окна: {len(cache)} байт; на машине владельца ~/Library/Caches/pantheon-sandbox/workshop "
          "≈ 50 байт — до предела 104 остаётся ~50 на имя папки и сокета")

    outside = os.path.join(ROOT, "outside")
    os.makedirs(outside)
    got = seatbelt_probe([cache], outside)
    if got is None:
        print("skip проба seatbelt: вложенный sandbox-exec недоступен (запуск внутри песочницы) или не macOS")
    else:
        check(f"seatbelt: bind+connect в кэше окна проходит ({got[0]})", got[0] == "ok")
        check(f"seatbelt: bind в папке рядом — EPERM ({got[1]})", got[1] == "errno 1")


if __name__ == "__main__":
    main()
    print(f"\n{sum(results)}/{len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)
