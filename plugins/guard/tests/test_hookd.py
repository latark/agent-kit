#!/usr/bin/env python3
"""Демон хуков guard (metis-0330, этап 2, ступень 2): hooks/daemon.py, клиент hooks/hookd-client.c, оболочка
hooks/hookd.sh, сборка hooks/hookd-build.sh, шаблон службы launchd/pantheon.svc.hookd.plist.in.

Запуск: python3 -I plugins/guard/tests/test_hookd.py   (код выхода 0 — все прошли)
Всё — во временной папке с коротким путём (сокет Unix — не длиннее 103 байт), HOME подменён; launchd, настоящие
~/.claude, ~/Library и ~/.cache не трогаются. Демоны теста запускаются с --socket и убиваются в конце (SIGKILL).
- оболочка: без PANTHEON_HOOKD=1 — медленный путь, демона не спрашивает; клиента нет, он не исполняемый или мусор с +x —
  медленный путь с тем же stdin и строка причины; клиента нет — он собирается в фоне в кэш вне дерева плагина;
- сверка решений: события и контексты test_context (хук плагина, --managed, --strict, роль hestia, агент dev-opus, два
  HOME, TMPDIR, GUARD_OFF) медленным путём и через демон — код, stdout, stderr и файлы в HOME совпадают, откатов нет;
- подпроцесс во внуке (git и gh push в принятый PR, шлюз слияния; subprocess, fork, posix_spawn, exec, system) —
  «F spawn» до запуска программы и медленный путь; Read, Write и Bash без подпроцессов демон решает сам;
- строгий guard не теряет отказов: демон загружен без --strict, режим берётся из argv каждого вызова (находка спайка);
- отказы демона и клиента (фальшивые серверы, нет сокета, права папки, отказ «F <причина>», зависание, обрыв, большой
  запрос, чужая версия, чужое дерево, чужой uid, кодировка, локаль, убитый внук, устаревшие правила) — тот же ответ, что
  у медленного пути, и строка причины в hookd-fallback.log без текста события;
- канарейка: 1 вызов из N обоими путями, расхождение — строка с хешем события (FNV-1a 64) и оба решения;
- сборка: SRC в hookd.sh — SHA-256 исходника клиента; несовпадение — метка .failed, без сборки;
- служба: шаблон plist — сокет 0600 в ~/.cache/pantheon/hookd, без KeepAlive, ThrottleInterval 1–2 с.
"""
import ast
import hashlib
import json
import os
import plistlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
HOOKS = os.path.join(PLUGIN, "hooks")
LAUNCHER = os.path.join(HOOKS, "python.sh")
GUARD = os.path.join(HOOKS, "guard.py")
WRAP = os.path.join(HOOKS, "hookd.sh")
BUILD = os.path.join(HOOKS, "hookd-build.sh")
DAEMON = os.path.join(HOOKS, "daemon.py")
CLIENT_SRC = os.path.join(HOOKS, "hookd-client.c")
INSTALL = os.path.join(PLUGIN, "scripts", "hookd-install.sh")
SUB_TIMEOUT = 60
SOCK_REL = os.path.join(".cache", "pantheon", "hookd", "hookd.sock")
sys.path.insert(0, HERE)
import test_context as TC  # noqa: E402 — события и контексты сверки решений — те же, что у ступени 1

results = []
PROCS = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:900]))


def src_hash():
    with open(CLIENT_SRC, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def src_const(path=WRAP):
    with open(path, encoding="utf-8") as fh:
        m = re.search(r"(?m)^SRC=([0-9a-f]{16})$", fh.read())
    return m.group(1) if m else None


def base_env(home, **kw):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "en_US.UTF-8", "HOME": home}
    env.update(kw)
    return env


def fb_log(home):
    return os.path.join(home, ".local", "state", "pantheon", "logs", "hookd-fallback.log")


def fb_lines(home):
    try:
        with open(fb_log(home), encoding="utf-8") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def reasons(home):
    return [ln.split("\t")[1] for ln in fb_lines(home) if "\t" in ln]


def hookd_dir(home):
    return os.path.join(home, ".cache", "pantheon", "hookd")


def install(home, client, sock=None):
    """Клиент этой версии исходника и (если sock) ссылка hookd.sock → сокет демона — в кэше HOME, папка 0700."""
    d = hookd_dir(home)
    os.makedirs(os.path.join(d, "bin"), exist_ok=True)
    os.chmod(d, 0o700)
    dst = os.path.join(d, "bin", "client-" + src_hash())
    if client and not os.path.exists(dst):
        try:
            os.link(client, dst)  # тот же файл: macOS проверяет новый исполняемый файл при первом запуске (~0,4 с)
        except OSError:
            shutil.copy2(client, dst)
        shutil.copyfile(client + ".sum", dst + ".sum")  # метка SHA-256: без неё оболочка клиент не запустит
    if sock:
        try:
            os.unlink(os.path.join(d, "hookd.sock"))
        except FileNotFoundError:
            pass
        os.symlink(sock, os.path.join(d, "hookd.sock"))
    return d


def run(argv, ev, env, cwd, raw=None):
    data = raw if raw is not None else json.dumps(ev, ensure_ascii=False).encode()
    t = time.perf_counter()
    r = subprocess.run(["/bin/sh", *argv], input=data, capture_output=True, env=env, cwd=cwd, timeout=SUB_TIMEOUT)
    return (r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")), \
        time.perf_counter() - t


def slow(args, ev, env, cwd, raw=None, hooks=HOOKS):
    return run([os.path.join(hooks, "python.sh"), os.path.join(hooks, "guard.py"), *args], ev, env, cwd, raw)


def wrap(args, ev, env, cwd, raw=None, hooks=HOOKS, canary="0"):
    env = dict(env, PANTHEON_HOOKD="1")
    if canary is not None:
        env["PANTHEON_HOOKD_CANARY"] = canary
    return run([os.path.join(hooks, "hookd.sh"), "guard", *args], ev, env, cwd, raw)


def wrap_argv(args, hooks=HOOKS):
    return [os.path.join(hooks, "hookd.sh"), "guard", *args]


def run_late(argv, ev, env, cwd, delay):
    """Как run, но stdin закрывается через delay с после старта: клиент ждёт его, а срок демона уже идёт."""
    t = time.perf_counter()
    p = subprocess.Popen(["/bin/sh", *argv], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=env, cwd=cwd)
    p.stdin.write(json.dumps(ev, ensure_ascii=False).encode())
    p.stdin.flush()
    time.sleep(delay)
    out, err = p.communicate(timeout=SUB_TIMEOUT)
    return (p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")), time.perf_counter() - t


def dec(res):
    return TC.dec(res)


def start_daemon(sock, home, hooks=HOOKS, extra=(), logname="daemon"):
    log = open(os.path.join(os.path.dirname(home), logname + ".log"), "ab")
    p = subprocess.Popen(["/bin/sh", os.path.join(hooks, "python.sh"), os.path.join(hooks, "daemon.py"),
                          "--socket", sock, "--idle", "300", *extra], env=base_env(home), stdout=log, stderr=log)
    PROCS.append(p)
    end = time.monotonic() + 30
    while time.monotonic() < end and not os.path.exists(sock) and p.poll() is None:
        time.sleep(0.02)
    return p


def stop(p):
    if p.poll() is None:
        p.send_signal(signal.SIGKILL)
    p.wait(timeout=30)


def plugin_version(root=PLUGIN):
    with open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
        return json.load(fh)["version"]


def raw_call(sock, hdr=None, body=b"", line=None, timeout=15):
    """Запрос по протоколу G2 руками: ответ демона — строка «A…»/«X …»/«F …» (без перевода строки)."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sock)
        f = s.makefile("rb")
        first = f.readline().decode().strip()
        if first != "A":
            return first
        h = json.dumps(hdr).encode() if hdr is not None else b""
        s.sendall((line or f"G2 {len(h)} {len(body)}\n").encode() + h + body)
        return f.readline().decode().strip()
    finally:
        s.close()


class Fake:
    """Фальшивый демон на сокете: поведение — функция от соединения; считает соединения."""

    def __init__(self, path, behaviour):
        self.path, self.behaviour, self.count = path, behaviour, 0
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.bind(path)
        os.chmod(path, 0o600)
        self.s.listen(16)
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                c, _ = self.s.accept()
            except OSError:
                return
            self.count += 1
            threading.Thread(target=self.one, args=(c,), daemon=True).start()

    def one(self, c):
        try:
            self.behaviour(c)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    def close(self):
        try:
            self.s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.s.close()


def read_request(c):
    f = c.makefile("rb")
    parts = f.readline().split()
    f.read(int(parts[1]) + int(parts[2]))
    return f


def b_close(c):
    pass


def b_garbage(c):
    c.sendall(b"A\nZZZ nonsense\n")


def b_hang(c):
    time.sleep(3)


def b_ack_die(c):
    c.sendall(b"A\n")
    time.sleep(0.05)


def b_short(c):
    c.sendall(b"A\n")
    read_request(c)
    c.sendall(b'X 0 500 0\n{"partial')


def b_f_stale(c):
    c.sendall(b"F stale\n")


def b_f_bad(c):
    c.sendall(b"F Bad!reason\n")


def b_ack_hang(c):
    c.sendall(b"A\n")
    read_request(c)
    time.sleep(10)


def b_ack_noread(c):
    """«Принят» и завис: запрос не читает, сокет держит дольше срока клиента (буфер AF_UNIX на macOS ~8 КБ)."""
    c.sendall(b"A\n")
    time.sleep(15)


def b_allow(c):
    c.sendall(b"A\n")
    read_request(c)
    c.sendall(b"X 0 0 0\n")


def b_allow_late(c):
    """«Пропустить» через 2,5 с: дольше CANARY_MS клиента (2 с) — канарейка не идёт."""
    c.sendall(b"A\n")
    read_request(c)
    time.sleep(2.5)
    c.sendall(b"X 0 0 0\n")


def b_x126(c):
    c.sendall(b"A\n")
    read_request(c)
    c.sendall(b"X 126 0 0\n")


def fnv1a(data):
    h = 1469598103934665603
    for b in data:
        h = ((h ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


LINE_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\t[a-z-]{1,32}")
CANARY_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\tcanary-diff\t[0-9a-f]{16}\tslow=\d+:(allow|ask|deny)"
                       r"\tdaemon=\d+:(allow|ask|deny)")


# --- без клиента: SRC, оболочка без флага, служба ------------------------------------------------------------------

def test_static(root):
    check("SRC в hookd.sh — первые 16 знаков SHA-256 hookd-client.c", src_const() == src_hash(),
          (src_const(), src_hash()))
    with open(WRAP, encoding="utf-8") as fh:
        body = fh.read()
    code = [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]
    check("оболочка не делает exec клиента (только медленного пути)",
          all('"$c"' not in ln or "exec" not in ln for ln in code) and any(ln.strip().startswith('"$c"') for ln in code),
          [ln for ln in code if '"$c"' in ln])
    # шаблон службы
    home = os.path.join(root, "svc")
    os.makedirs(home)
    r = subprocess.run(["/bin/sh", INSTALL, "--print"], env=base_env(home), capture_output=True, timeout=SUB_TIMEOUT)
    try:
        pl = plistlib.loads(r.stdout)
    except Exception as e:  # noqa: BLE001
        pl = {"error": repr(e)}
    lst = ((pl.get("Sockets") or {}).get("Listeners") or {})
    check("hookd-install.sh --print: plist без меток @…@, сокет 0600 в ~/.cache/pantheon/hookd, без KeepAlive, "
          "ThrottleInterval 1–2 с, первый процесс pantheon-hookd (папка hooks этого дерева)",
          r.returncode == 0 and b"@" not in r.stdout.replace(b"<?xml", b"")
          and pl.get("Label") == "pantheon.svc.hookd"
          and lst.get("SockPathName") == os.path.join(home, SOCK_REL) and lst.get("SockPathMode") == 0o600
          and lst.get("SockFamily") == "Unix" and lst.get("SockType") == "stream"
          and "KeepAlive" not in pl and "RunAtLoad" not in pl and 1 <= pl.get("ThrottleInterval", 0) <= 2
          and pl.get("ProgramArguments") == [os.path.join(home, ".cache", "pantheon", "hookd", "bin", "pantheon-hookd")],
          (r.returncode, r.stderr[-300:], pl))
    check("hookd-install.sh --print ничего не ставит: ~/Library в подменённом HOME не создан",
          not os.path.exists(os.path.join(home, "Library")), os.listdir(home))
    r = subprocess.run(["/bin/sh", INSTALL, "--bogus"], env=base_env(home), capture_output=True, text=True,
                       timeout=SUB_TIMEOUT)
    check("hookd-install.sh с неизвестным ключом — код 64 и причина", r.returncode == 64 and "неизвестный ключ" in r.stderr,
          (r.returncode, r.stderr))


def test_daemon_cli(root):
    home = os.path.join(root, "cli")
    os.makedirs(home)
    r = subprocess.run(["/bin/sh", LAUNCHER, DAEMON], env=base_env(home), capture_output=True, text=True,
                       timeout=SUB_TIMEOUT)
    last = (r.stderr.strip().splitlines() or [""])[-1]
    check("daemon.py вне launchd (без --socket) — код 1 и причина последней строкой",
          r.returncode == 1 and last.startswith("hookd: сокет не получен"), (r.returncode, r.stderr[-300:]))
    r = subprocess.run(["/bin/sh", LAUNCHER, DAEMON, "--idle"], env=base_env(home), capture_output=True, text=True,
                       timeout=SUB_TIMEOUT)
    check("daemon.py с плохими аргументами — код 64", r.returncode == 64 and "плохие аргументы" in r.stderr,
          (r.returncode, r.stderr[-300:]))
    sock = os.path.join(root, "idle.sock")
    p = subprocess.Popen(["/bin/sh", LAUNCHER, DAEMON, "--socket", sock, "--idle", "1"], env=base_env(home),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS.append(p)
    end = time.monotonic() + 30
    while time.monotonic() < end and not os.path.exists(sock) and p.poll() is None:
        time.sleep(0.02)
    mode = os.stat(sock).st_mode & 0o777 if os.path.exists(sock) else None
    try:
        code = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        code = None
    check("свой сокет демона — 0600; после простоя --idle демон выходит с кодом 0 и убирает сокет",
          mode == 0o600 and code == 0 and not os.path.exists(sock), (oct(mode or 0), code, os.path.exists(sock)))


def test_flag_off(root, client):
    home = os.path.join(root, "off")
    work = os.path.join(root, "work")
    os.makedirs(home)
    d = install(home, client)
    fake = Fake(os.path.join(d, "hookd.sock"), b_allow)
    try:
        ev = deny_event(work)
        ref, _ = slow(["--strict"], ev, base_env(home), work)
        got, _ = run([WRAP, "guard", "--strict"], ev, base_env(home), work)
        check("без PANTHEON_HOOKD=1 оболочка — медленный путь: ответ тот же, демона не спрашивает, журнала откатов нет",
              got == ref and fake.count == 0 and not fb_lines(home), (got, ref, fake.count, fb_lines(home)))
        got, _ = run([WRAP, "guard", "--strict"], ev, base_env(home, PANTHEON_HOOKD="yes"), work)
        check("PANTHEON_HOOKD не «1» — тоже медленный путь", got == ref and fake.count == 0, (got, fake.count))
    finally:
        fake.close()


def deny_event(work):
    return {"session_id": "hookd0330abcdef12", "transcript_path": "/nonexistent", "cwd": work,
            "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "npm run dev"}}


def test_wrapper_no_client(root):
    """Оболочка без клиента: метка .failed (фон не запускается) — no-client; клиент 0644 — no-client; мусор с +x —
    client-exec. Ответ — медленного пути с тем же stdin."""
    work = os.path.join(root, "work")
    ev = deny_event(work)
    for name, setup, want in (("клиента нет", "none", "no-client"), ("клиент не исполняемый", "nonexec", "no-client"),
                              ("клиент — мусор с +x", "garbage", "client-exec")):
        if setup == "garbage" and sys.platform != "darwin":
            print(f"пропущено: {name} — на Linux /bin/sh (dash) исполняет мусор как скрипт; служба только для macOS")
            continue
        home = os.path.join(root, "nc-" + setup)
        os.makedirs(home)
        d = install(home, None)
        c = os.path.join(d, "bin", "client-" + src_hash())
        with open(c + ".failed", "w") as fh:
            fh.write("проба\n")
        if setup == "nonexec":
            with open(c, "wb") as fh:
                fh.write(b"#!/bin/sh\nexit 0\n")
            os.chmod(c, 0o644)
        elif setup == "garbage":
            with open(c, "wb") as fh:
                fh.write(b"\xcf\xfa\xed\xfe\x00\x01garbage(\n")
            os.chmod(c, 0o755)
            with open(c + ".sum", "w") as fh:  # метка совпала — мусор доходит до запуска и даёт 126
                fh.write(hashlib.sha256(open(c, "rb").read()).hexdigest() + "\n")
        ref, _ = slow(["--strict"], ev, base_env(home), work)
        got, _ = wrap(["--strict"], ev, base_env(home), work)
        # мусор с +x: /bin/sh сам пишет «cannot execute binary file» в stderr перед медленным путём
        same = got == ref if setup != "garbage" else got[:2] == ref[:2] and got[2].endswith(ref[2])
        check(f"оболочка: {name} → ответ медленного пути (отказ остаётся отказом), причина {want}",
              same and '"deny"' in ref[1] and reasons(home) == [want], (got, ref, fb_lines(home)))
    home = os.path.join(root, "nc-env")
    os.makedirs(home)
    ref, _ = slow(["--strict"], ev, base_env(home), work)
    got, _ = wrap(["--strict"], ev, base_env(""), work)
    check("оболочка: HOME пуст → медленный путь и причина env в stderr (журнал не записать)",
          got[:2] == ref[:2] and "hookd: env" in got[2], (got, ref))


def test_build(root):
    """hookd-build.sh: SRC не совпал — метка .failed и код 1; клиента нет — оболочка собирает его в фоне."""
    copy = os.path.join(root, "bcopy")
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    with open(os.path.join(copy, "hooks", "hookd.sh"), encoding="utf-8") as fh:
        body = fh.read()
    with open(os.path.join(copy, "hooks", "hookd.sh"), "w", encoding="utf-8") as fh:
        fh.write(re.sub(r"(?m)^SRC=.*$", "SRC=0000000000000000", body))
    home = os.path.join(root, "bh-bad")
    os.makedirs(home)
    r = subprocess.run(["/bin/sh", os.path.join(copy, "hooks", "hookd-build.sh")], env=base_env(home),
                       capture_output=True, text=True, timeout=SUB_TIMEOUT)
    marker = os.path.join(hookd_dir(home), "bin", "client-0000000000000000.failed")
    check("hookd-build.sh: исходник не совпал с SRC — код 1, метка .failed, клиента нет",
          r.returncode == 1 and os.path.exists(marker) and "не совпал" in r.stderr
          and not os.path.exists(marker[:-len(".failed")]), (r.returncode, r.stderr[-300:]))
    r = subprocess.run(["/bin/sh", os.path.join(copy, "hooks", "hookd-build.sh")], env=base_env(home),
                       capture_output=True, text=True, timeout=SUB_TIMEOUT)
    check("hookd-build.sh: после неудачи без --force не собирает", r.returncode == 1 and "--force" in r.stderr,
          (r.returncode, r.stderr[-300:]))
    mode = os.stat(hookd_dir(home)).st_mode & 0o777
    check("hookd-build.sh: папка ~/.cache/pantheon/hookd — 0700", mode == 0o700, oct(mode))


def build_client(root):
    home = os.path.join(root, "bh")
    os.makedirs(home)
    r = subprocess.run(["/bin/sh", BUILD], env=base_env(home), capture_output=True, text=True, timeout=300)
    path = r.stdout.strip()
    ok = r.returncode == 0 and path == os.path.join(hookd_dir(home), "bin", "client-" + src_hash()) \
        and os.access(path, os.X_OK)
    if not ok and shutil.which("cc") is None:
        print("пропущено: нет компилятора cc — проверки клиента и демона через клиент не идут")
        return None
    check("hookd-build.sh собрал клиент в кэш вне дерева плагина: ~/.cache/pantheon/hookd/bin/client-<SRC>", ok,
          (r.returncode, r.stdout, r.stderr[-400:]))
    check("в дереве плагина собранного клиента нет", not [f for f in os.listdir(HOOKS) if f.startswith("client")],
          os.listdir(HOOKS))
    return path if ok else None


def test_supply(root, client):
    """Находка проверки безопасности: сборку зовёт хук с окружением окна, клиент обходит все решения guard.
    Поддельные cc, sha256 и прочие команды первыми в PATH, CPATH с заголовком #error, CFLAGS, SDKROOT — сборка их не
    берёт. Подменённый клиент (или клиент без метки .sum) оболочка не запускает: медленный путь, причина client-sum."""
    work = os.path.join(root, "work")
    fake = os.path.join(root, "fk")
    inc = os.path.join(fake, "inc")
    os.makedirs(inc)
    mark = os.path.join(fake, "called")
    for tool in ("cc", "clang", "gcc", "sha256", "sha256sum", "shasum", "uname", "env", "xcrun", "head", "cut", "sed",
                 "mv", "chmod", "find", "mkdir", "rm", "tail", "xcode-select", "ld"):
        p = os.path.join(fake, tool)
        with open(p, "w") as fh:
            fh.write(f"#!/bin/sh\necho {tool} >>{mark}\nexit 0\n")
        os.chmod(p, 0o755)
    with open(os.path.join(inc, "stdio.h"), "w") as fh:
        fh.write("#error поддельный заголовок из CPATH\n")
    home = os.path.join(root, "sup")
    os.makedirs(home)
    env = dict(base_env(home), PATH=fake + ":" + os.environ.get("PATH", "/usr/bin:/bin"), CPATH=inc,
               C_INCLUDE_PATH=inc, CFLAGS="-DGUARD_FAKE=1 -include /nonexistent.h", SDKROOT=fake,
               CCC_OVERRIDE_OPTIONS="#^-DX", COMPILER_PATH=fake, LIBRARY_PATH=fake)
    r = subprocess.run(["/bin/sh", BUILD, "--force"], env=env, capture_output=True, text=True, timeout=300)
    c = os.path.join(hookd_dir(home), "bin", "client-" + src_hash())
    sum_ok = os.path.exists(c) and os.path.exists(c + ".sum") and \
        open(c + ".sum").read().strip() == hashlib.sha256(open(c, "rb").read()).hexdigest()
    check("сборка с поддельными cc, sha256 и прочими первыми в PATH, CPATH, CFLAGS, SDKROOT: подделки не вызваны, "
          "клиент собран, метка .sum — его SHA-256",
          r.returncode == 0 and not os.path.exists(mark) and sum_ok,
          (r.returncode, r.stderr[-400:], open(mark).read() if os.path.exists(mark) else ""))
    if sum_ok:
        ev = deny_event(work)
        ref, _ = slow(["--strict"], ev, base_env(home), work)
        got, _ = wrap(["--strict"], ev, base_env(home), work)
        check("клиент, собранный в подменённом окружении, работает: ответ медленного пути, откат — только no-socket",
              got == ref and reasons(home) == ["no-socket"], (got, ref, fb_lines(home)))
    # подмена клиента: «пропустить» на всё; метка .failed — фоновая пересборка не идёт
    for name, setup in (("клиент подменён (метка — от настоящего)", "swap"), ("метки .sum нет", "nosum"),
                        ("метка пустая", "empty")):
        home = os.path.join(root, "sw" + setup[:2])
        os.makedirs(home)
        d = install(home, client)
        c = os.path.join(d, "bin", "client-" + src_hash())
        open(c + ".failed", "w").write("проба\n")
        if setup == "swap":
            os.unlink(c)
            with open(c, "w") as fh:
                fh.write("#!/bin/sh\ncat >/dev/null\nexit 0\n")
            os.chmod(c, 0o755)
        elif setup == "nosum":
            os.unlink(c + ".sum")
        else:
            open(c + ".sum", "w").close()
        ev = deny_event(work)
        ref, _ = slow(["--strict"], ev, base_env(home), work)
        got, _ = wrap(["--strict"], ev, base_env(home), work)
        check(f"оболочка: {name} → клиент не запущен, отказ медленного пути, причина client-sum",
              got == ref and '"deny"' in ref[1] and reasons(home) == ["client-sum"], (got, ref, fb_lines(home)))
    # без метки .failed — пересборка в фоне возвращает настоящий клиент
    home = os.path.join(root, "swre")
    os.makedirs(home)
    d = install(home, client)
    c = os.path.join(d, "bin", "client-" + src_hash())
    os.unlink(c)
    with open(c, "w") as fh:
        fh.write("#!/bin/sh\ncat >/dev/null\nexit 0\n")
    os.chmod(c, 0o755)
    ev = deny_event(work)
    ref, _ = slow(["--strict"], ev, base_env(home), work)
    got, _ = wrap(["--strict"], ev, base_env(home), work)
    end = time.monotonic() + 120

    def healed():
        with open(c, "rb") as fh:
            body = fh.read()
        with open(c + ".sum") as fh:
            label = fh.read().strip()
        return not body.startswith(b"#!") and hashlib.sha256(body).hexdigest() == label

    while time.monotonic() < end and (os.path.exists(c + ".lock") or not healed()):
        time.sleep(0.1)
    check("подменённый клиент без .failed → медленный путь (client-sum) и пересборка в фоне вернула настоящий",
          got == ref and reasons(home) == ["client-sum"] and healed(), (got == ref, fb_lines(home)))


def test_shasum(root, client):
    """Д4: без /sbin/sha256 и sha256sum (macOS старше 14) оболочка сверяет клиент через /usr/bin/shasum, как сборка
    (sum() в hookd-build.sh) — клиент запускается, а не client-sum навсегда. Копия плагина: в hookd.sh пути первых двух
    заменены несуществующими."""
    if not os.access("/usr/bin/shasum", os.X_OK):
        print("пропущено: shasum в оболочке — /usr/bin/shasum нет")
        return
    copy = os.path.join(root, "shasum")
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    w = os.path.join(copy, "hooks", "hookd.sh")
    with open(w, encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace("/sbin/sha256", "/nonexistent/sha256").replace("/usr/bin/sha256sum", "/nonexistent/sha256sum")
    with open(w, "w", encoding="utf-8") as fh:
        fh.write(text)
    home = os.path.join(root, "shs")
    os.makedirs(home)
    d = install(home, client)
    fake = Fake(os.path.join(d, "hookd.sock"), b_allow)
    work = os.path.join(root, "work")
    try:
        got, _ = wrap(["--strict"], deny_event(work), base_env(home), work, hooks=os.path.join(copy, "hooks"))
    finally:
        fake.close()
    check("оболочка без /sbin/sha256 и sha256sum: клиент сверен через shasum и запущен (ответ демона, откатов нет)",
          got == (0, "", "") and fake.count == 1 and not fb_lines(home), (got, fake.count, fb_lines(home)))


def test_bench(root):
    """Д5: bench.py --hookd не падает кодом 1 из-за прогрева клиента без аргументов (usage): прогрев — настоящий вызов."""
    bench = os.path.join(PLUGIN, "scripts", "bench.py")
    # bench кладёт HOME в <TMPDIR>/gbXXXXXXXX/home: папка, где сокет укладывается в 103 байта
    fits = [d for d in (root, tempfile.gettempdir(), "/tmp")
            if len(d) + len("/gbXXXXXXXX/home/") + len(SOCK_REL) <= 103]
    if not fits:
        print("пропущено: bench.py --hookd — нет папки с коротким путём для сокета")
        return
    r = subprocess.run([sys.executable, "-I", bench, "--hookd", "-n", "1"], capture_output=True, text=True,
                       env=dict(os.environ, TMPDIR=fits[0]), timeout=300)
    check("bench.py --hookd -n 1 → код 0", r.returncode == 0, (r.returncode, r.stdout[-300:], r.stderr[-500:]))


def test_background_build(root):
    work = os.path.join(root, "work")
    home = os.path.join(root, "bg")
    os.makedirs(home)
    ev = deny_event(work)
    ref, _ = slow(["--strict"], ev, base_env(home), work)
    got, _ = wrap(["--strict"], ev, base_env(home), work)
    c = os.path.join(hookd_dir(home), "bin", "client-" + src_hash())
    end = time.monotonic() + 120
    while time.monotonic() < end and (not os.path.exists(c) or os.path.exists(c + ".lock")):
        time.sleep(0.1)
    check("клиента нет → этот вызов медленным путём (no-client), а клиент собирается в фоне",
          got == ref and reasons(home) == ["no-client"] and os.access(c, os.X_OK) and not os.path.exists(c + ".lock"),
          (got == ref, fb_lines(home), os.path.exists(c)))
    # С-A2: замок сборки брошен (сборку убили SIGKILL, папка замка осталась). Свежий замок — сборка идёт, фон не
    # запускается; старше 2 мин — оболочка запускает фон, hookd-build.sh снимает замок и собирает клиент
    for name, age, built in (("свежий замок — фон не запускается", 0, False),
                             ("замок старше 2 мин — фон запускается и собирает клиент", 180, True)):
        home = os.path.join(root, "bgl" + str(age))
        os.makedirs(os.path.join(hookd_dir(home), "bin"))
        c = os.path.join(hookd_dir(home), "bin", "client-" + src_hash())
        os.makedirs(c + ".lock")
        t = time.time() - age
        os.utime(c + ".lock", (t, t))
        got, _ = wrap(["--strict"], ev, base_env(home), work)
        end = time.monotonic() + (120 if built else 3)
        while time.monotonic() < end and not (os.access(c, os.X_OK) and not os.path.exists(c + ".lock")):
            time.sleep(0.1)
        ok = os.access(c, os.X_OK) and not os.path.exists(c + ".lock") if built else \
            not os.path.exists(c) and os.path.isdir(c + ".lock")
        check(f"клиента нет, {name}; вызов — медленным путём (no-client)",
              got == ref and reasons(home) == ["no-client"] and ok,
              (got == ref, fb_lines(home), os.path.exists(c), os.path.exists(c + ".lock")))


# --- сверка решений -----------------------------------------------------------------------------------------------

def tree_of(root, skip):
    """Файлы и папки под root с правами (umask вызова): [(путь, права)]."""
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if os.path.join(d, x) not in skip)
        for f in files + dirs:
            if f != "hookd-fallback.log":
                p = os.path.join(d, f)
                out.append((os.path.relpath(p, root), oct(os.lstat(p).st_mode & 0o7777)))
    return sorted(out)


def test_equivalence(root, client, sock):
    """Сверка решений и файлов с правами; umask вызовов — не тот, с которым запущен демон (Д1/Д-A3). Набор, где guard
    создаёт папки по umask, — test_strict_sequence. Только PreToolUse: остальное демон не судит (С-A3, проверка в
    test_daemon_refusals)."""
    w = TC.World(os.path.join(root, "w"))
    ctx, evs = TC.contexts(w), TC.events(w)
    jobs = [(f"{cn} {en}", argv, env, ev) for en, ev in evs.items() for cn, (argv, env) in ctx.items()
            if ev.get("hook_event_name") == "PreToolUse"]
    daemon_umask = os.umask(0)
    call_umask = 0o027 if daemon_umask != 0o027 else 0o077
    os.umask(call_umask)
    try:
        _equivalence(w, jobs, client, sock, call_umask, daemon_umask)
    finally:
        os.umask(daemon_umask)


def _equivalence(w, jobs, client, sock, call_umask, daemon_umask):
    def one_pass(via):
        w.reset()
        for h in (w.ha, w.hb):
            install(h, client, sock)
        out = []
        for _, argv, env, ev in jobs:
            if via == "slow":
                out.append(slow(argv, ev, env, w.work)[0])
            elif via == "wrap-off":
                out.append(run([WRAP, "guard", *argv], ev, env, w.work)[0])
            else:
                out.append(wrap(argv, ev, env, w.work)[0])
        return out, tree_of(w.root, {hookd_dir(w.ha), hookd_dir(w.hb)})

    want, want_files = one_pass("slow")
    off, off_files = one_pass("wrap-off")
    got, got_files = one_pass("hookd")
    logs = fb_lines(w.ha) + fb_lines(w.hb)
    bad = [(n, a, b) for (n, *_), a, b in zip(jobs, want, got) if a != b]
    check(f"демон: решения — как у медленного пути ({len(jobs)} вызовов: плагин, --managed, --strict, hestia, "
          "dev-opus, два HOME, TMPDIR, GUARD_OFF): код, stdout и stderr", not bad,
          [(n, a[0], a[1][:160], a[2][:160], "≠", b[0], b[1][:160], b[2][:160]) for n, a, b in bad[:3]])
    check(f"демон: файлы и папки, которые guard пишет в HOME и TMPDIR (метки strict, журналы), и их права при umask "
          f"вызова {oct(call_umask)} (у демона {oct(daemon_umask)}) — те же, что у медленного пути",
          got_files == want_files, sorted(set(got_files) ^ set(want_files))[:10])
    rs = [ln.split("\t")[1] for ln in logs if "\t" in ln]
    print(f"     сверка: {len(jobs) - len(rs)} вызовов решил демон, {rs.count('spawn')} — медленным путём (spawn)")
    check("демон: ни одного отката (и spawn нет) — все вызовы решил демон", not logs, logs[:5])
    check("оболочка без флага — те же решения и файлы", off == want and off_files == want_files,
          [(n, a, b) for (n, *_), a, b in zip(jobs, want, off) if a != b][:2])
    d = {n: dec(r) for (n, *_), r in zip(jobs, got)}
    kinds = {k for k in d.values()}
    check("набор различает решения: есть и отказ, и пропуск", {"deny", "allow"} <= kinds, kinds)
    check("строгий guard через демон отказывает (attribution, strict-B) — демон загружен без --strict",
          d["strict-B attribution"] == "deny", d["strict-B attribution"])
    if TC.managed_active():
        check("режим из argv: хук плагина того же HOME через демон при управляемых настройках молчит",
              d["plugin-B attribution"] == "allow", d["plugin-B attribution"])
    else:
        print("пропущено: управляемые настройки этой машины не зовут guard --managed — плагин и strict здесь не "
              "различаются по ним")


def test_push_accepted(root, client, sock):
    """Д-B3-2: push в принятый PR (metis-0794) через клиент. Случаи test_push_accepted (настоящий git, поддельный gh в
    PATH вызова, записи argus в HOME) идут медленным путём и через клиент: ответы те же, проверки случаев проходят.
    Правило зовёт git и gh — внук демона их не запускает: такой вызов уходит на медленный путь с причиной spawn (решение
    лида 05.11, argus #311 Б1). Другие причины отката — ошибка."""
    import test_push_accepted as tpa
    tm = tpa.tm
    base = tpa.mkroot("pa", first=root)
    if len(base) + len("/") + len(SOCK_REL) > 103:
        print(f"пропущено: push в принятый PR — путь сокета в {base} длиннее 103 байт")
        return
    h = tm.Home(base)
    install(h.root, client, sock)
    calls, verdicts, how = {}, {}, []

    def hook_via(via):
        def hook(event, pdir, mode=(), extra_env=None):
            env = dict(h.env(pdir), **(extra_env or {}))
            raw = json.dumps(event).encode()
            n = len(fb_lines(h.root))
            res = (slow if via == "slow" else wrap)(list(mode), None, env, h.j(pdir), raw=raw)[0]
            calls[via].append(res)
            if via == "hookd":
                how.append(",".join(ln.split("\t")[1] for ln in fb_lines(h.root)[n:]) or "daemon")
            return subprocess.CompletedProcess([], res[0], res[1], res[2])
        return hook

    old_check = tpa.check
    try:
        for via in ("slow", "hookd"):
            calls[via], verdicts[via] = [], []
            tpa.check = lambda name, cond, detail="", v=via: verdicts[v].append((name, bool(cond)))
            h.hook = hook_via(via)
            for case in tpa.CASES:
                h.reset()
                case(h)
    finally:
        tpa.check = old_check
        shutil.rmtree(base, ignore_errors=True)
    bad = [n for n, ok in verdicts["hookd"] if not ok]
    check(f"push в принятый PR через клиент: все {len(verdicts['hookd'])} проверок test_push_accepted прошли",
          verdicts["hookd"] and not bad and verdicts["hookd"] == verdicts["slow"], bad[:3])
    def norm(res):  # коммиты каждого прохода новые (время в коммите) — SHA в тексте отказа разные
        return tuple(re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", x) if isinstance(x, str) else x for x in res)

    diff = [(i, a, b) for i, (a, b) in enumerate(zip(calls["slow"], calls["hookd"])) if norm(a) != norm(b)]
    n_spawn, n_daemon = how.count("spawn"), how.count("daemon")
    print(f"     push в принятый PR через клиент: {n_spawn} вызовов — медленным путём (spawn), {n_daemon} — демоном")
    check(f"push в принятый PR: {len(calls['hookd'])} ответов через клиент — как у медленного пути (код, stdout, "
          "stderr), есть отказы",
          len(calls["slow"]) == len(calls["hookd"]) and not diff and any(dec(r) == "deny" for r in calls["hookd"]),
          diff[:2])
    spawned = [dec(r) for r, w in zip(calls["hookd"], how) if w == "spawn"]
    check("push в принятый PR: правило зовёт git и gh — откат только spawn, и в нём есть отказы медленного пути",
          len(how) == len(calls["hookd"]) and set(how) <= {"spawn", "daemon"} and "deny" in spawned,
          (sorted(set(how)), spawned.count("deny")))


def test_strict_sequence(root, client, sock):
    """Строгий guard и хук плагина одной сессии окна по очереди через один демон: строгий пишет метку и отказывает,
    хук плагина после метки молчит, строгий снова отказывает — как у медленного пути. umask вызовов — не демона
    (Д1/Д-A3): родители папки меток (~/.local, ~/.local/state, …/pantheon) создаются с правами по umask вызова."""
    work = os.path.join(root, "work")
    co = "Co-" + "Authored-By: " + "Cla" + "ude <noreply@anthropic.com>"
    ev = dict(deny_event(work), session_id="strictseq0330abcd", tool_input={"command": f"git commit -m x -m '{co}'"})
    seq = (["--strict"], [], ["--strict"], [], ["--managed"])
    res = {}
    daemon_umask = os.umask(0)
    os.umask(daemon_umask)
    call_umask = 0o027 if daemon_umask != 0o027 else 0o077
    for via in ("slow", "hookd"):
        home = os.path.join(root, "sq" + via[:2])
        os.makedirs(home)
        install(home, client, sock)
        env = base_env(home, PANTHEON_WINDOW="w1")
        os.umask(call_umask)
        try:
            res[via] = [(slow if via == "slow" else wrap)(a, ev, env, work)[0] for a in seq]
        finally:
            os.umask(daemon_umask)
        res[via + "-tree"] = tree_of(home, {hookd_dir(home)})
        marker = os.path.join(home, ".local", "state", "pantheon", "guard-strict", ev["session_id"])
        res[via + "-marker"] = open(marker, encoding="utf-8").read() if os.path.exists(marker) else None
        res[via + "-log"] = fb_lines(home)
    check("strict → плагин → strict → плагин → managed через демон: те же ответы, что медленным путём, без откатов",
          res["hookd"] == res["slow"] and not res["hookd-log"], (res["hookd"], res["slow"], res["hookd-log"]))
    check("строгий guard через демон отказал оба раза и записал метку окна w1\\tBash в HOME вызова",
          [dec(r) for r in res["hookd"][0::2][:2]] == ["deny", "deny"] and res["hookd-marker"] == "w1\tBash\n",
          ([dec(r) for r in res["hookd"]], res["hookd-marker"]))
    local = dict(res["hookd-tree"]).get(".local")
    check(f"umask вызова {oct(call_umask)} (у демона {oct(daemon_umask)}): файлы и права в HOME — как у медленного "
          f"пути, ~/.local — {oct(0o777 & ~call_umask)}",
          res["hookd-tree"] == res["slow-tree"] and local == oct(0o777 & ~call_umask),
          (sorted(set(res["hookd-tree"]) ^ set(res["slow-tree"]))[:6], local))


# --- отказы -------------------------------------------------------------------------------------------------------

def test_failures(root, client):
    work = os.path.join(root, "work")
    ev = deny_event(work)
    probes = [
        ("нет сокета", None, "no-socket"),
        ("права папки 0755", b_close, "dir-perm"),
        ("демон закрыл соединение до «принят»", b_close, "no-ack"),
        ("мусор вместо ответа", b_garbage, "proto"),
        ("демон молчит (нет «принят» за 300 мс)", b_hang, "no-ack"),
        ("демон умер после «принят»", b_ack_die, "no-reply"),
        ("ответ оборван", b_short, "short-reply"),
        ("отказ демона F stale", b_f_stale, "stale"),
        ("отказ демона с чужой причиной", b_f_bad, "proto"),
        ("сокет без слушателя", "refused", "refused"),
        ("демон вернул код 126", b_x126, None),
    ]
    for i, (name, behaviour, want) in enumerate(probes):
        home = os.path.join(root, f"f{i}")
        os.makedirs(home)
        d = install(home, client)
        fake = None
        if behaviour == "refused":
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(os.path.join(d, "hookd.sock"))
            s.close()
        elif behaviour is not None:
            fake = Fake(os.path.join(d, "hookd.sock"), behaviour)
        if "0755" in name:
            os.chmod(d, 0o755)
        try:
            ref, t_ref = slow(["--strict"], ev, base_env(home), work)
            got, t_got = wrap(["--strict"], ev, base_env(home), work)
        finally:
            if fake:
                fake.close()
        if want is None:
            check(f"отказ: {name} → клиент отдаёт код 2, а не 126 (оболочка не повторит вызов с пустым stdin)",
                  got[0] == 2 and not fb_lines(home), (got, fb_lines(home)))
            continue
        ok = got == ref and '"deny"' in ref[1] and reasons(home) == [want]
        extra = ""
        if behaviour is b_hang:
            ok = ok and t_got - t_ref < 2.0
            extra = f" за {t_got - t_ref + 0.0:.2f} с сверх медленного пути"
        check(f"отказ: {name} → ответ медленного пути, причина {want}{extra}", ok,
              (got, ref, fb_lines(home), round(t_got, 2), round(t_ref, 2)))
    # решение не пришло — медленный путь. Срок демона — 7,5 с от старта клиента (Д-D1): stdin приходит через 1,5 с,
    # а клиент всё равно отпускает демона к 7,5 с от своего старта — медленному пути до таймаута хука 10 с остаётся 2,5 с
    home = os.path.join(root, "fsr")
    os.makedirs(home)
    d = install(home, client)
    fake = Fake(os.path.join(d, "hookd.sock"), b_ack_hang)
    try:
        ref, t_ref = slow(["--strict"], ev, base_env(home), work)
        got, t_got = run_late(wrap_argv(["--strict"]), ev, dict(base_env(home), PANTHEON_HOOKD="1",
                                                               PANTHEON_HOOKD_CANARY="0"), work, 1.5)
    finally:
        fake.close()
    check("отказ: «принят», но решения нет → медленный путь, причина no-reply; stdin через 1,5 с, а демона ждали "
          "7,5 с от старта клиента — медленному пути до 10 с осталось 2,5 с",
          got == ref and reasons(home) == ["no-reply"] and 7.3 < t_got - t_ref < 7.9,
          (got == ref, fb_lines(home), round(t_got, 2), round(t_ref, 2)))
    # «принят», а запрос около 1 МиБ демон не читает: запись в сокет не держит вызов сверх срока (F1, argus PR 307)
    home = os.path.join(root, "fsend")
    os.makedirs(home)
    d = install(home, client)
    fake = Fake(os.path.join(d, "hookd.sock"), b_ack_noread)
    padded = dict(ev, pad="x" * (1024 * 1024))
    try:
        ref, t_ref = slow(["--strict"], padded, base_env(home), work)
        got, t_got = wrap(["--strict"], padded, base_env(home), work)
    finally:
        fake.close()
    check("отказ: «принят», демон не читает stdin 1 МиБ → медленный путь, причина send; демона ждали не дольше 7,5 с",
          got == ref and '"deny"' in ref[1] and reasons(home) == ["send"] and t_got - t_ref < 7.9,
          (got == ref, fb_lines(home), round(t_got, 2), round(t_ref, 2)))
    # путь сокета длиннее sun_path
    home = os.path.join(root, "L" * (110 - len(root)))
    os.makedirs(home)
    install(home, client)
    ref, _ = slow(["--strict"], ev, base_env(home), work)
    got, _ = wrap(["--strict"], ev, base_env(home), work)
    check("отказ: путь сокета длиннее 103 байт → медленный путь, причина path-long",
          got == ref and reasons(home) == ["path-long"], (got == ref, fb_lines(home)))
    # большой запрос — до соединения
    home = os.path.join(root, "fbig")
    os.makedirs(home)
    d = install(home, client)
    fake = Fake(os.path.join(d, "hookd.sock"), b_allow)
    big = dict(deny_event(work), tool_name="Write",
               tool_input={"file_path": os.path.join(work, "big.txt"), "content": "x" * (8 * 1024 * 1024 + 10)})
    try:
        ref, _ = slow(["--strict"], big, base_env(home), work)
        got, _ = wrap(["--strict"], big, base_env(home), work)
    finally:
        fake.close()
    check("отказ: запрос больше 8 МиБ → медленный путь (причина big), демона не спрашивает",
          got == ref and reasons(home) == ["big"] and fake.count == 0, (got[0], ref[0], fb_lines(home), fake.count))
    all_lines = []
    for d in os.listdir(root):
        all_lines += fb_lines(os.path.join(root, d))
    check("в журнале откатов только «время<TAB>причина» — текста события нет",
          all_lines and all(LINE_RE.fullmatch(ln) for ln in all_lines), [ln for ln in all_lines if not
                                                                           LINE_RE.fullmatch(ln)][:3])


def test_double_failure(root, client):
    """Д-B2-1: демона нет и медленный путь не запустился (python.sh нет) или убит (python.sh делает kill -9 себе) —
    двойной отказ: код 2 (запрет этого вызова, а не «пропустить»), причина в stderr и строки no-socket и
    slow-exec / slow-signal в журнале откатов."""
    work = os.path.join(root, "work")
    ev = deny_event(work)
    for name, body, want, text in (("python.sh нет", None, "slow-exec", "недоступны (python.sh: код 127)"),
                                   ("python.sh убивает себя kill -9", "#!/bin/sh\nkill -9 $$\n", "slow-signal",
                                    "прерван сигналом 9")):
        copy = os.path.join(root, "dbl-" + want[5:])
        shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        py = os.path.join(copy, "hooks", "python.sh")
        os.unlink(py)
        if body:
            with open(py, "w") as fh:
                fh.write(body)
        home = os.path.join(root, "db" + want[5:8])
        os.makedirs(home)
        install(home, client)
        got, _ = wrap(["--strict"], ev, base_env(home), work, hooks=os.path.join(copy, "hooks"))
        check(f"двойной отказ: демона нет, {name} → код 2, причина в stderr, строки no-socket и {want}",
              got[0] == 2 and got[1] == "" and text in got[2] and "действие остановлено" in got[2]
              and reasons(home) == ["no-socket", want], (got, fb_lines(home)))


def test_daemon_refusals(root, client, sock):
    """Отказы настоящего демона: протокол руками и через клиент."""
    work = os.path.join(root, "work")
    home = os.path.join(root, "dh-raw")
    os.makedirs(home)
    env = base_env(home)
    hdr = {"argv": ["--strict"], "cwd": work, "env": env, "hooks": HOOKS, "version": plugin_version(), "umask": 0o22}
    body = json.dumps(deny_event(work)).encode()
    got = raw_call(sock, hdr, body)
    check("демон по протоколу G2: ответ «X 0 <n> 0» с отказом", got.startswith("X 0 "), got)
    for name, h, b, line, want in (
            ("чужая версия плагина", dict(hdr, version="0.0.0"), body, None, "F version"),
            ("чужое дерево плагина", dict(hdr, hooks=os.path.join(root, "other", "hooks")), body, None, "F tree"),
            ("чужая версия протокола", hdr, body, "G3 1 1\n", "F proto"),
            ("шапка не JSON", None, b"abc", "G2 3 0\n", "F proto"),
            ("шапка без umask", {k: v for k, v in hdr.items() if k != "umask"}, body, None, "F proto"),
            ("событие не UTF-8", hdr, b"\xff\xfe", None, "F encoding"),
            ("локаль KOI8-R", dict(hdr, env=dict(env, LC_ALL="ru_RU.KOI8-R")), body, None, "F locale"),
            ("папки вызова нет", dict(hdr, cwd=os.path.join(root, "nope")), body, None, "F cwd"),
            ("событие PostToolUse (С-A3: демон судит только PreToolUse)", hdr,
             json.dumps(dict(deny_event(work), hook_event_name="PostToolUse")).encode(), None, "F event"),
            ("событие без hook_event_name", hdr,
             json.dumps({k: v for k, v in deny_event(work).items() if k != "hook_event_name"}).encode(), None,
             "F event"),
            ("событие не JSON", hdr, b"abc", None, "F event"),
            ("запрос больше 8 МиБ", None, b"", "G2 9000000 1\n", "F big")):
        got = raw_call(sock, h, b, line=line)
        check(f"демон: {name} → «{want}»", got == want, got)
    if not client:
        print("пропущено: без клиента — отказы демона через клиент")
        return
    # через клиент: кодировка и локаль ведут на медленный путь с тем же решением
    for name, raw, extra, want in (("событие не UTF-8", b'{"hook_event_name": "PreToolUse", "x": "\xff"}', {},
                                    "encoding"),
                                   ("локаль KOI8-R", None, {"LC_ALL": "ru_RU.KOI8-R"}, "locale"),
                                   ("событие PostToolUse", json.dumps(dict(
                                       deny_event(work), hook_event_name="PostToolUse",
                                       tool_response={"stdout": "", "stderr": "", "interrupted": False})).encode(),
                                    {}, "event")):
        h2 = os.path.join(root, "d" + want[:3])
        os.makedirs(h2)
        install(h2, client, sock)
        e2 = base_env(h2, **extra)
        ref, _ = slow(["--strict"], deny_event(work), e2, work, raw=raw)
        got, _ = wrap(["--strict"], deny_event(work), e2, work, raw=raw)
        check(f"клиент: {name} → медленный путь с тем же ответом, причина {want}",
              got == ref and reasons(h2) == [want], (got, ref, fb_lines(h2)))


def test_perm(root, client, sock):
    """Решение владельца 04.11 (Д-A2): отказ доступа во внуке (EPERM, EACCES) — «F perm» и медленный путь, а не решение
    по нераскрытому пути. Запись в симлинк на ~/.claude/settings.json защищена (protect-config), пока симлинк читается.
    chmod 000 на его папке — EACCES и у демона, и у медленного пути. Песочница sandbox-exec только у демона — EPERM, как
    у службы launchd без доступа TCC: медленный путь раскрывает ссылку и отказывает, а демон без «F perm» пропустил бы."""
    work = os.path.join(root, "work")
    home = os.path.join(root, "pm")
    os.makedirs(os.path.join(home, ".claude"))
    with open(os.path.join(home, ".claude", "settings.json"), "w") as fh:
        fh.write("{}\n")
    locked = os.path.join(work, "locked")
    os.makedirs(locked)
    link = os.path.join(locked, "s.json")
    os.symlink(os.path.join(home, ".claude", "settings.json"), link)
    install(home, client, sock)
    ev = dict(deny_event(work), tool_name="Write", tool_input={"file_path": link, "content": "{}"},
              agent_type="dev-opus")
    env = base_env(home)
    hdr = {"argv": ["--strict"], "cwd": work, "env": env, "hooks": HOOKS, "version": plugin_version(), "umask": 0o22}
    ref, _ = slow(["--strict"], ev, env, work)
    got, _ = wrap(["--strict"], ev, env, work)
    check("perm: симлинк на settings.json читается — отказ, через демон тот же и без отката",
          got == ref and dec(ref) == "deny" and not fb_lines(home), (got, ref, fb_lines(home)))
    unread = os.path.join(work, "unread")
    os.makedirs(unread)
    try:
        os.chmod(locked, 0)
        os.chmod(unread, 0o311)
        got_raw = raw_call(sock, hdr, json.dumps(ev).encode())
        ref, _ = slow(["--strict"], ev, env, work)
        got, _ = wrap(["--strict"], ev, env, work)
        cwd_raw = raw_call(sock, dict(hdr, cwd=unread), json.dumps(dict(deny_event(unread))).encode())
    finally:
        os.chmod(locked, 0o755)
        os.chmod(unread, 0o755)
    check("perm: папка симлинка chmod 000 (EACCES) → демон «F perm», а не решение", got_raw == "F perm", got_raw)
    check("perm: chmod 000 через клиент → ответ медленного пути, причина perm",
          got == ref and reasons(home) == ["perm"], (got, ref, fb_lines(home)))
    check("perm: папка вызова не читается (0311) → «F perm»", cwd_raw == "F perm", cwd_raw)
    sbx = "/usr/bin/sandbox-exec"
    probe = subprocess.run([sbx, "-p", "(version 1)(allow default)", "/usr/bin/true"], capture_output=True,
                           timeout=SUB_TIMEOUT) if os.path.exists(sbx) else None
    if probe is None or probe.returncode != 0:
        print("пропущено: perm под песочницей — sandbox-exec нет или вложенная песочница запрещена")
        return
    prof = '(version 1)(allow default)(deny file-read* (subpath "%s"))' % os.path.realpath(locked)
    dhome = os.path.join(root, "pmd")
    os.makedirs(dhome)
    sock2 = os.path.join(root, "pm.sock")
    log = open(os.path.join(root, "pm-daemon.log"), "ab")
    p = subprocess.Popen([sbx, "-p", prof, "/bin/sh", LAUNCHER, DAEMON, "--socket", sock2, "--idle", "300"],
                         env=base_env(dhome), stdout=log, stderr=log)
    PROCS.append(p)
    end = time.monotonic() + 30
    while time.monotonic() < end and not os.path.exists(sock2) and p.poll() is None:
        time.sleep(0.02)
    home = os.path.join(root, "pms")
    os.makedirs(os.path.join(home, ".claude"))
    os.replace(os.path.join(root, "pm", ".claude", "settings.json"), os.path.join(home, ".claude", "settings.json"))
    os.unlink(link)
    os.symlink(os.path.join(home, ".claude", "settings.json"), link)
    install(home, client, sock2)
    env = base_env(home)
    got_raw = raw_call(sock2, dict(hdr, env=env), json.dumps(ev).encode())
    ref, _ = slow(["--strict"], ev, env, work)
    got, _ = wrap(["--strict"], ev, env, work)
    stop(p)
    check("perm: демон в песочнице без доступа к папке симлинка (EPERM, как TCC у launchd) → «F perm»",
          got_raw == "F perm", got_raw)
    check("perm: через клиент — отказ медленного пути (он ссылку раскрыл), а не пропуск демона; причина perm",
          got == ref and dec(got) == "deny" and reasons(home) == ["perm"], (got, ref, fb_lines(home)))


def test_spawn(root, client, sock):
    """Решение лида 05.11 (argus #311 Б1): правило, которое запускает программу (git и gh push в принятый PR, шлюз
    слияния), идёт медленным путём — «F spawn». Программа под службой launchd получает EPERM от TCC сама: trap_perm
    этого не видит, правило читает код не 0 как «нет данных» и пропускает. Проба P2 argus: демон в песочнице без чтения
    данных репозитория, `git -C <repo> push` в принятый PR из другой папки — медленный путь отказывает. Read и Write без
    подпроцессов демон решает сам, без отката: иначе ускорение пропало бы."""
    import test_push_accepted as tpa
    tm = tpa.tm
    base = tpa.mkroot("sp", first=root)
    if len(base) + len("/") + len(SOCK_REL) > 103:
        print(f"пропущено: spawn — путь сокета в {base} длиннее 103 байт")
        return
    h = tm.Home(base)
    try:
        h.reset()
        s = tpa.Push(h)
        s.pr(tpa.NON_CORE)
        s.accepts(1, checklist=dict(tm.CHECKLIST, ran="модель: claude-sonnet-4-5, тесты 10 из 10"))
        cwd, env = h.j("ai/pantheon"), h.env(tpa.KIT)
        ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
              "tool_input": {"command": f"git -C {s.p} push origin {tpa.BRANCH}"}, "cwd": cwd,
              "session_id": "s-coord", "tool_use_id": "toolu_sp1", "agent_type": "domain-coordinator"}
        hdr = {"argv": [], "cwd": cwd, "env": env, "hooks": HOOKS, "version": plugin_version(), "umask": 0o22}
        body = json.dumps(ev).encode()
        install(h.root, client, sock)
        ref, _ = slow([], ev, env, cwd)
        got_raw = raw_call(sock, hdr, body, timeout=30)
        got, _ = wrap([], ev, env, cwd)
        check("spawn: push в принятый PR (правило зовёт git и gh) → демон «F spawn»", got_raw == "F spawn", got_raw)
        check("spawn: тот же push через клиент → отказ медленного пути, причина spawn",
              got == ref and dec(ref) == "deny" and tpa.HINT in ref[1] and reasons(h.root) == ["spawn"],
              (got, ref, fb_lines(h.root)))
        # без подпроцессов: Read, Write, Edit и Bash без git через тот же демон — без отката
        work = os.path.join(root, "work")
        plain = [dict(deny_event(work), tool_name="Read", tool_input={"file_path": os.path.join(work, "a.txt")}),
                 dict(deny_event(work), tool_name="Write",
                      tool_input={"file_path": os.path.join(work, "b.txt"), "content": "x"}),
                 dict(deny_event(work), tool_name="Edit",
                      tool_input={"file_path": os.path.join(work, "a.txt"), "old_string": "a", "new_string": "b"}),
                 dict(deny_event(work), tool_input={"command": "ls -la"})]
        n = len(fb_lines(h.root))
        pr = [(wrap([], e, env, work)[0], slow([], e, env, work)[0]) for e in plain]
        check(f"spawn: {len(plain)} вызова без подпроцессов (Read, Write, Edit, Bash ls) — решил демон, откатов нет, "
              "ответы как у медленного пути",
              all(a == b for a, b in pr) and fb_lines(h.root)[n:] == [], (pr, fb_lines(h.root)[n:]))
        # P2 argus: демон в песочнице без чтения данных репозитория (как служба launchd без доступа TCC)
        sbx = "/usr/bin/sandbox-exec"
        probe = subprocess.run([sbx, "-p", "(version 1)(allow default)", "/usr/bin/true"], capture_output=True,
                               timeout=SUB_TIMEOUT) if os.path.exists(sbx) else None
        if probe is None or probe.returncode != 0:
            print("пропущено: spawn под песочницей — sandbox-exec нет или вложенная песочница запрещена")
            return
        prof = '(version 1)(allow default)(deny file-read-data (subpath "%s"))' % os.path.realpath(s.p)
        dhome = os.path.join(root, "spd")
        os.makedirs(dhome)
        sock2 = os.path.join(root, "sp.sock")
        log = open(os.path.join(root, "sp-daemon.log"), "ab")
        p = subprocess.Popen([sbx, "-p", prof, "/bin/sh", LAUNCHER, DAEMON, "--socket", sock2, "--idle", "300"],
                             env=base_env(dhome), stdout=log, stderr=log)
        PROCS.append(p)
        end = time.monotonic() + 30
        while time.monotonic() < end and not os.path.exists(sock2) and p.poll() is None:
            time.sleep(0.02)
        install(h.root, client, sock2)
        n = len(fb_lines(h.root))
        try:
            got_raw = raw_call(sock2, hdr, body, timeout=30)
            got, _ = wrap([], ev, env, cwd)
        finally:
            stop(p)
        check("spawn: проба P2 — демон в песочнице без чтения данных репозитория → «F spawn», а не «X 0» (пропуск)",
              got_raw == "F spawn", got_raw)
        check("spawn: проба P2 через клиент → отказ медленного пути, причина spawn",
              got == ref and dec(got) == "deny" and fb_lines(h.root)[n:] and
              [ln.split("\t")[1] for ln in fb_lines(h.root)[n:]] == ["spawn"], (got, ref, fb_lines(h.root)[n:]))
    finally:
        shutil.rmtree(base, ignore_errors=True)


def patched_copy(root, name):
    """Копия плагина guard для проб демона: guard.run убивает себя (KILLME), выходит кодом 99 (EXIT99), печатает
    часовой пояс процесса (PROBE-TZ: time.tzname, time.timezone, strftime %z) или запускает программу способом <вид>,
    которая создаёт файл <метка> (`echo PROBE-SPAWN <вид> <метка>`, SPAWN_KINDS). Подмена — после входа
    `if __name__ == "__main__"`: медленный путь копии её не видит, только демон."""
    copy = os.path.join(root, name)
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    with open(os.path.join(copy, "hooks", "guard.py"), "a", encoding="utf-8") as fh:
        fh.write("\n_run0 = run\n\n\ndef run(argv, raw=None):\n"
                 "    if raw and b'KILLME' in raw:\n        os.kill(os.getpid(), signal.SIGKILL)\n"
                 "    if raw and b'EXIT99' in raw:\n        os._exit(99)\n"
                 "    if raw and b'PROBE-TZ' in raw:\n"
                 "        print(json.dumps([list(time.tzname), time.timezone, time.strftime('%z')]), flush=True)\n"
                 "        os._exit(0)\n"
                 "    if raw and b'PROBE-SPAWN' in raw:\n"
                 "        _, _, kind, mark = json.loads(raw)['tool_input']['command'].split()\n"
                 "        _spawn_probe(kind, mark)\n"
                 "        print('ran', flush=True)\n"
                 "        os._exit(0)\n"
                 "    return _run0(argv, raw)\n" + SPAWN_PROBE)
    return copy


# виды запуска программы во внуке — всё, чем правила могли бы её запустить (trap_spawn в daemon.py). Каждый создаёт
# файл-метку: метки нет — программа не запустилась. popen-init: Popen берёт fileno() у stdin до запуска — метка
# «.fileno» значит, что Popen.__init__ начал работу (ловушка стоит ниже, чем нужно)
SPAWN_KINDS = ("run", "check_output", "popen-init", "os.system", "os.popen", "os.fork", "pty.fork", "os.posix_spawn",
               "os.posix_spawnp", "os.execv", "os.spawnv", "posix.fork", "posix.system", "multiprocessing")
SPAWN_PROBE = """

def _spawn_probe(kind, mark):
    import subprocess
    touch = ["/usr/bin/touch", mark]
    if kind == "run":
        subprocess.run(touch, capture_output=True)
    elif kind == "check_output":
        subprocess.check_output(touch)
    elif kind == "popen-init":
        class In:
            def fileno(self):
                open(mark + ".fileno", "w").close()
                return 0
        subprocess.Popen(touch, stdin=In()).wait()
    elif kind == "os.system":
        os.system("/usr/bin/touch " + mark)
    elif kind == "os.popen":
        os.popen("/usr/bin/touch " + mark).read()
    elif kind in ("os.fork", "posix.fork", "pty.fork"):
        import posix
        import pty
        pid = {"os.fork": os.fork, "posix.fork": posix.fork, "pty.fork": lambda: pty.fork()[0]}[kind]()
        if pid == 0:
            open(mark, "w").close()
            os._exit(0)
        os.waitpid(pid, 0)
    elif kind == "os.posix_spawn":
        os.waitpid(os.posix_spawn(touch[0], touch, dict(os.environ)), 0)
    elif kind == "os.posix_spawnp":
        os.waitpid(os.posix_spawnp("touch", touch, dict(os.environ, PATH="/usr/bin")), 0)
    elif kind == "os.execv":
        os.execv(touch[0], touch)
    elif kind == "os.spawnv":
        os.spawnv(os.P_WAIT, touch[0], touch)
    elif kind == "posix.system":
        import posix
        posix.system("/usr/bin/touch " + mark)
    elif kind == "multiprocessing":
        import multiprocessing.util
        os.waitpid(multiprocessing.util.spawnv_passfds(touch[0].encode(), touch, []), 0)
"""


TZ_PRINT = "import json, time; print(json.dumps([list(time.tzname), time.timezone, time.strftime('%z')]))"


def far_tz():
    """Пояс, далёкий от пояса этой машины (у демона теста TZ нет — пояс машины): UTC-10 или UTC+12."""
    off = time.localtime().tm_gmtoff / 3600
    return "Etc/GMT+10" if abs(off + 10) >= 4 else "Etc/GMT-12"


def test_copy_daemon(root, client):
    """Демон на копии плагина: убитый внук, сбой внука, чужое дерево, устаревшие правила, перезапуск."""
    copy = patched_copy(root, "cp")
    chooks = os.path.join(copy, "hooks")
    work = os.path.join(root, "work")
    dhome = os.path.join(root, "cp-dh")
    os.makedirs(dhome)
    sock = os.path.join(root, "cp.sock")
    p = start_daemon(sock, dhome, hooks=chooks, logname="cp-daemon")
    check("демон копии запустился", os.path.exists(sock), p.poll())
    env = base_env(dhome)
    hdr = {"argv": ["--strict"], "cwd": work, "env": env, "hooks": chooks, "version": plugin_version(copy),
           "umask": 0o22}
    ev = deny_event(work)
    got = raw_call(sock, hdr, json.dumps(dict(ev, tool_input={"command": "echo KILLME"})).encode())
    check("демон: внук убит SIGKILL → «F killed»", got == "F killed", got)
    got = raw_call(sock, hdr, json.dumps(dict(ev, tool_input={"command": "echo EXIT99"})).encode())
    check("демон: внук вышел, не дав решения (код 99) → «F error»", got == "F error", got)
    # клиент: убитый внук → медленный путь копии (у неё KILLME — обычная команда) с тем же ответом
    home = os.path.join(root, "cph")
    os.makedirs(home)
    install(home, client, sock)
    kev = dict(ev, tool_input={"command": "npm run dev # KILLME"})
    ref, _ = slow(["--strict"], kev, base_env(home), work, hooks=chooks)
    got, _ = wrap(["--strict"], kev, base_env(home), work, hooks=chooks)
    check("клиент: внук убит → медленный путь, тот же отказ, причина killed",
          got == ref and '"deny"' in ref[1] and reasons(home) == ["killed"], (got, ref, fb_lines(home)))
    # пояс вызова (Д1/Д-A3): у демона TZ нет, у вызова — далёкий; внук видит пояс вызова, как новый процесс
    home = os.path.join(root, "cptz")
    os.makedirs(home)
    install(home, client, sock)
    tz = far_tz()
    tenv = base_env(home, TZ=tz)
    want = subprocess.run([sys.executable, "-I", "-c", TZ_PRINT], env=tenv, capture_output=True, text=True,
                          timeout=SUB_TIMEOUT).stdout
    got, _ = wrap(["--strict"], dict(ev, tool_input={"command": "echo PROBE-TZ"}), tenv, work, hooks=chooks)
    mine = subprocess.run([sys.executable, "-I", "-c", TZ_PRINT], env=base_env(home), capture_output=True, text=True,
                          timeout=SUB_TIMEOUT).stdout
    check(f"демон: TZ вызова ({tz}) ≠ TZ демона — time.tzname, time.timezone и %z внука как у нового процесса",
          got == (0, want, "") and want != mine and not fb_lines(home), (got, want, mine, fb_lines(home)))
    # подпроцесс во внуке (решение лида 05.11, argus #311 Б1): любой способ запуска — «F spawn» до запуска программы
    marks = os.path.join(root, "cpsp")
    os.makedirs(marks)
    bad = []
    for kind in SPAWN_KINDS:
        mark = os.path.join(marks, kind)
        got = raw_call(sock, hdr, json.dumps(dict(ev, tool_input={"command": f"echo PROBE-SPAWN {kind} {mark}"}))
                       .encode())
        time.sleep(0.05)  # метку пишет потомок внука — у него было бы время
        if got != "F spawn" or os.path.exists(mark) or os.path.exists(mark + ".fileno"):
            bad.append((kind, got, os.path.exists(mark), os.path.exists(mark + ".fileno")))
    check(f"демон: внук запускает программу ({len(SPAWN_KINDS)} способов: subprocess, os.system, popen, fork, pty, "
          "posix_spawn, exec, spawn, posix, multiprocessing) → «F spawn», программа не запустилась", not bad, bad)
    # через клиент: медленный путь копии (у неё PROBE-SPAWN — обычная команда) с тем же ответом, причина spawn
    home = os.path.join(root, "cpsc")
    os.makedirs(home)
    install(home, client, sock)
    sev = dict(ev, tool_input={"command": f"echo PROBE-SPAWN run {os.path.join(marks, 'client')}"})
    ref, _ = slow(["--strict"], sev, base_env(home), work, hooks=chooks)
    got, _ = wrap(["--strict"], sev, base_env(home), work, hooks=chooks)
    check("клиент: внук запускает программу → медленный путь с тем же ответом, причина spawn; программа не запущена",
          got == ref and reasons(home) == ["spawn"] and not os.path.exists(os.path.join(marks, "client")),
          (got, ref, fb_lines(home)))
    # чужое дерево: клиент основного дерева на сокете демона копии
    home = os.path.join(root, "cptr")
    os.makedirs(home)
    install(home, client, sock)
    ref, _ = slow(["--strict"], ev, base_env(home), work)
    got, _ = wrap(["--strict"], ev, base_env(home), work)
    check("клиент другого дерева плагина → медленный путь своего дерева, причина tree",
          got == ref and reasons(home) == ["tree"], (got, ref, fb_lines(home)))
    # устаревшие правила
    home = os.path.join(root, "cpst")
    os.makedirs(home)
    install(home, client, sock)
    first, _ = wrap(["--strict"], ev, base_env(home), work, hooks=chooks)
    with open(os.path.join(chooks, "guard_rules.py"), "a", encoding="utf-8") as fh:
        fh.write("\n# правка правил\n")
    ref, _ = slow(["--strict"], ev, base_env(home), work, hooks=chooks)
    got, _ = wrap(["--strict"], ev, base_env(home), work, hooks=chooks)
    try:
        code = p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        code = None
    check("правила изменились → «F stale», медленный путь с тем же ответом; демон вышел (код 0) и убрал сокет",
          first == ref and got == ref and reasons(home) == ["stale"] and code == 0 and not os.path.exists(sock),
          (first == ref, got == ref, fb_lines(home), code, os.path.exists(sock)))
    p2 = start_daemon(sock, dhome, hooks=chooks, logname="cp-daemon2")
    got, _ = wrap(["--strict"], ev, base_env(home), work, hooks=chooks)
    check("новый демон после stale решает сам (новых откатов нет)", got == ref and reasons(home) == ["stale"],
          (got == ref, fb_lines(home)))
    with open(os.path.join(copy, ".claude-plugin", "plugin.json"), "a", encoding="utf-8") as fh:
        fh.write("\n")
    got, _ = wrap(["--strict"], ev, base_env(home), work, hooks=chooks)
    try:
        code = p2.wait(timeout=10)
    except subprocess.TimeoutExpired:
        code = None
    check("изменился plugin.json → тоже stale и выход демона", got == ref and reasons(home)[-1:] == ["stale"]
          and code == 0, (fb_lines(home), code))
    # чужой uid: демон ждёт другой uid
    sock2 = os.path.join(root, "peer.sock")
    p3 = start_daemon(sock2, dhome, extra=("--uid", str(os.getuid() + 1)), logname="peer-daemon")
    home = os.path.join(root, "cppe")
    os.makedirs(home)
    install(home, client, sock2)
    ref, _ = slow(["--strict"], ev, base_env(home), work)
    got, _ = wrap(["--strict"], ev, base_env(home), work)
    check("пир не того uid (LOCAL_PEERCRED) → «F peer», медленный путь", got == ref and reasons(home) == ["peer"],
          (got, ref, fb_lines(home)))
    stop(p3)


def test_log_home(root, client):
    """Журнал откатов — только $HOME окружения вызова: клиент без аргументов (usage) пишет в подменённый HOME.
    Повод — строки usage в настоящем журнале от прогрева клиента без env (bench.py до правки)."""
    home = os.path.join(root, "lh")
    os.makedirs(home)
    r = subprocess.run([client], input=b"", capture_output=True, env=base_env(home), timeout=SUB_TIMEOUT)
    check("клиент без аргументов — код 2, причина usage в журнале подменённого HOME",
          r.returncode == 2 and reasons(home) == ["usage"], (r.returncode, r.stderr[-200:], fb_lines(home)))
    with open(os.path.join(PLUGIN, "scripts", "bench.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    calls = [n for f in tree.body if isinstance(f, ast.FunctionDef) and f.name in ("main_hookd", "run_hookd")
             for n in ast.walk(f) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("run", "Popen") and getattr(n.func.value, "id", "") == "subprocess"]
    check("bench.py --hookd: каждый запуск подпроцесса — с env временного HOME, журнал настоящего HOME не трогает",
          len(calls) >= 4 and all(any(k.arg == "env" for k in c.keywords) for c in calls),
          [(c.lineno, [k.arg for k in c.keywords]) for c in calls])


def test_canary(root, client, sock):
    work = os.path.join(root, "work")
    ev = deny_event(work)
    data = json.dumps(ev, ensure_ascii=False).encode()
    home = os.path.join(root, "can")
    os.makedirs(home)
    d = install(home, client)
    fake = Fake(os.path.join(d, "hookd.sock"), b_allow)
    try:
        ref, _ = slow(["--strict"], ev, base_env(home), work)
        got0, _ = wrap(["--strict"], ev, base_env(home), work, canary="0")
        got1, _ = wrap(["--strict"], ev, base_env(home), work, canary="1")
    finally:
        fake.close()
    lines = fb_lines(home)
    check("канарейка выключена (0): ответ демона как есть (фальшивый «пропустить»)", got0 == (0, "", ""), got0)
    check("канарейка (1 из 1): отдан ответ медленного пути, а не демона", got1 == ref and '"deny"' in ref[1],
          (got1, ref))
    check("канарейка: расхождение — строка с хешем события FNV-1a и обоими решениями",
          len(lines) == 1 and CANARY_RE.fullmatch(lines[0]) is not None and lines[0].split("\t")[2] == fnv1a(data)
          and "slow=0:deny" in lines[0] and "daemon=0:allow" in lines[0], (lines, fnv1a(data)))
    # Д-B2-2: канарейка не идёт на событиях шлюза слияния и когда демон думал дольше 2 с — ответ демона как есть
    # (фальшивый «пропустить»), строк нет. Медленный путь на этих событиях отказывает: прошла бы канарейка — был бы отказ
    for name, cmd, behaviour in (("gh pr merge", "gh pr merge 7 --merge && npm run dev", b_allow),
                                 ("git push", "git -C . push origin main && npm run dev", b_allow),
                                 ("pantheon review", "pantheon review accept x 1 y; npm run dev", b_allow),
                                 ("демон ответил через 2,5 с", "npm run dev", b_allow_late)):
        home = os.path.join(root, "cn" + str(abs(hash(name)) % 10000))
        os.makedirs(home)
        d = install(home, client)
        fake = Fake(os.path.join(d, "hookd.sock"), behaviour)
        e = dict(ev, tool_input={"command": cmd})
        try:
            ref, _ = slow(["--strict"], e, base_env(home), work)
            got, _ = wrap(["--strict"], e, base_env(home), work, canary="1")
        finally:
            fake.close()
        check(f"канарейка (1 из 1) не идёт: {name} — ответ демона, строк нет (медленный путь отказал бы)",
              got == (0, "", "") and dec(ref) == "deny" and not fb_lines(home), (got, dec(ref), fb_lines(home)))
    # настоящий демон и канарейка на каждом вызове: расхождений нет
    home = os.path.join(root, "canr")
    os.makedirs(home)
    install(home, client, sock)
    outs = []
    for args, cmd in ((["--strict"], "npm run dev"), ([], "git status"), (["--managed"], "rm -rf ~/x")):
        e = dict(ev, tool_input={"command": cmd})
        outs.append(wrap(args, e, base_env(home), work, canary="1")[0] == slow(args, e, base_env(home), work)[0])
    check("канарейка на настоящем демоне: решения совпали, строк расхождения нет", all(outs) and not fb_lines(home),
          (outs, fb_lines(home)))


def short_root():
    """Временная папка с путём, где сокет HOME/.cache/pantheon/hookd/hookd.sock укладывается в 103 байта."""
    root = tempfile.mkdtemp(prefix="hk")
    if len(root) + len("/123456/") + len(SOCK_REL) <= 103:  # имена HOME проб — не длиннее 6 знаков
        return root
    os.rmdir(root)
    return tempfile.mkdtemp(prefix="hk", dir="/tmp")


def main():
    root = short_root()
    os.makedirs(os.path.join(root, "work"))
    try:
        test_static(root)
        test_daemon_cli(root)
        test_wrapper_no_client(root)
        test_build(root)
        client = build_client(root)
        dhome = os.path.join(root, "dh")
        os.makedirs(dhome)
        sock = os.path.join(root, "d.sock")
        p = start_daemon(sock, dhome)
        check("демон запустился и создал сокет", os.path.exists(sock) and p.poll() is None, p.poll())
        test_daemon_refusals(root, client, sock)
        if client:
            test_perm(root, client, sock)
            test_flag_off(root, client)
            test_equivalence(root, client, sock)
            test_push_accepted(root, client, sock)
            test_spawn(root, client, sock)
            test_strict_sequence(root, client, sock)
            test_failures(root, client)
            test_double_failure(root, client)
            test_copy_daemon(root, client)
            test_canary(root, client, sock)
            test_supply(root, client)
            test_shasum(root, client)
            test_bench(root)
            test_log_home(root, client)
            test_background_build(root)
            # демон убит SIGKILL: сокет остался, слушателя нет — медленный путь
            stop(p)
            home = os.path.join(root, "killed")
            os.makedirs(home)
            install(home, client, sock)
            ev = deny_event(os.path.join(root, "work"))
            ref, _ = slow(["--strict"], ev, base_env(home), os.path.join(root, "work"))
            got, _ = wrap(["--strict"], ev, base_env(home), os.path.join(root, "work"))
            check("демон убит (SIGKILL) → медленный путь с тем же ответом, причина refused",
                  got == ref and reasons(home) == ["refused"], (got, ref, fb_lines(home)))
    finally:
        for p in PROCS:
            try:
                stop(p)
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
