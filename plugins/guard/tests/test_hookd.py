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
- строгий guard не теряет отказов: демон загружен без --strict, режим берётся из argv каждого вызова (находка спайка);
- отказы демона и клиента (фальшивые серверы, нет сокета, права папки, отказ «F <причина>», зависание, обрыв, большой
  запрос, чужая версия, чужое дерево, чужой uid, кодировка, локаль, убитый внук, устаревшие правила) — тот же ответ, что
  у медленного пути, и строка причины в hookd-fallback.log без текста события;
- канарейка: 1 вызов из N обоими путями, расхождение — строка с хешем события (FNV-1a 64) и оба решения;
- сборка: SRC в hookd.sh — SHA-256 исходника клиента; несовпадение — метка .failed, без сборки;
- служба: шаблон plist — сокет 0600 в ~/.cache/pantheon/hookd, без KeepAlive, ThrottleInterval 1–2 с.
"""
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


def b_allow(c):
    c.sendall(b"A\n")
    read_request(c)
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
    hooks_real = os.path.realpath(HOOKS)
    check("hookd-install.sh --print: plist без меток @…@, сокет 0600 в ~/.cache/pantheon/hookd, без KeepAlive, "
          "ThrottleInterval 1–2 с, демон этого дерева",
          r.returncode == 0 and b"@" not in r.stdout.replace(b"<?xml", b"")
          and pl.get("Label") == "pantheon.svc.hookd"
          and lst.get("SockPathName") == os.path.join(home, SOCK_REL) and lst.get("SockPathMode") == 0o600
          and lst.get("SockFamily") == "Unix" and lst.get("SockType") == "stream"
          and "KeepAlive" not in pl and "RunAtLoad" not in pl and 1 <= pl.get("ThrottleInterval", 0) <= 2
          and pl.get("ProgramArguments") == ["/bin/sh", os.path.join(hooks_real, "python.sh"),
                                             os.path.join(hooks_real, "daemon.py")],
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


# --- сверка решений -----------------------------------------------------------------------------------------------

def tree_of(root, skip):
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if os.path.join(d, x) not in skip)
        for f in files:
            if f != "hookd-fallback.log":
                out.append(os.path.relpath(os.path.join(d, f), root))
    return sorted(out)


def test_equivalence(root, client, sock):
    w = TC.World(os.path.join(root, "w"))
    ctx, evs = TC.contexts(w), TC.events(w)
    jobs = [(f"{cn} {en}", argv, env, ev) for en, ev in evs.items() for cn, (argv, env) in ctx.items()]

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
    check("демон: файлы, которые guard пишет в HOME и TMPDIR (метки strict, журналы), — те же, что у медленного пути",
          got_files == want_files, sorted(set(got_files) ^ set(want_files))[:10])
    check("демон: ни одного отката — все вызовы решил демон", not logs, logs[:5])
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


def test_strict_sequence(root, client, sock):
    """Строгий guard и хук плагина одной сессии окна по очереди через один демон: строгий пишет метку и отказывает,
    хук плагина после метки молчит, строгий снова отказывает — как у медленного пути."""
    work = os.path.join(root, "work")
    co = "Co-" + "Authored-By: " + "Cla" + "ude <noreply@anthropic.com>"
    ev = dict(deny_event(work), session_id="strictseq0330abcd", tool_input={"command": f"git commit -m x -m '{co}'"})
    seq = (["--strict"], [], ["--strict"], [], ["--managed"])
    res = {}
    for via in ("slow", "hookd"):
        home = os.path.join(root, "sq" + via[:2])
        os.makedirs(home)
        install(home, client, sock)
        env = base_env(home, PANTHEON_WINDOW="w1")
        res[via] = [(slow if via == "slow" else wrap)(a, ev, env, work)[0] for a in seq]
        marker = os.path.join(home, ".local", "state", "pantheon", "guard-strict", ev["session_id"])
        res[via + "-marker"] = open(marker, encoding="utf-8").read() if os.path.exists(marker) else None
        res[via + "-log"] = fb_lines(home)
    check("strict → плагин → strict → плагин → managed через демон: те же ответы, что медленным путём, без откатов",
          res["hookd"] == res["slow"] and not res["hookd-log"], (res["hookd"], res["slow"], res["hookd-log"]))
    check("строгий guard через демон отказал оба раза и записал метку окна w1\\tBash в HOME вызова",
          [dec(r) for r in res["hookd"][0::2][:2]] == ["deny", "deny"] and res["hookd-marker"] == "w1\tBash\n",
          ([dec(r) for r in res["hookd"]], res["hookd-marker"]))


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
    # решение не пришло за 8,5 с — медленный путь
    home = os.path.join(root, "fsr")
    os.makedirs(home)
    d = install(home, client)
    fake = Fake(os.path.join(d, "hookd.sock"), b_ack_hang)
    try:
        ref, t_ref = slow(["--strict"], ev, base_env(home), work)
        got, t_got = wrap(["--strict"], ev, base_env(home), work)
    finally:
        fake.close()
    check("отказ: «принят», но решения нет 8,5 с → медленный путь, причина no-reply (ждали 8,5 с, не больше 10)",
          got == ref and reasons(home) == ["no-reply"] and 8.4 < t_got - t_ref < 9.8 + t_ref,
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
            ("запрос больше 8 МиБ", None, b"", "G2 9000000 1\n", "F big")):
        got = raw_call(sock, h, b, line=line)
        check(f"демон: {name} → «{want}»", got == want, got)
    if not client:
        print("пропущено: без клиента — отказы демона через клиент")
        return
    # через клиент: кодировка и локаль ведут на медленный путь с тем же решением
    for name, raw, extra, want in (("событие не UTF-8", b'{"hook_event_name": "PreToolUse", "x": "\xff"}', {},
                                    "encoding"),
                                   ("локаль KOI8-R", None, {"LC_ALL": "ru_RU.KOI8-R"}, "locale")):
        h2 = os.path.join(root, "d" + want[:3])
        os.makedirs(h2)
        install(h2, client, sock)
        e2 = base_env(h2, **extra)
        ref, _ = slow(["--strict"], deny_event(work), e2, work, raw=raw)
        got, _ = wrap(["--strict"], deny_event(work), e2, work, raw=raw)
        check(f"клиент: {name} → медленный путь с тем же ответом, причина {want}",
              got == ref and reasons(h2) == [want], (got, ref, fb_lines(h2)))


def patched_copy(root, name):
    """Копия плагина guard: guard.run убивает себя (KILLME) или выходит кодом 99 (EXIT99) — для проб демона."""
    copy = os.path.join(root, name)
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    with open(os.path.join(copy, "hooks", "guard.py"), "a", encoding="utf-8") as fh:
        fh.write("\n_run0 = run\n\n\ndef run(argv, raw=None):\n"
                 "    if raw and b'KILLME' in raw:\n        os.kill(os.getpid(), signal.SIGKILL)\n"
                 "    if raw and b'EXIT99' in raw:\n        os._exit(99)\n    return _run0(argv, raw)\n")
    return copy


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
            test_flag_off(root, client)
            test_equivalence(root, client, sock)
            test_strict_sequence(root, client, sock)
            test_failures(root, client)
            test_copy_daemon(root, client)
            test_canary(root, client, sock)
            test_supply(root, client)
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
