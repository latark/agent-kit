#!/usr/bin/env python3
"""Тест служб по требованию (metis-0151): сокет у launchd, прокси lib/ondemand.py, qmd поднимается запросом.

Запуск: python3 -I plugins/pantheon/tests/test_svc_ondemand.py  (код выхода 0 — все прошли), на 3.9 и 3.14.
Живой launchd не трогается: слушающий сокет создаёт сам тест и передаёт прокси через PANTHEON_LISTEN_FDS — так же,
как launchd держит сокет и отдаёт его службе. qmd подменён маленьким HTTP-сервером (fake_qmd), тик — PANTHEON_DRYRUN.
Где слушать порт нельзя (песочница окна: bind → EPERM), сквозная часть через настоящие сокеты пропускается, а те же
свойства проверяет прокси в процессе теста: соединения — socketpair, qmd — настоящий подпроцесс (test_proxy_inproc).
"""
import collections
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile
import atexit as _atexit
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="ondemand-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(HERE, "lib")
PAN = os.path.join(LIB, "pantheon.py")
T0 = 1_792_000_000
OK, FAIL = [], []
IDLE = 2  # секунды простоя в тесте (в жизни — idle_min, 30 мин)

# Поддельный qmd: `--index index mcp --http --port N --host H`, пишет «pid порт» в FAKE_PIDS и отвечает на POST /mcp
# JSON-ом с заголовком Host запроса — видно, что ответ пришёл от него и что Host клиента дошёл как есть.
FAKE = r'''
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
argv = sys.argv[1:]
port = int(argv[argv.index("--port") + 1]); host = argv[argv.index("--host") + 1]
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.dumps({"fake": "qmd", "pid": os.getpid(), "host": self.headers.get("Host"), "port": port}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
srv = HTTPServer((host, port), H)
with open(os.environ["FAKE_PIDS"], "a") as fh:
    fh.write(f"{os.getpid()} {port}\n")
srv.serve_forever()
'''


def can_listen():
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
        return True
    except PermissionError:
        return False


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    if not cond:
        print(f"НЕ ПРОШЁЛ: {name} {detail}")


def fake_qmd(tmp):
    p = os.path.join(tmp, "fakeqmd")
    with open(p, "w") as fh:
        fh.write(f"#!{sys.executable} -I\n{FAKE}")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
    return p


def listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(16)
    return s


def pids(path):
    if not os.path.exists(path):
        return []
    return [int(ln.split()[0]) for ln in open(path) if ln.strip()]


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def post(port, timeout=30):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=b'{"jsonrpc":"2.0","id":1,"method":"x"}',
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def wait_dead(pid, t=10):
    end = time.monotonic() + t
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


# --- прокси напрямую (lib/ondemand.py на этом python: 3.9 или 3.14) ---------------------------------------------------
PROXY = r'''
import os, subprocess, sys
sys.path.insert(0, sys.argv[1])
import ondemand
fake, idle = sys.argv[2], float(sys.argv[3])
start = lambda port: subprocess.Popen([fake, "--index", "index", "mcp", "--http", "--port", str(port),
                                       "--host", "127.0.0.1"], stdin=subprocess.DEVNULL)
sys.exit(ondemand.Proxy(ondemand.listen_sockets(), start, idle).run())
'''


def start_proxy(lst, fake, pidfile, log):
    env = {"PATH": os.environ["PATH"], "PANTHEON_LISTEN_FDS": str(lst.fileno()), "FAKE_PIDS": pidfile,
           "TMPDIR": _ROOT}
    return subprocess.Popen([sys.executable, "-I", "-c", PROXY, LIB, fake, str(IDLE)], env=env,
                            pass_fds=(lst.fileno(),), stdout=log, stderr=log)


def test_proxy():
    with tempfile.TemporaryDirectory() as tmp:
        fake, pidfile = fake_qmd(tmp), os.path.join(tmp, "pids")
        lst = listener()
        lport = lst.getsockname()[1]
        with open(os.path.join(tmp, "proxy.log"), "w") as log:
            proxy = start_proxy(lst, fake, pidfile, log)
            time.sleep(IDLE / 2)
            check("без запроса процесса qmd нет", proxy.poll() is None and pids(pidfile) == [], str(pids(pidfile)))
            try:
                code, body = post(lport)
            except OSError as e:
                code, body = None, str(e)
            ps = pids(pidfile)
            check("первый запрос поднимает qmd и получает его ответ",
                  code == 200 and isinstance(body, dict) and body.get("fake") == "qmd" and ps == [body.get("pid")]
                  and alive(ps[0]), f"{code} {body} {ps}")
            check("Host клиента доходит до qmd как есть (порт сокета, а не внутренний)",
                  isinstance(body, dict) and body.get("host") == f"127.0.0.1:{lport}" and body.get("port") != lport,
                  str(body))
            code2, body2 = post(lport)
            check("второй запрос — тот же qmd, без нового запуска", code2 == 200 and body2.get("pid") == ps[0]
                  and pids(pidfile) == ps, f"{body2} {pids(pidfile)}")
            # молчащий поток (как subscriptions/listen у клиентов MCP) простою не мешает
            silent = socket.create_connection(("127.0.0.1", lport))
            silent.sendall(b"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 100\r\n\r\n")
            try:
                rc = proxy.wait(IDLE * 5)
            except subprocess.TimeoutExpired:
                rc = None
            check("после простоя прокси выходит сам (код 0), хотя соединение открыто", rc == 0, str(rc))
            check("после простоя qmd выходит", wait_dead(ps[0]), str(ps))
            silent.settimeout(5)
            try:
                closed = silent.recv(10) == b""
            except OSError:
                closed = True
            silent.close()
            check("молчащее соединение закрыто при выходе", closed)
            # сокет остаётся у «launchd» (у теста): запрос ждёт в очереди, следующий запуск службы его обслужит
            res = {}

            def client():
                try:
                    res["r"] = post(lport)
                except OSError as e:
                    res["r"] = (None, str(e))
            t = threading.Thread(target=client)
            t.start()
            time.sleep(0.3)
            proxy = start_proxy(lst, fake, pidfile, log)
            t.join(30)
            r = res.get("r", (None, "нет ответа"))
            check("запрос, пришедший без прокси, обслужен следующим запуском", r[0] == 200 and len(pids(pidfile)) == 2,
                  f"{r} {pids(pidfile)}")
            proxy.send_signal(signal.SIGTERM)
            try:
                rc = proxy.wait(15)
            except subprocess.TimeoutExpired:
                proxy.kill()
                rc = None
            check("SIGTERM (bootout) гасит и прокси, и qmd", rc == 0 and wait_dead(pids(pidfile)[-1]),
                  f"{rc} {pids(pidfile)}")
        lst.close()


def test_backend_fails():
    """qmd не поднялся (сразу вышел) — соединение закрыто, прокси не висит и после простоя выходит."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = os.path.join(tmp, "badqmd")
        with open(bad, "w") as fh:
            fh.write("#!/bin/sh\nexit 3\n")
        os.chmod(bad, 0o755)
        lst = listener()
        with open(os.path.join(tmp, "proxy.log"), "w") as log:
            proxy = start_proxy(lst, bad, os.path.join(tmp, "pids"), log)
            try:
                post(lst.getsockname()[1], timeout=10)
                got = "ответ"
            except OSError as e:
                got = type(e).__name__
            try:
                rc = proxy.wait(IDLE * 5)
            except subprocess.TimeoutExpired:
                proxy.kill()
                rc = None
        text = open(os.path.join(tmp, "proxy.log")).read()
        check("qmd не поднялся — клиенту закрытое соединение, в журнале код выхода, прокси вышел",
              got != "ответ" and "кодом 3" in text and rc == 0, f"{got} {rc} {text}")
        lst.close()


# --- прокси в процессе теста, без слушающих сокетов (идёт и в песочнице) ---------------------------------------------
# qmd — настоящий подпроцесс: через 0,2 с («запуск») пишет «pid порт» и спит. Соединение с ним — socketpair, на другом
# конце которого отвечает HTTP-обработчик теста от имени этого pid; пока процесса нет или он умер — «отказано».
SLEEPER = r'''
import os, sys, time
argv = sys.argv[1:]
port = argv[argv.index("--port") + 1]
time.sleep(0.2)
with open(os.environ["FAKE_PIDS"], "a") as fh:
    fh.write(f"{os.getpid()} {port}\n")
while True:
    time.sleep(60)
'''


class FakeListener:
    """Слушающий сокет без bind: dial() кладёт соединение в очередь и будит select, accept() его отдаёт."""

    def __init__(self):
        self.r, self.w = socket.socketpair()
        self.pending = collections.deque()

    def fileno(self):
        return self.r.fileno()

    def setblocking(self, flag):
        self.r.setblocking(flag)

    def accept(self):
        self.r.recv(1)
        return self.pending.popleft(), None

    def dial(self):
        a, b = socket.socketpair()
        self.pending.append(b)
        self.w.send(b"x")
        return a

    def close(self):
        pass  # сокет «launchd» живёт дальше, как настоящий


def answer(sock, pid):
    """HTTP-ответ поддельного qmd на одном соединении: JSON с pid и заголовком Host."""
    buf = b""
    try:
        while b"\r\n\r\n" not in buf:
            d = sock.recv(65536)
            if not d:
                return
            buf += d
        head, _, rest = buf.partition(b"\r\n\r\n")
        hdr = dict(ln.split(": ", 1) for ln in head.decode().split("\r\n")[1:] if ": " in ln)
        while len(rest) < int(hdr.get("Content-Length") or 0):
            d = sock.recv(65536)
            if not d:
                return
            rest += d
        body = json.dumps({"fake": "qmd", "pid": pid, "host": hdr.get("Host")}).encode()
        sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
                     b"Content-Length: %d\r\n\r\n" % len(body) + body)
    except OSError:
        pass
    finally:
        sock.close()


def raw_post(lst, timeout=30):
    """POST /mcp через FakeListener → (код, JSON) или (None, причина)."""
    c = lst.dial()
    c.settimeout(timeout)
    data = b""
    try:
        c.sendall(b"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:8181\r\nContent-Length: 2\r\n\r\n{}")
        while True:
            d = c.recv(65536)
            if not d:
                break
            data += d
    except OSError as e:
        return None, str(e)
    finally:
        c.close()
    head, _, body = data.partition(b"\r\n\r\n")
    if not head.startswith(b"HTTP/1.1 200"):
        return None, data[:200]
    return 200, json.loads(body)


def test_proxy_inproc():
    sys.path.insert(0, LIB)
    import ondemand
    with tempfile.TemporaryDirectory() as tmp:
        pidfile = os.path.join(tmp, "pids")
        sleeper = os.path.join(tmp, "sleeper")
        with open(sleeper, "w") as fh:
            fh.write(f"#!{sys.executable} -I\n{SLEEPER}")
        os.chmod(sleeper, 0o755)
        env = dict(os.environ, FAKE_PIDS=pidfile)
        ports = iter(range(40001, 40100))
        log = open(os.path.join(tmp, "qmd.log"), "w")

        def start(port):
            return subprocess.Popen([sleeper, "--index", "index", "mcp", "--http", "--port", str(port), "--host",
                                     "127.0.0.1"], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)

        def connect(port):
            live = []
            if os.path.exists(pidfile):
                live = [int(p) for p, q in (ln.split() for ln in open(pidfile) if ln.strip())
                        if int(q) == port and alive(int(p))]
            if not live:
                raise ConnectionRefusedError("qmd не слушает")
            a, b = socket.socketpair()
            threading.Thread(target=answer, args=(b, live[-1]), daemon=True).start()
            return a

        lst = FakeListener()
        res = {}

        def go(key):
            p = ondemand.Proxy([lst], start, IDLE, connect=connect, new_port=lambda: next(ports))
            res[key + "-proxy"] = p
            res[key] = p.run()
        t = threading.Thread(target=go, args=("a",), daemon=True)
        t.start()
        time.sleep(IDLE / 2)
        check("в процессе: без запроса процесса qmd нет", t.is_alive() and pids(pidfile) == [], str(pids(pidfile)))
        code, body = raw_post(lst)
        ps = pids(pidfile)
        check("в процессе: первый запрос поднимает qmd и получает его ответ",
              code == 200 and isinstance(body, dict) and ps == [body.get("pid")] and alive(ps[0]), f"{code} {body} {ps}")
        check("в процессе: Host клиента доходит как есть",
              isinstance(body, dict) and body.get("host") == "127.0.0.1:8181", str(body))
        code2, body2 = raw_post(lst)
        check("в процессе: второй запрос — тот же qmd", code2 == 200 and isinstance(body2, dict)
              and body2.get("pid") == ps[0] and pids(pidfile) == ps, f"{body2} {pids(pidfile)}")
        silent = lst.dial()
        silent.sendall(b"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 100\r\n\r\n")
        t.join(IDLE * 5)
        check("в процессе: после простоя прокси выходит (код 0), хотя соединение открыто",
              not t.is_alive() and res.get("a") == 0, str(res))
        check("в процессе: после простоя qmd выходит", bool(ps) and wait_dead(ps[0]), str(ps))
        silent.settimeout(5)
        try:
            closed = silent.recv(10) == b""
        except OSError:
            closed = True
        silent.close()
        check("в процессе: молчащее соединение закрыто при выходе", closed)
        # запрос пришёл, когда прокси нет: ждёт в очереди сокета, следующий запуск его обслужит
        out = {}
        c = threading.Thread(target=lambda: out.setdefault("r", raw_post(lst)))
        c.start()
        time.sleep(0.3)
        t = threading.Thread(target=go, args=("b",), daemon=True)
        t.start()
        c.join(30)
        r = out.get("r", (None, "нет ответа"))
        check("в процессе: запрос без прокси обслужен следующим запуском", r[0] == 200 and len(pids(pidfile)) == 2,
              f"{r} {pids(pidfile)}")
        if "b-proxy" in res:
            res["b-proxy"].stop.set()  # как SIGTERM от bootout
        t.join(15)
        check("в процессе: остановка гасит и прокси, и qmd", not t.is_alive() and res.get("b") == 0
              and bool(pids(pidfile)) and wait_dead(pids(pidfile)[-1]), f"{res} {pids(pidfile)}")
        # keep-alive (ревью #57, п. 1): одно соединение, байты идут чаще простоя — простой считается по байтам
        # пересылки (touch в _pipe), а не только по новым соединениям: прокси не рвёт клиента посреди работы

        def echo(s):
            try:
                while True:
                    d = s.recv(65536)
                    if not d:
                        break
                    s.sendall(d)
            except OSError:
                pass
            finally:
                s.close()

        def connect_echo(port):
            live = [int(p) for p, q in (ln.split() for ln in open(pidfile) if ln.strip())
                    if int(q) == port and alive(int(p))] if os.path.exists(pidfile) else []
            if not live:
                raise ConnectionRefusedError("qmd не слушает")
            a, b = socket.socketpair()
            threading.Thread(target=echo, args=(b,), daemon=True).start()
            return a

        def go_echo():
            p = ondemand.Proxy([lst], start, IDLE, connect=connect_echo, new_port=lambda: next(ports))
            res["k-proxy"] = p
            res["k"] = p.run()
        before = len(pids(pidfile))
        t = threading.Thread(target=go_echo, daemon=True)
        t.start()
        k = lst.dial()
        k.settimeout(10)
        # metis-0365: мерило — сколько секунд соединение прожило без обрыва, а не сколько ответов уложилось в 3 простоя.
        # Счёт ответов краснел без поломки (8–10 из ≥11 в 10 логах автоустановки и 10 из 10 под QoS background):
        # запуск qmd первым обменом и опоздание sleep при слиянии таймеров в фоне съедают интервалы. Первый обмен
        # поднимает qmd — отсчёт с его ответа; пауза IDLE/8 — запас 7/8 простоя на опоздание; худшая пауза — в детали.
        served, why, worst = 0, "", 0.0
        try:
            k.sendall(b"ping")
            why = "" if k.recv(10) == b"ping" else "первый обмен без ответа"
        except OSError as e:
            why = f"первый обмен: {e}"
        t0 = last = time.monotonic()
        while not why and time.monotonic() - t0 < IDLE * 3:
            time.sleep(IDLE / 8)
            worst = max(worst, time.monotonic() - last)
            try:
                k.sendall(b"ping")
                if k.recv(10) != b"ping":
                    why = "соединение закрыто"
                    break
            except OSError as e:
                why = str(e)
                break
            served, last = served + 1, time.monotonic()
        held = last - t0
        check("в процессе: keep-alive — байты одного соединения держат прокси дольше простоя",
              not why and held >= IDLE * 3 - IDLE / 8 and t.is_alive() and len(pids(pidfile)) == before + 1,
              f"оборвалось: {why or 'нет'}; соединение жило {held:.2f} с из {IDLE * 3} (простой {IDLE}), ответов "
              f"{served}, худшая пауза {worst:.2f} с, прокси жив: {t.is_alive()}, {pids(pidfile)}")
        t.join(IDLE * 5)
        try:
            closed = k.recv(10) == b""
        except OSError:
            closed = True
        k.close()
        check("в процессе: keep-alive замолчал — после простоя прокси выходит и закрывает соединение",
              not t.is_alive() and res.get("k") == 0 and closed and wait_dead(pids(pidfile)[-1]), f"{res} {closed}")
        log.close()


# --- весь путь службы: pantheon qmd serve (Python 3.11+) ------------------------------------------------------------
def env_for(tmp, extra=None):
    home = os.path.join(tmp, "home")
    pan, state = os.path.join(home, "ai", "pantheon"), os.path.join(tmp, "state")
    os.makedirs(pan, exist_ok=True)
    env = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pan, "PANTHEON_STATE": state,
           "PANTHEON_NOW": str(T0), "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_ALERTS_IN_DRYRUN": "1", "TMPDIR": _ROOT}
    env.update(extra or {})
    return home, pan, state, env


def test_qmd_serve():
    with tempfile.TemporaryDirectory() as tmp:
        lst = listener()
        lport = lst.getsockname()[1]
        pidfile = os.path.join(tmp, "pids")
        home, pan, state, env = env_for(tmp, {"PANTHEON_QMD_BIN": fake_qmd(tmp), "FAKE_PIDS": pidfile,
                                              "PANTHEON_LISTEN_FDS": str(lst.fileno()), "PANTHEON_SVC_IDLE": str(IDLE)})
        open(os.path.join(pan, "qmd.toml"), "w").write(f"port = {lport}\n")
        logp = os.path.join(tmp, "serve.log")
        with open(logp, "w") as log:
            proxy = subprocess.Popen([PY311, "-I", PAN, "qmd", "serve"], env=env, pass_fds=(lst.fileno(),),
                                     stdout=log, stderr=log)
            time.sleep(IDLE / 2)
            check("qmd serve по сокету: без запроса процесса qmd нет", proxy.poll() is None and pids(pidfile) == [],
                  open(logp).read())
            try:
                code, body = post(lport)
            except OSError as e:
                code, body = None, str(e)
            ps = pids(pidfile)
            check("qmd serve по сокету: первый запрос поднимает qmd и получает ответ",
                  code == 200 and isinstance(body, dict) and ps == [body.get("pid")], f"{code} {body} {ps}")
            try:
                rc = proxy.wait(IDLE * 5)
            except subprocess.TimeoutExpired:
                proxy.kill()
                rc = None
            check("qmd serve по сокету: после простоя выходят и прокси, и qmd",
                  rc == 0 and ps and wait_dead(ps[0]), f"{rc} {ps} {open(logp).read()}")
        text = open(logp).read()
        check("qmd serve: порт сокета совпал с qmd.toml — без предупреждения", "qmd.toml port" not in text, text)
        lst.close()


def test_qmd_serve_no_launchd():
    """Служба по требованию запущена не launchd и без готового сокета — внятная ошибка, а не трасса."""
    with tempfile.TemporaryDirectory() as tmp:
        home, pan, state, env = env_for(tmp, {"PANTHEON_QMD_BIN": fake_qmd(tmp), "PANTHEON_SVC_SOCKET": "Listeners"})
        open(os.path.join(pan, "qmd.toml"), "w").write("port = 8199\n")
        r = subprocess.run([PY311, "-I", PAN, "qmd", "serve"], env=env, capture_output=True, text=True, timeout=60)
        check("qmd serve по требованию не под launchd — код 1 и причина", r.returncode == 1
              and "нет сокета службы по требованию" in r.stderr and "Traceback" not in r.stderr, r.stderr)


# --- тик и пульт: служба по требованию -------------------------------------------------------------------------------
SCHED = """primary_host = "mac-b"
[[service]]
name = "qmd"
command = "pantheon qmd serve"
socket = 8181
idle_min = 20
[[service]]
name = "keep"
command = "pantheon qmd serve"
[[service]]
name = "badsock"
command = "pantheon qmd serve"
socket = 80
"""


def run(env, *args):
    return subprocess.run([PY311, "-I", PAN, *args], env=env, capture_output=True, text=True, timeout=60)


def dry(state):
    p = os.path.join(state, "dryrun.log")
    lines = [ln.split(None, 1)[1].strip() for ln in open(p)] if os.path.exists(p) else []
    return [ln for ln in lines if ln.startswith("svc-")]


def test_tick():
    with tempfile.TemporaryDirectory() as tmp:
        home, pan, state, env = env_for(tmp)
        open(os.path.join(pan, "schedule.toml"), "w").write(SCHED)
        r = run(env, "tick")
        agents = os.path.join(home, "Library", "LaunchAgents")
        text = open(os.path.join(agents, "pantheon.svc.qmd.plist")).read()
        check("служба по требованию: plist с сокетом 127.0.0.1:8181, без KeepAlive и RunAtLoad",
              "<key>Sockets</key>" in text and "<string>127.0.0.1</string>" in text
              and "<key>SockServiceName</key><string>8181</string>" in text and "KeepAlive" not in text
              and "RunAtLoad" not in text and "<string>service-run</string><string>qmd</string>" in text, text)
        keep = open(os.path.join(agents, "pantheon.svc.keep.plist")).read()
        check("обычная служба — по-прежнему KeepAlive, без сокета",
              "<key>KeepAlive</key><true/>" in keep and "Sockets" not in keep, keep)
        check("socket = 80 — служба не ставится", "svc-bootstrap badsock" not in dry(state)
              and not os.path.exists(os.path.join(agents, "pantheon.svc.badsock.plist")), str(dry(state)))
        # launchd: обе загружены, процессов нет (у службы по требованию — ждёт запроса)
        with open(os.path.join(state, "svc-dry.json"), "w") as fh:
            json.dump({"qmd": 0, "keep": 0}, fh)
        run(env, "tick")
        log = dry(state)
        alerts_p = os.path.join(pan, "alerts.md")
        alerts = open(alerts_p).read() if os.path.exists(alerts_p) else ""
        check("загружена без процесса: служба по требованию — без kickstart и без тревоги",
              "svc-kickstart qmd" not in log and "служба qmd не работает" not in alerts, f"{log} {alerts}")
        check("загружена без процесса: обычная служба — kickstart и тревога, как раньше",
              "svc-kickstart keep" in log and "служба keep не работает" in alerts, f"{log} {alerts}")
        # ревью #57, п. 2: по требованию, процесса нет, последний запуск упал (нет qmd → код 3) — тревога

        def tick_exit(code):
            with open(os.path.join(state, "svc-dry.json"), "w") as fh:
                json.dump({"qmd": 0, "keep": 4242, "exit": {"qmd": code}}, fh)
            run(env, "tick")
            return open(alerts_p).read().count("служба по требованию qmd падает при запуске")
        n3 = tick_exit(3)
        check("по требованию, последний код выхода 3 — тревога с кодом, без kickstart",
              n3 == 1 and "последний код выхода 3" in open(alerts_p).read()
              and "svc-kickstart qmd" not in dry(state), f"{n3} {dry(state)}")
        check("тот же код на следующем проходе — тревога не повторяется", tick_exit(3) == 1)
        n0 = tick_exit(0)
        check("код 0 (выход по простою) — новой тревоги нет, а следующий сбой снова виден",
              n0 == 1 and tick_exit(3) == 2, str(n0))
        tick_exit(0)
        with open(os.path.join(state, "svc-dry.json"), "w") as fh:
            json.dump({"qmd": 0, "keep": 4242}, fh)
        out = run(env, "jobs").stdout
        check("pantheon jobs: «по требованию: ждёт запроса на 127.0.0.1:8181»",
              "по требованию: ждёт запроса на 127.0.0.1:8181" in out, out)
        check("pantheon jobs: плохой socket — причина видна", "socket: нужен порт" in out, out)
        st = run(env, "status").stdout
        check("pantheon status: служба по требованию без процесса — не «НЕ ИДЁТ»",
              "служба qmd: НЕ ИДЁТ" not in st and "служба qmd: НЕ ЗАГРУЖЕНА" not in st, st)
        with open(os.path.join(state, "svc-dry.json"), "w") as fh:
            json.dump({"qmd": 777, "keep": 4242}, fh)
        out = run(env, "jobs").stdout
        check("pantheon jobs: идёт по запросу — pid и простой", "идёт по запросу, pid 777" in out and "20 мин" in out,
              out)
        r = run(env, "jobs", "pause", "qmd")
        check("пауза снимает службу по требованию сразу", r.returncode == 0 and dry(state)[-1] == "svc-bootout qmd"
              and not os.path.exists(os.path.join(agents, "pantheon.svc.qmd.plist")), f"{dry(state)} {r.stderr}")


if __name__ == "__main__":
    test_proxy_inproc()
    listen = can_listen()
    if listen:
        test_proxy()
        test_backend_fails()
    else:
        print("слушать порт нельзя (bind → EPERM, песочница) — сквозная часть через сокеты и qmd serve пропущены")
    if PY311:
        if listen:
            test_qmd_serve()
        test_qmd_serve_no_launchd()
        test_tick()
    else:
        print("нет Python 3.11+ — части с CLI pantheon пропущены")
    print(f"{len(OK)} из {len(OK) + len(FAIL)} прошли")
    sys.exit(1 if FAIL else 0)
