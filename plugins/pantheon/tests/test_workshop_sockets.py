#!/usr/bin/env python3
"""Окно мастерской слушает Unix-сокеты только в своём кэше (metis-0278, решение владельца «А» 19.10).

Запуск: python3 -I plugins/pantheon/tests/test_workshop_sockets.py  (код выхода 0 — все прошли)
- `pantheon domains build` на временном HOME: у workshop.json sandbox.network.allowUnixSockets — ровно [настоящий путь
  ~/Library/Caches/pantheon-sandbox/workshop], без allowLocalBinding и allowAllUnixSockets (на macOS он открыл бы все
  порты 127.0.0.1, в том числе демон CDP); у окон направлений — свой кэш ([sb-simplify]), у задач расписания, Гестии и штаба — нет;
- проба seatbelt тем же правилом, что ставит Claude Code на allowUnixSockets (subpath для bind и connect): bind
  AF_UNIX в кэше проходит, во второй папке рядом — EPERM. Внутри чужой песочницы (sandbox_apply: EPERM) — skip.
"""
import atexit
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")


RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
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
    return sys.executable


CHILD = """
import os, socket, sys
mode, path = sys.argv[1], sys.argv[2]
s = socket.socket(socket.AF_UNIX)
try:
    if mode == "bind":
        s.bind(path)
        s.listen(1)
        c = socket.socket(socket.AF_UNIX)
        c.connect(path)
    else:
        s.connect(path)
    print("ok")
except OSError as e:
    print("errno", e.errno)
"""


def seatbelt_probe(cache, outside):
    """Четыре прогона под профилем «сеть закрыта, Unix-сокеты — только subpath кэша» (как ставит Claude Code):
    [bind+connect в кэше, bind снаружи, connect к сокету снаружи напрямую, connect к нему через симлинк в кэше].
    None — проба не исполнима (не macOS или уже внутри песочницы)."""
    sb = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
    if sys.platform != "darwin" or not os.path.exists(sb):
        return None
    rules = (f'(allow network-bind (local unix-socket (subpath "{cache}")))'
             f'(allow network-outbound (remote unix-socket (subpath "{cache}")))')
    profile = "(version 1)(allow default)(deny network*)(allow system-socket (socket-domain AF_UNIX))" + rules

    def run(mode, path):
        r = subprocess.run([sb, "-p", profile, "/usr/bin/python3", "-I", "-c", CHILD, mode, path],
                           capture_output=True, text=True, timeout=60)
        if "sandbox_apply" in r.stderr:
            return None  # уже внутри песочницы: вложенный seatbelt macOS не даёт
        return r.stdout.strip() or r.stderr.strip()

    inside = run("bind", os.path.join(cache, "probe.sock"))
    if inside is None:
        return None
    with contextlib.suppress(OSError):
        os.unlink(os.path.join(cache, "probe.sock"))
    target = os.path.join(outside, "real.sock")
    srv = socket.socket(socket.AF_UNIX)  # слушает родитель, вне профиля
    srv.bind(target)
    srv.listen(5)
    link = os.path.join(cache, "link.sock")
    try:
        os.symlink(target, link)
        res = [inside, run("bind", os.path.join(outside, "x.sock")), run("connect", target), run("connect", link)]
    finally:
        srv.close()
        with contextlib.suppress(OSError):
            os.unlink(link)
    return res


def workshop_by_fact():
    """Песочница, роль и пересборка мастерской по факту на диске (metis-0899, вариант А): ~/ai/workshop нет — пишет
    в старую папку workshop в ~/projects, появилась — в новую (domains build --if-changed сам пересобирает)."""
    tmp = os.path.join(ROOT, "fact")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    old, new = os.path.join(tmp, "projects", "workshop"), os.path.join(tmp, "ai", "workshop")
    os.makedirs(os.path.join(old, "old-task"))
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    os.makedirs(os.path.join(tmp, "projects", "br"))
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    build = lambda *a: subprocess.run([py311(), "-I", RUN_PY, "domains", "build", *a], env=env, capture_output=True,
                                      text=True, timeout=120)
    aw = lambda: json.load(open(os.path.join(state, "settings", "workshop.json")))["sandbox"]["filesystem"]["allowWrite"]
    role = lambda: open(os.path.join(tmp, ".claude", "agents", "workshop.md"), encoding="utf-8").read()
    r = build()
    w = aw()
    check("мастерская без ~/ai/workshop: песочница пишет в старую папку workshop в ~/projects, новой нет",
          r.returncode == 0 and os.path.realpath(old) in w and not any(x.startswith(os.path.realpath(new)) for x in w)
          and "песочница workshop:" not in r.stderr)
    check("мастерская без ~/ai/workshop: роль — в старой папке",
          "~/projects/workshop/<задача>" in role() and "~/ai/workshop/<задача>" not in role())
    os.makedirs(new)
    r = build("--if-changed")
    w = aw()
    check("появилась ~/ai/workshop: --if-changed пересобрал, песочница пишет в новую, старой нет",
          r.returncode == 0 and os.path.realpath(new) in w and os.path.realpath(old) not in w)
    check("появилась ~/ai/workshop: роль — в новой папке",
          "~/ai/workshop/<задача>" in role() and "~/projects/workshop/<задача>" not in role())
    # копия правила в хуке ctx.py (ядро защит, moved.py грузить не может) совпадает с moved.workshop_root
    import importlib.util

    def load(name, rel):
        spec = importlib.util.spec_from_file_location(name, os.path.join(PLUGIN, rel))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    ctx, moved = load("ctx_ws", os.path.join("hooks", "ctx.py")), load("moved_ws", os.path.join("lib", "moved.py"))
    h = os.path.join(ROOT, "parity")
    os.makedirs(os.path.join(h, "ai"))
    os.makedirs(os.path.join(h, "elsewhere"))
    states = []
    states.append((ctx.workshop_root(h), moved.workshop_root(h)))               # новой нет
    os.symlink(os.path.join(h, "elsewhere"), os.path.join(h, "ai", "workshop"))
    states.append((ctx.workshop_root(h), moved.workshop_root(h)))               # новая — ссылка
    os.remove(os.path.join(h, "ai", "workshop"))
    os.makedirs(os.path.join(h, "ai", "workshop"))
    states.append((ctx.workshop_root(h), moved.workshop_root(h)))               # новая — папка
    check("ctx.workshop_root совпадает с moved.workshop_root: нет новой, ссылка, папка",
          all(a == b for a, b in states) and states[0][0] == os.path.join(h, "projects", "workshop")
          and states[1][0] == states[0][0] and states[2][0] == os.path.join(h, "ai", "workshop"))
    if not all(a == b for a, b in states):
        print("     ", states)


def main():
    workshop_by_fact()
    tmp = os.path.join(ROOT, "h")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    for d in ("projects/br", "ai/knowledge", "ai/workshop"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n'
                 '[[direction]]\nname = "mnemo-brain"\nfolders = ["~/ai/knowledge"]\n')
    # Library — симлинк (как на машине с кэшами на другом томе): в настройки должен идти настоящий путь, не раскрытый ~
    real_lib = os.path.join(ROOT, "reallib")
    os.makedirs(real_lib)
    os.symlink(real_lib, os.path.join(tmp, "Library"))
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    r = subprocess.run([py311(), "-I", RUN_PY, "domains", "build"], env=env, capture_output=True, text=True, timeout=120)
    check("domains build на временном HOME прошёл", r.returncode == 0)
    if r.returncode != 0:
        print(r.stderr)
        return
    out = os.path.join(state, "settings")
    win = lambda n: json.load(open(os.path.join(out, n + ".json")))  # noqa: E731
    cache = os.path.realpath(os.path.join(tmp, "Library", "Caches", "pantheon-sandbox", "workshop"))
    net = win("workshop")["sandbox"]["network"]
    check("workshop: allowUnixSockets — ровно настоящий путь кэша окна", net.get("allowUnixSockets") == [cache])
    check("workshop: кэш через симлинк Library записан настоящим путём (realpath, не expanduser)",
          cache != os.path.join(tmp, "Library", "Caches", "pantheon-sandbox", "workshop")
          and net.get("allowUnixSockets") == [cache])
    check("workshop: кэш окна существует (Claude Code ставит subpath на настоящий путь)", os.path.isdir(cache))
    check("workshop: allowLocalBinding и allowAllUnixSockets нет",
          "allowLocalBinding" not in net and "allowAllUnixSockets" not in net)
    check("workshop: сеть по-прежнему по списку доменов", isinstance(net.get("allowedDomains"), list))
    others = sorted(f[:-5] for f in os.listdir(out) if f.endswith(".json") and f != "workshop.json")
    check("координаторы athena-shop и mnemo-brain собраны", {"athena-shop", "mnemo-brain"} <= set(others))
    # с [sb-simplify] сокеты в своём кэше — у всех окон направлений; у задач расписания, Гестии и штаба — нет
    serv = [n for n in others if n.startswith("job-") or n in ("hestia", "hq")]
    bad = [n for n in serv if set(win(n)["sandbox"].get("network", {})) - {"allowedDomains"}]
    check(f"служебные окна ({len(serv)}): в network только allowedDomains — без сокетов и местных портов", not bad)
    check("окна направлений: сокеты — свой кэш", all(win(n)["sandbox"]["network"].get("allowUnixSockets") == [
        os.path.realpath(os.path.join(tmp, "Library", "Caches", "pantheon-sandbox", n))] for n in ("athena-shop", "mnemo-brain")))
    print(f"     путь кэша окна: {len(cache)} байт; на машине владельца ~/Library/Caches/pantheon-sandbox/workshop "
          "≈ 50 байт — до предела 104 остаётся ~50 на имя папки и сокета")

    outside = os.path.join(ROOT, "outside")
    os.makedirs(outside)
    got = seatbelt_probe(cache, outside)
    if got is None:
        print("skip проба seatbelt: вложенный sandbox-exec недоступен (запуск внутри песочницы) или не macOS.\n"
              "     Прогнать снаружи песочницы (терминал владельца, не окно роли) и вложить вывод в PR:\n"
              f"     /usr/bin/python3 -I {os.path.abspath(__file__)}   (и тем же python3.14 -I)")
    else:
        check(f"seatbelt: bind+connect в кэше окна проходит ({got[0]})", got[0] == "ok")
        check(f"seatbelt: bind вне кэша — EPERM ({got[1]})", got[1] == "errno 1")
        check(f"seatbelt: connect к сокету вне кэша напрямую — EPERM ({got[2]})", got[2] == "errno 1")
        check(f"seatbelt: connect через симлинк в кэше на сокет вне кэша — EPERM ({got[3]})", got[3] == "errno 1")


if __name__ == "__main__":
    main()
    print(f"\n{sum(results)}/{len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)
