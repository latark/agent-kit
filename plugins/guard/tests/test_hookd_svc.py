#!/usr/bin/env python3
"""Служба демона хуков (metis-0811, часть 2): исполняемый файл службы hooks/hookd-svc.c (pantheon-hookd), режимы
демона --fd и --tcc-probe, счёт решений (hookd-calls.log), установка и --check scripts/hookd-install.sh.

Запуск: python3 -I plugins/guard/tests/test_hookd_svc.py   (код выхода 0 — все прошли)
Всё — во временной папке, HOME подменён. launchd не трогается: launchctl подменён (PANTHEON_HOOKD_LAUNCHCTL) тестовым,
который задание с RunAtLoad запускает ответственным за себя (posix_spawn + responsibility_spawnattrs_setdisclaim), как
это делает launchd. Так проверяется главное свойство обёртки: ответственный процесс TCC у Python-демона — pantheon-hookd.
- daemon.py: плохие --fd, --socket вместе с --fd, --tcc-probe без файла — код 64; не сокет, не слушающий — код 1;
- --tcc-probe: ok, denied (EACCES), missing по каждой папке, путь ответственного процесса; файл не записать — код 1;
- --fd: демон отвечает на запросы через переданный сокет; решения считаются (отказы «F …» — нет), строка
  «время<TAB>ok<TAB>число» — перед выходом по простою, по stale, по SIGTERM и раз в FLUSH_EVERY, в том числе
  в тишине после решения;
- hookd-build.sh --svc: собирает pantheon-hookd с метками .sum и .src, тот же исходник — без пересборки, правка — заново;
- pantheon-hookd: DYLD_INSERT_LIBRARIES не внедряет код (сегмент __RESTRICT и подпись ad-hoc с hardened runtime,
  Б1 argus #320); подпись не прошла или без runtime — сборка отказывает; старая сборка без runtime — заново;
- pantheon-hookd: папку hooks и файл итога из аргументов не берёт (64), чужой python.sh не запускает: нет
  pantheon-hookd.hooks, он открыт другим или ссылка, путь не канонический, папка hooks не из кэша guard
  (~/.claude/plugins/cache/agent-kit/guard/<версия>/hooks) или открыта всем, копия файла вне
  ~/.cache/pantheon/hookd/bin — код 78 (confused deputy, находка 05.11); окружение ребёнка — только HOME и PATH;
  вне launchd — 1 и причина; код ребёнка и SIGTERM (ребёнку, код 143) передаются; Python-ребёнок приписан ему;
- hookd-install.sh: установка из рабочей копии — отказ (код 1), из кэша — plist с pantheon-hookd первым, проба под
  «launchd», таблица доступа, задание пробы снято; --check — в порядке (код 0), нет доступа (код 1, команда
  «Файлы и папки», перезапуск службы), старая установка, нет службы, проба без итога, canary-diff, папка демона
  открыта окну.
"""
import json
import os
import plistlib
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_hookd as TH  # noqa: E402 — помощники протокола G2

PLUGIN = TH.PLUGIN
HOOKS = TH.HOOKS
DAEMON = TH.DAEMON
LAUNCHER = TH.LAUNCHER
BUILD = TH.BUILD
INSTALL = TH.INSTALL
SVC_SRC = os.path.join(HOOKS, "hookd-svc.c")
MAC = sys.platform == "darwin"
results = []
PROCS = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:900]))


def env_for(home, **kw):
    return TH.base_env(home, **kw)


def daemon_cli(home, *args, pass_fds=()):
    r = subprocess.run(["/bin/sh", LAUNCHER, DAEMON, *args], env=env_for(home), capture_output=True, text=True,
                       timeout=60, pass_fds=pass_fds)
    return r.returncode, (r.stderr.strip().splitlines() or [""])[-1]


def calls_lines(home):
    try:
        with open(os.path.join(home, ".local", "state", "pantheon", "logs", "hookd-calls.log"), encoding="utf-8") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def calls_total(home):
    return sum(int(ln.split("\t")[2]) for ln in calls_lines(home) if ln.count("\t") == 2)


# --- daemon.py: аргументы, проба, --fd, счёт ----------------------------------------------------------------------

def test_cli(root):
    home = os.path.join(root, "cli")
    os.makedirs(home)
    for args in (["--fd", "1"], ["--fd", "x"], ["--fd", "5", "--socket", os.path.join(root, "s")],
                 ["--tcc-probe", "x", "--fd", "5"], ["--tcc-probe"]):
        code, last = daemon_cli(home, *args)
        check(f"daemon.py {' '.join(args)} — код 64 и причина", code == 64 and "плохие аргументы" in last, (code, last))
    code, last = daemon_cli(home, "--fd", "77")
    check("daemon.py --fd на закрытый номер — код 1, «сокет не получен»", code == 1 and "сокет не получен" in last,
          (code, last))
    fd = os.open(os.path.join(root, "plain"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        code, last = daemon_cli(home, "--fd", str(fd), pass_fds=(fd,))
    finally:
        os.close(fd)
    check("daemon.py --fd на обычный файл — код 1", code == 1 and "сокет не получен" in last, (code, last))
    a, b = socket.socketpair()
    try:
        code, last = daemon_cli(home, "--fd", str(a.fileno()), pass_fds=(a.fileno(),))
    finally:
        a.close()
        b.close()
    check("daemon.py --fd на соединённый сокет (socketpair) — код 1 и «не слушающий сокет Unix»",
          code == 1 and "не слушающий сокет Unix" in last, (code, last))
    u = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        code, last = daemon_cli(home, "--fd", str(u.fileno()), pass_fds=(u.fileno(),))
    finally:
        u.close()
    check("daemon.py --fd на непривязанный сокет Unix — код 1 и «не слушающий сокет Unix»",
          code == 1 and "не слушающий сокет Unix" in last, (code, last))
    u = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        u.bind(("127.0.0.1", 0))
        u.listen(1)
        code, last = daemon_cli(home, "--fd", str(u.fileno()), pass_fds=(u.fileno(),))
    except PermissionError:
        code, last = None, "пропущено: песочница не даёт местный порт"
    finally:
        u.close()
    if code is None:
        print(last)
    else:
        check("daemon.py --fd на слушающий сокет TCP — код 1 (только Unix)",
              code == 1 and "не слушающий сокет Unix" in last, (code, last))


def probe_home(root, name):
    home = os.path.join(root, name)
    for d in ("Desktop", "Documents", os.path.join("Library", "Mobile Documents")):
        os.makedirs(os.path.join(home, d))
    os.chmod(os.path.join(home, "Documents"), 0)  # EACCES — как отказ TCC (EPERM) для пробы
    return home


def test_probe(root):
    home = probe_home(root, "pr")
    out = os.path.join(home, "r.json")
    try:
        code, last = daemon_cli(home, "--tcc-probe", out)
        res = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    finally:
        os.chmod(os.path.join(home, "Documents"), 0o700)
    check("--tcc-probe: код 0; Desktop ok, Documents denied (EACCES), Downloads missing, iCloud Drive ok",
          code == 0 and res.get("dirs") == {"Desktop": "ok", "Documents": "denied", "Downloads": "missing",
                                            "iCloud Drive": "ok"}, (code, last, res))
    check("--tcc-probe: в итоге путь ответственного процесса (macOS) и HOME, временного файла нет",
          (bool(res.get("responsible")) or not MAC) and res.get("home") == home and not os.path.exists(out + ".tmp"),
          res)
    code, last = daemon_cli(home, "--tcc-probe", os.path.join(home, "nope", "r.json"))
    check("--tcc-probe: файл итога не записать — код 1, причина последней строкой",
          code == 1 and last.startswith("hookd: итог пробы не записан"), (code, last))


def listening(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path)
    s.listen(16)
    return s


def valid_call(sock, work, home):
    hdr = {"argv": ["--strict"], "cwd": work, "env": env_for(home), "hooks": HOOKS, "version": TH.plugin_version(),
           "umask": 0o22}
    return TH.raw_call(sock, hdr, json.dumps(TH.deny_event(work)).encode())


def spawn_fd_daemon(root, home, path, hooks=HOOKS, idle="3"):
    lst = listening(path)
    log = open(os.path.join(root, os.path.basename(home) + ".log"), "ab")
    p = subprocess.Popen(["/bin/sh", os.path.join(hooks, "python.sh"), os.path.join(hooks, "daemon.py"),
                          "--fd", str(lst.fileno()), "--idle", idle], env=env_for(home), stdout=log, stderr=log,
                         pass_fds=(lst.fileno(),))
    lst.close()  # сокет держит только демон, как после pantheon-hookd
    PROCS.append(p)
    return p


def test_fd_daemon(root):
    work = os.path.join(root, "work")
    home = os.path.join(root, "fdh")
    os.makedirs(home)
    path = os.path.join(root, "fd.sock")
    p = spawn_fd_daemon(root, home, path)
    first = valid_call(path, work, home)
    bad = TH.raw_call(path, None, b"", line="G3 1 1\n")
    second = valid_call(path, work, home)
    check("--fd: демон отвечает через переданный сокет — «X 0 …», мусор — «F proto»",
          first.startswith("X 0 ") and second.startswith("X 0 ") and bad == "F proto", (first, bad, second))
    check("счёт решений: пока демон жив и минута не прошла, строки нет", calls_lines(home) == [], calls_lines(home))
    try:
        code = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        code = None
    check("счёт решений: выход по простою — код 0 и одна строка «время<TAB>ok<TAB>2» (отказ F не считается)",
          code == 0 and len(calls_lines(home)) == 1 and calls_lines(home)[0].endswith("\tok\t2")
          and len(calls_lines(home)[0]) == 19 + len("\tok\t2"), (code, calls_lines(home)))


def patched_tree(root, name, flush_every=None):
    copy = os.path.join(root, name)
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    if flush_every is not None:
        p = os.path.join(copy, "hooks", "daemon.py")
        body = open(p, encoding="utf-8").read()
        assert "FLUSH_EVERY = 60" in body
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body.replace("FLUSH_EVERY = 60", f"FLUSH_EVERY = {flush_every}", 1))
    return copy


def hdr_for(copy, work, home):
    with open(os.path.join(copy, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
        ver = json.load(fh)["version"]
    return {"argv": ["--strict"], "cwd": work, "env": env_for(home), "hooks": os.path.join(copy, "hooks"),
            "version": ver, "umask": 0o22}


def test_flush_paths(root):
    work = os.path.join(root, "work")
    # раз в FLUSH_EVERY: копия с FLUSH_EVERY = 0 пишет строку, пока демон жив
    copy = patched_tree(root, "fl0", flush_every=0)
    home = os.path.join(root, "flh")
    os.makedirs(home)
    path = os.path.join(root, "f0.sock")
    p = spawn_fd_daemon(root, home, path, hooks=os.path.join(copy, "hooks"), idle="300")
    got = TH.raw_call(path, hdr_for(copy, work, home), json.dumps(TH.deny_event(work)).encode())
    end = time.monotonic() + 10
    while time.monotonic() < end and not calls_lines(home):
        time.sleep(0.05)
    check("счёт решений: срок FLUSH_EVERY прошёл — строка «ok 1», пока демон жив",
          got.startswith("X 0 ") and p.poll() is None and calls_total(home) == 1, (got, p.poll(), calls_lines(home)))
    TH.stop(p)
    # выход по stale: строка пишется перед выходом
    copy = patched_tree(root, "fls")
    home = os.path.join(root, "fsh")
    os.makedirs(home)
    path = os.path.join(root, "fs.sock")
    p = spawn_fd_daemon(root, home, path, hooks=os.path.join(copy, "hooks"), idle="300")
    got = TH.raw_call(path, hdr_for(copy, work, home), json.dumps(TH.deny_event(work)).encode())
    time.sleep(0.3)  # байт ребёнка дошёл до родителя
    rules = os.path.join(copy, "hooks", "guard_rules.py")
    st = os.stat(rules)
    os.utime(rules, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    stale = TH.raw_call(path, hdr_for(copy, work, home), json.dumps(TH.deny_event(work)).encode())
    try:
        code = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        code = None
    check("счёт решений: выход по stale — код 0 и строка «ok 1» перед выходом",
          got.startswith("X 0 ") and stale == "F stale" and code == 0 and calls_total(home) == 1,
          (got, stale, code, calls_lines(home)))
    # HOME не пишется: строка не записана, демон работает дальше, причина — в его журнале
    copy = patched_tree(root, "flr", flush_every=0)
    home = os.path.join(root, "frh")
    os.makedirs(os.path.join(home, ".local", "state", "pantheon"))
    with open(os.path.join(home, ".local", "state", "pantheon", "logs"), "w") as fh:
        fh.write("файл на месте папки")
    path = os.path.join(root, "fr.sock")
    p = spawn_fd_daemon(root, home, path, hooks=os.path.join(copy, "hooks"), idle="300")
    got = TH.raw_call(path, hdr_for(copy, work, home), json.dumps(TH.deny_event(work)).encode())
    time.sleep(0.5)
    again = TH.raw_call(path, hdr_for(copy, work, home), json.dumps(TH.deny_event(work)).encode())
    TH.stop(p)
    log = open(os.path.join(root, "frh.log"), encoding="utf-8", errors="replace").read()
    check("счёт решений: журнал не записать — решения идут дальше, причина в журнале демона",
          got.startswith("X 0 ") and again.startswith("X 0 ") and "не записан в hookd-calls.log" in log,
          (got, again, log[-400:]))
    # SIGTERM (launchctl bootout, kickstart -k): строка пишется перед выходом, код 0 (Д1 argus #320)
    home = os.path.join(root, "fth")
    os.makedirs(home)
    path = os.path.join(root, "ft.sock")
    p = spawn_fd_daemon(root, home, path, idle="300")
    got = valid_call(path, work, home)
    time.sleep(0.3)  # байт ребёнка дошёл до родителя
    p.send_signal(signal.SIGTERM)
    try:
        code = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        code = None
    check("счёт решений: SIGTERM — код 0 и строка «ok 1» перед выходом",
          got.startswith("X 0 ") and code == 0 and calls_total(home) == 1, (got, code, calls_lines(home)))
    # SIGTERM, пока байт ребёнка ещё не прочитан: в копии ребёнок пишет байт через 1 с после ответа; демон остановлен
    # (SIGSTOP) до того, байт лёг в канал, затем SIGTERM и SIGCONT — select видит и SIGTERM, и байт сразу
    copy = patched_tree(root, "flu")
    dp = os.path.join(copy, "hooks", "daemon.py")
    body = open(dp, encoding="utf-8").read()
    slow = body.replace('                os.write(self.count_w, b".")',
                        '                time.sleep(1)\n                os.write(self.count_w, b".")', 1)
    if slow == body:
        check("копия демона: байт счёта с задержкой", False)
        return
    with open(dp, "w", encoding="utf-8") as fh:
        fh.write(slow)
    home = os.path.join(root, "fuh")
    os.makedirs(home)
    path = os.path.join(root, "fu.sock")
    p = spawn_fd_daemon(root, home, path, hooks=os.path.join(copy, "hooks"), idle="300")
    got = TH.raw_call(path, hdr_for(copy, work, home), json.dumps(TH.deny_event(work)).encode())
    p.send_signal(signal.SIGSTOP)
    time.sleep(1.5)  # ребёнок дописал байт, родитель его не прочёл
    p.send_signal(signal.SIGTERM)
    p.send_signal(signal.SIGCONT)
    try:
        code = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        code = None
    check("счёт решений: SIGTERM при непрочитанном байте счёта — он тоже в строке «ok 1»",
          got.startswith("X 0 ") and code == 0 and calls_total(home) == 1, (got, code, calls_lines(home)))
    # тишина после решения: строка — через FLUSH_EVERY, а не на следующем соединении или по простою
    copy = patched_tree(root, "flq", flush_every=3)
    home = os.path.join(root, "fqh")
    os.makedirs(home)
    path = os.path.join(root, "fq.sock")
    p = spawn_fd_daemon(root, home, path, hooks=os.path.join(copy, "hooks"), idle="300")
    got = TH.raw_call(path, hdr_for(copy, work, home), json.dumps(TH.deny_event(work)).encode())
    end = time.monotonic() + 10
    while time.monotonic() < end and not calls_lines(home):
        time.sleep(0.05)
    check("счёт решений: после решения тишина — строка «ok 1» через FLUSH_EVERY, демон жив",
          got.startswith("X 0 ") and p.poll() is None and calls_total(home) == 1, (got, p.poll(), calls_lines(home)))
    TH.stop(p)


# --- pantheon-hookd ---------------------------------------------------------------------------------------------

def build_svc(home, build=BUILD):
    r = subprocess.run(["/bin/sh", build, "--svc"], env=env_for(home), capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def test_build_svc(root):
    home = os.path.join(root, "bsv")
    os.makedirs(home)
    code, out, err = build_svc(home)
    want = os.path.join(TH.hookd_dir(home), "bin", "pantheon-hookd")
    if code != 0 and shutil.which("cc") is None:
        print("пропущено: нет компилятора cc — pantheon-hookd не собрать")
        return None
    ok = code == 0 and out == want and os.access(want, os.X_OK)
    check("hookd-build.sh --svc собрал ~/.cache/pantheon/hookd/bin/pantheon-hookd с метками .sum и .src", ok
          and len(open(want + ".sum").read().strip()) == 64 and len(open(want + ".src").read().strip()) == 64,
          (code, out, err[-300:]))
    if not ok:
        return None
    st = os.stat(want)
    code2, out2, _ = build_svc(home)
    st2 = os.stat(want)
    check("hookd-build.sh --svc: тот же исходник — без пересборки (тот же файл: macOS не спросит доступ снова)",
          code2 == 0 and out2 == want and (st.st_ino, st.st_mtime_ns) == (st2.st_ino, st2.st_mtime_ns),
          (code2, out2, st.st_ino, st2.st_ino))
    os.chmod(want, 0o755)
    with open(want, "ab") as fh:  # файл подменён — метка .sum не совпала: пересборка
        fh.write(b"x")
    code3, _, _ = build_svc(home)
    check("hookd-build.sh --svc: файл не совпал с меткой .sum — пересобран",
          code3 == 0 and TH.hashlib.sha256(open(want, "rb").read()).hexdigest() == open(want + ".sum").read().strip(),
          code3)
    copy = patched_tree(root, "bsvc")
    with open(os.path.join(copy, "hooks", "hookd-svc.c"), "a", encoding="utf-8") as fh:
        fh.write("/* правка */\n")
    src_before = open(want + ".src").read()
    code4, _, err4 = build_svc(home, build=os.path.join(copy, "hooks", "hookd-build.sh"))
    check("hookd-build.sh --svc: исходник изменился — пересборка, новая метка .src",
          code4 == 0 and open(want + ".src").read() != src_before, (code4, err4[-300:]))
    code5, out5, _ = build_svc(home)  # обратно на исходник этого дерева
    return out5 if code5 == 0 else None


INJ_C = r'''
#include <fcntl.h>
#include <stdlib.h>
#include <unistd.h>
__attribute__((constructor)) static void injected(void) {
    const char *m = getenv("HOOKD_INJ_MARK");
    if (m) { int fd = open(m, O_WRONLY | O_CREAT | O_APPEND, 0600); if (fd >= 0) { write(fd, "x", 1); close(fd); } }
}
'''


def test_hardened(root, svc):
    """Б1 argus #320: DYLD_INSERT_LIBRARIES не внедряет чужой код в pantheon-hookd (иначе он работал бы с его TCC)."""
    d = os.path.join(root, "inj")
    os.makedirs(d)
    with open(os.path.join(d, "inj.c"), "w") as fh:
        fh.write(INJ_C)
    with open(os.path.join(d, "plain.c"), "w") as fh:
        fh.write("int main(void) { return 0; }\n")
    dylib, plain = os.path.join(d, "inj.dylib"), os.path.join(d, "plain")
    cc = [subprocess.run(["/usr/bin/cc", *a], capture_output=True, text=True, timeout=120)
          for a in (["-dynamiclib", "-o", dylib, os.path.join(d, "inj.c")], ["-o", plain, os.path.join(d, "plain.c")])]
    if any(r.returncode for r in cc):
        check("тестовая dylib и программа собраны", False, [r.stderr[-300:] for r in cc])
        return
    home = svc_home(svc)

    def injected(prog, *args):
        mark = os.path.join(d, "mark-" + os.path.basename(prog))
        subprocess.run([prog, *args], env=env_for(home, DYLD_INSERT_LIBRARIES=dylib, HOOKD_INJ_MARK=mark),
                       capture_output=True, timeout=30)
        return os.path.exists(mark)

    check("проверка теста: в программу, собранную голым cc, DYLD_INSERT_LIBRARIES внедряет dylib", injected(plain))
    check("pantheon-hookd: DYLD_INSERT_LIBRARIES не внедряет чужой код (hardened runtime, __RESTRICT)",
          not injected(svc, "--bogus"))
    r = subprocess.run(["/usr/bin/codesign", "-dv", svc], capture_output=True, text=True, timeout=30)
    check("pantheon-hookd подписан ad-hoc с hardened runtime (codesign -o runtime)",
          r.returncode == 0 and "Signature=adhoc" in r.stderr and "Identifier=pantheon-hookd\n" in r.stderr
          and re.search(r"^CodeDirectory .*flags=0x[0-9a-f]+\([^)]*\bruntime\b", r.stderr, re.M), r.stderr[-400:])
    with open(svc, "rb") as fh:
        head = fh.read(65536)
    check("pantheon-hookd: сегмент __RESTRICT — второй слой, если подпись снимут", b"__RESTRICT\0" in head)
    # уже стоящий файл без hardened runtime (старая сборка) при том же исходнике — пересобирается
    subprocess.run(["/usr/bin/codesign", "-s", "-", "-f", "-i", "pantheon-hookd", svc], capture_output=True, timeout=30)
    with open(svc + ".sum", "w") as fh:
        fh.write(TH.hashlib.sha256(open(svc, "rb").read()).hexdigest() + "\n")
    code, out, err = build_svc(home)
    r = subprocess.run(["/usr/bin/codesign", "-dv", svc], capture_output=True, text=True, timeout=30)
    check("hookd-build.sh --svc: стоящий файл без hardened runtime при том же исходнике — пересобран с ним",
          code == 0 and out == svc and re.search(r"flags=0x[0-9a-f]+\([^)]*\bruntime\b", r.stderr), (code, err, r.stderr))
    # подпись не прошла или прошла без runtime — сборка отказывает и ничего не ставит (codesign подменён в копии)
    sign_fails = ('[ "$1" = -dv ] && { echo "CodeDirectory v=20500 size=1 flags=0x10002(adhoc,runtime) hashes=1+0" >&2;'
                  ' exit 0; }\necho "подмена: подпись не прошла" >&2\nexit 1\n')
    sign_noop = '[ "$1" = -dv ] && exec /usr/bin/codesign "$@"\nexit 0\n'
    for name, fake, why in (("bcs", sign_fails, "codesign не прошёл (код не 0)"),
                            ("bcn", sign_noop, "codesign прошёл, но в подписи нет runtime")):
        copy = patched_tree(root, name)
        p = os.path.join(copy, "hooks", "hookd-build.sh")
        body = open(p, encoding="utf-8").read()
        if "/usr/bin/codesign" not in body:
            check("hookd-build.sh --svc подписывает /usr/bin/codesign", False)
            return
        cs = os.path.join(root, name + "-codesign")
        with open(cs, "w") as fh:
            fh.write("#!/bin/sh\n" + fake)
        os.chmod(cs, 0o755)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body.replace("/usr/bin/codesign", cs))
        h2 = os.path.join(root, name + "h")
        os.makedirs(h2)
        code, out, err = build_svc(h2, build=p)
        want = os.path.join(TH.hookd_dir(h2), "bin", "pantheon-hookd")
        check(f"hookd-build.sh --svc: {why} — код 1, причина «codesign», файла службы и метки .sum нет",
              code == 1 and "codesign" in (err.splitlines() or [""])[-1] and not os.path.exists(want)
              and not os.path.exists(want + ".sum"), (code, out, err[-300:]))


def disclaim_spawn_code():
    """Текст функции запуска «как launchd»: процесс ответственен за себя (TCC спрашивает про него)."""
    return r'''
import ctypes, os
def spawn_self_responsible(argv, env):
    lib = ctypes.CDLL(None, use_errno=True)
    attr = ctypes.c_void_p()
    if lib.posix_spawnattr_init(ctypes.byref(attr)) != 0:
        raise OSError("posix_spawnattr_init")
    fn = lib.responsibility_spawnattrs_setdisclaim
    fn.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
    if fn(ctypes.byref(attr), 1) != 0:
        raise OSError("responsibility_spawnattrs_setdisclaim")
    c_argv = (ctypes.c_char_p * (len(argv) + 1))(*[a.encode() for a in argv], None)
    e = [f"{k}={v}".encode() for k, v in env.items()]
    c_env = (ctypes.c_char_p * (len(e) + 1))(*e, None)
    pid = ctypes.c_int()
    rc = lib.posix_spawn(ctypes.byref(pid), argv[0].encode(), None, ctypes.byref(attr), c_argv, c_env)
    if rc:
        raise OSError(rc, "posix_spawn")
    return pid.value
'''


def svc_home(svc):
    """HOME, от которого собран pantheon-hookd: …/<HOME>/.cache/pantheon/hookd/bin/pantheon-hookd."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(svc)))))


def pin_hooks(svc, path, mode=0o600):
    p = svc + ".hooks"
    if os.path.lexists(p):
        os.remove(p)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(path + "\n")
    os.chmod(p, mode)


def guard_cache(home):
    return os.path.join(home, ".claude", "plugins", "cache", "agent-kit", "guard")


def cached(home, ver):
    """Папка hooks проверенного дерева guard: <HOME>/.claude/plugins/cache/agent-kit/guard/<ver>/hooks."""
    return os.path.join(guard_cache(home), ver, "hooks")


def cache_tree(home, ver="9.9.9"):
    """Копия плагина в проверенное дерево подменённого HOME; путь к её папке hooks (realpath)."""
    dst = os.path.dirname(cached(home, ver))
    shutil.copytree(PLUGIN, dst, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    return os.path.realpath(os.path.join(dst, "hooks"))


def fake_hooks(d, script, mode=0o755):
    os.makedirs(d)
    with open(os.path.join(d, "python.sh"), "w") as fh:
        fh.write(script)
    open(os.path.join(d, "daemon.py"), "w").close()
    os.chmod(d, mode)
    return os.path.realpath(d)


def test_wrapper(root, svc):
    home = svc_home(svc)
    real_home = os.path.realpath(home)
    hooks_real = cache_tree(home)
    marker = os.path.join(root, "evil-ran")
    bad = f'echo ran >> "{marker}"\nexit 0\n'
    evil = fake_hooks(cached(home, "evil"), bad)  # в проверенном дереве: отказ — только от проверки своего случая

    def run(argv, **kw):
        return subprocess.run(argv, env=env_for(home, **kw), capture_output=True, text=True, timeout=30)

    def refused(name, r, code, words):
        ok = r.returncode == code and words in r.stderr and not os.path.exists(marker)
        check(name, ok, (r.returncode, r.stderr, os.path.exists(marker)))
        if os.path.exists(marker):
            os.remove(marker)

    pin_hooks(svc, hooks_real)
    for args in ([evil], [evil, "--tcc-probe"], ["--tcc-probe", os.path.join(root, "out.json")], ["--bogus"]):
        refused(f"pantheon-hookd {' '.join(args)}: папку hooks и файл итога из аргументов не берёт — код 64, "
                "чужой python.sh не запущен", run([svc, *args]), 64, "аргументов нет")
    r = run([svc])
    check("pantheon-hookd вне launchd — код 1, «сокет от launchd не получен»",
          r.returncode == 1 and "сокет от launchd не получен" in r.stderr, (r.returncode, r.stderr))
    # закрепление папки hooks: только свой файл 0600 с каноническим путём к своей закрытой папке
    os.remove(svc + ".hooks")
    refused("нет pantheon-hookd.hooks — код 78, ничего не запущено", run([svc, "--tcc-probe"]), 78,
            "нет pantheon-hookd.hooks")
    pin_hooks(svc, evil, mode=0o622)
    refused("pantheon-hookd.hooks открыт на запись другим — код 78, чужой python.sh не запущен",
            run([svc, "--tcc-probe"]), 78, "открыт другим")
    os.remove(svc + ".hooks")
    other = os.path.join(root, "pin-other")
    with open(other, "w") as fh:
        fh.write(evil + "\n")
    os.symlink(other, svc + ".hooks")
    refused("pantheon-hookd.hooks — ссылка — код 78, чужой python.sh не запущен", run([svc, "--tcc-probe"]), 78,
            "pantheon-hookd.hooks")
    pin_hooks(svc, os.path.join(evil, "..", "hooks"))
    refused("в pantheon-hookd.hooks путь с «..» — код 78", run([svc, "--tcc-probe"]), 78, "не канонический")
    # только проверенное дерево guard: рабочую копию и /tmp правят агенты (вторая находка 05.11)
    for where, path in (("рабочая копия (папка вне кэша плагинов)", os.path.join(root, "wt", "hooks")),
                        ("кэш guard без версии", os.path.join(guard_cache(home), "hooks")),
                        ("кэш guard, лишняя папка в версии", cached(home, os.path.join("a", "b"))),
                        ("кэш guard, папка не hooks", os.path.join(guard_cache(home), "1", "hooks2")),
                        ("кэш guard2 (имя с тем же началом)", os.path.join(guard_cache(home) + "2", "hooks"))):
        pin_hooks(svc, fake_hooks(path, bad))
        refused(f"папка hooks — {where} — код 78, её python.sh не запущен", run([svc, "--tcc-probe"]), 78,
                "не из проверенного дерева guard")
    open_dir = fake_hooks(cached(home, "open"), bad, mode=0o777)
    pin_hooks(svc, open_dir)
    refused("папка hooks открыта на запись всем — код 78, её python.sh не запущен", run([svc, "--tcc-probe"]), 78,
            "открыты на запись другим")
    pin_hooks(svc, evil)
    bindir = os.path.dirname(svc)
    os.chmod(bindir, 0o777)
    try:
        r = run([svc, "--tcc-probe"])
    finally:
        os.chmod(bindir, 0o755)
    refused("папка bin открыта на запись всем — код 78, pantheon-hookd.hooks в ней не читается", r, 78, "папка bin")
    elsewhere = os.path.join(root, "elsewhere")
    os.makedirs(elsewhere)
    copy = os.path.join(elsewhere, "pantheon-hookd")
    shutil.copy2(svc, copy)
    pin_hooks(copy, evil)
    refused("копия pantheon-hookd вне ~/.cache/pantheon/hookd/bin — код 78, её pantheon-hookd.hooks не читается",
            run([copy, "--tcc-probe"]), 78, "запущен не из")
    # ребёнок: окружение только HOME и PATH, итог пробы — свой путь, код и сигнал передаются
    out = os.path.join(root, "child.txt")
    fake = fake_hooks(cached(home, "fake"), f'{{ env; echo "ARGS $1 $2 $3"; }} > "{out}"\n'
                      'case $2 in --tcc-probe) ;; *) exit 99 ;; esac\n'
                      '[ -f "$HOME/sleep-please" ] && exec /bin/sleep 30\nexit 7\n')
    pin_hooks(svc, fake)
    r = run([svc, "--tcc-probe"], PYTHONPATH="/x", FOO="bar", PYTHONEXECUTABLE="/x/python", BASH_ENV="/x/env")
    seen = open(out).read() if os.path.exists(out) else ""
    env_names = sorted(ln.split("=", 1)[0] for ln in seen.splitlines() if "=" in ln and not ln.startswith("ARGS"))
    check("pantheon-hookd: код ребёнка — его код (7)", r.returncode == 7, (r.returncode, r.stderr))
    check("pantheon-hookd: окружение ребёнка — HOME от своего пути и PATH; PYTHON*, BASH_ENV и прочее не доходят",
          f"HOME={real_home}\n" in seen and "FOO" not in seen and "PYTHON" not in seen and "BASH_ENV" not in seen
          and set(env_names) <= {"HOME", "PATH", "PWD", "SHLVL", "_", "OLDPWD"}, seen)
    check("pantheon-hookd --tcc-probe: итог — всегда ~/.cache/pantheon/hookd/probe/result.json",
          f"ARGS {fake}/daemon.py --tcc-probe {real_home}/.cache/pantheon/hookd/probe/result.json" in seen, seen)
    open(os.path.join(home, "sleep-please"), "w").close()
    p = subprocess.Popen([svc, "--tcc-probe"], env=env_for(home))
    PROCS.append(p)
    time.sleep(0.5)
    p.send_signal(signal.SIGTERM)
    try:
        code = p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        code = None
    os.remove(os.path.join(home, "sleep-please"))
    check("pantheon-hookd: SIGTERM передан ребёнку — выход 128+15", code == 143, code)
    if not MAC:
        print("пропущено: нужен macOS — ответственный процесс TCC")
        return
    # главное свойство: Python-ребёнок приписан pantheon-hookd, когда тот ответственен за себя (как задание launchd)
    pin_hooks(svc, hooks_real)
    for d in ("Desktop", "Documents", os.path.join("Library", "Mobile Documents"),
              os.path.join(".cache", "pantheon", "hookd", "probe")):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    os.chmod(os.path.join(home, "Documents"), 0)
    res_path = os.path.join(home, ".cache", "pantheon", "hookd", "probe", "result.json")
    ns = {}
    exec(disclaim_spawn_code(), ns)  # noqa: S102 — код теста
    try:
        pid = ns["spawn_self_responsible"]([svc, "--tcc-probe"], env_for(home))
        _, st = os.waitpid(pid, 0)
        res = json.load(open(res_path, encoding="utf-8")) if os.path.exists(res_path) else {}
    finally:
        os.chmod(os.path.join(home, "Documents"), 0o700)
    check("pantheon-hookd под «launchd» (ответственен за себя): Python-демон приписан ему, а не Python.app",
          os.waitstatus_to_exitcode(st) == 0 and os.path.realpath(res.get("responsible") or "-") == os.path.realpath(svc)
          and res.get("dirs", {}).get("Documents") == "denied", res)


# --- hookd-install.sh с подменённым launchctl --------------------------------------------------------------------

FAKE_LCTL = r'''
import os, plistlib, signal, sys
D = os.environ["FAKE_LCTL_DIR"]
with open(os.path.join(D, "calls.log"), "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\n")
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
def label_of(target):
    return target.split("/", 2)[2] if target.count("/") >= 2 else ""
if cmd == "bootstrap":
    pl = plistlib.load(open(sys.argv[3], "rb"))
    with open(os.path.join(D, "loaded-" + pl["Label"]), "w") as fh:
        fh.write(sys.argv[3])
    with open(os.path.join(D, "plist-" + pl["Label"]), "wb") as fh:
        plistlib.dump(pl, fh)
    if pl.get("RunAtLoad") and not os.environ.get("FAKE_NORUN"):
        pid = spawn_self_responsible(pl["ProgramArguments"], dict(os.environ, **pl.get("EnvironmentVariables", {})))
        open(os.path.join(D, "pid-" + pl["Label"]), "w").write(str(pid))
    sys.exit(0)
if cmd == "bootout":
    lab = label_of(sys.argv[2])
    try:
        os.kill(int(open(os.path.join(D, "pid-" + lab)).read()), signal.SIGKILL)
    except (OSError, ValueError):
        pass
    try:
        os.unlink(os.path.join(D, "loaded-" + lab))
    except FileNotFoundError:
        sys.exit(3)
    sys.exit(0)
if cmd == "print":
    sys.exit(0 if os.path.exists(os.path.join(D, "loaded-" + label_of(sys.argv[2]))) else 113)
sys.exit(64)
'''


def fake_launchctl(root):
    p = os.path.join(root, "launchctl")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(f"#!{sys.executable} -I\n" + disclaim_spawn_code() + FAKE_LCTL)
    os.chmod(p, 0o755)
    return p


def inst(home, lctl, *args, script=INSTALL, **kw):
    d = os.path.join(home, "lctl")
    os.makedirs(d, exist_ok=True)
    env = env_for(home, **{"PANTHEON_HOOKD_LAUNCHCTL": lctl, "FAKE_LCTL_DIR": d, "PANTHEON_HOOKD_PROBE_WAIT": "30", **kw})
    r = subprocess.run(["/bin/sh", script, *args], env=env, capture_output=True, text=True, timeout=300)
    calls = open(os.path.join(d, "calls.log")).read().splitlines() if os.path.exists(os.path.join(d, "calls.log")) else []
    return r.returncode, r.stdout, r.stderr, calls


def last_line(s):
    return (s.strip().splitlines() or [""])[-1]


def test_templates():
    """Оба шаблона — строгий XML (plutil -lint прощает «--» в комментарии, launchd и plistlib — нет)."""
    for name, want in (("pantheon.svc.hookd.plist.in", ["/S/pantheon-hookd"]),
                       ("pantheon.hookd.probe.plist.in", ["/S/pantheon-hookd", "--tcc-probe"])):
        with open(os.path.join(PLUGIN, "launchd", name), encoding="utf-8") as fh:
            body = fh.read()
        body = body.replace("@SVC@", "/S/pantheon-hookd").replace("@HOOKS@", "/H").replace("@HOME@", "/home") \
            .replace("@OUT@", "/O/r.json")
        try:
            pl = plistlib.loads(body.encode())
        except Exception as e:  # noqa: BLE001
            pl = {"error": str(e)}
        check(f"шаблон {name}: строгий plist, ProgramArguments — pantheon-hookd первым",
              pl.get("ProgramArguments") == want and "KeepAlive" not in pl, pl)


def test_install(root, svc_built):
    if not MAC or shutil.which("plutil") is None:
        print("пропущено: нужен macOS (plutil, launchd) — установка и --check")
        return
    lctl = fake_launchctl(root)
    home = os.path.join(root, "in")
    for d in ("Desktop", "Documents", "Downloads", os.path.join("Library", "Mobile Documents")):
        os.makedirs(os.path.join(home, d))
    svc = os.path.join(TH.hookd_dir(home), "bin", "pantheon-hookd")
    plist = os.path.join(home, "Library", "LaunchAgents", "pantheon.svc.hookd.plist")
    # ставить — только из проверенного дерева guard (вторая находка 05.11): рабочая копия — отказ
    code, out, err, calls = inst(home, lctl)
    check("установка из рабочей копии — код 1, «ставить только из проверенного дерева», ничего не поставлено",
          code == 1 and "ставить только из проверенного дерева guard" in err and not os.path.exists(plist)
          and not os.path.exists(svc + ".hooks") and not calls, (code, out[-300:], err[-300:], calls))
    deep = cache_tree(home, os.path.join("x", "y"))
    code, out, err, calls = inst(home, lctl, script=os.path.join(os.path.dirname(deep), "scripts", "hookd-install.sh"))
    check("установка из кэша guard, но версия — две папки (x/y) — код 1, ничего не поставлено",
          code == 1 and "ставить только из проверенного дерева guard" in err and not os.path.exists(plist)
          and not calls, (code, out[-300:], err[-300:], calls))
    hooks_c = cache_tree(home)
    sc = os.path.join(os.path.dirname(hooks_c), "scripts", "hookd-install.sh")

    def ins(*a, **k):
        return inst(home, lctl, *a, script=sc, **k)

    code, out, err, calls = ins()
    pl = plistlib.load(open(plist, "rb")) if os.path.exists(plist) else {}
    check("установка: код 0, plist службы — один pantheon-hookd, без папки hooks в аргументах",
          code == 0 and pl.get("ProgramArguments") == [svc] and os.access(svc, os.X_OK),
          (code, out[-600:], err[-600:], pl.get("ProgramArguments")))
    pin = svc + ".hooks"
    pin_text = open(pin).read() if os.path.exists(pin) else ""
    check("установка: pantheon-hookd.hooks — папка hooks этого дерева, файл 0600",
          pin_text == hooks_c + "\n" and stat.S_IMODE(os.lstat(pin).st_mode) == 0o600,
          (pin_text, oct(os.lstat(pin).st_mode) if os.path.exists(pin) else None))
    probe_pl = os.path.join(home, "lctl", "plist-pantheon.hookd.probe")
    ppl = plistlib.load(open(probe_pl, "rb")) if os.path.exists(probe_pl) else {}
    check("установка: после bootstrap службы — разовое задание пробы через тот же pantheon-hookd (RunAtLoad, без "
          "KeepAlive), затем снято",
          any(c.startswith("bootstrap gui/") and c.endswith("pantheon.svc.hookd.plist") for c in calls)
          and ppl.get("ProgramArguments", [None])[0] == svc and "--tcc-probe" in ppl.get("ProgramArguments", [])
          and ppl.get("RunAtLoad") is True and "KeepAlive" not in ppl
          and calls[-1].endswith("/pantheon.hookd.probe") and calls[-1].startswith("bootout")
          and not os.path.exists(os.path.join(TH.hookd_dir(home), "probe", "probe.plist")), (calls, ppl))
    check("установка: таблица доступа — все четыре папки «есть», ответственный — pantheon-hookd",
          "итог: доступ ко всем папкам есть" in out and out.count(" есть") >= 4 and svc in out, out[-900:])
    code, out, err, _ = ins("--check")
    check("--check: служба загружена, доступ есть, окон нет, вызовов нет — код 0, «всё в порядке»",
          code == 0 and last_line(out) == "hookd-install --check: всё в порядке" and "загружена" in out
          and "вызовов нет" in out, (code, out[-900:], err[-300:]))
    st_before = os.stat(plist).st_mtime_ns
    os.chmod(os.path.join(home, "Documents"), 0)
    try:
        code, out, err, _ = ins("--check")
    finally:
        os.chmod(os.path.join(home, "Documents"), 0o700)
    uid = os.getuid()
    check("--check: нет доступа к Documents — код 1; команда «Файлы и папки», «Полный доступ к диску», перезапуск "
          "службы, итог последней строкой",
          code == 1 and "Documents     НЕТ" in out
          and 'open "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders"' in out
          and "Privacy_AllFiles" in out and f"launchctl kickstart -k gui/{uid}/pantheon.svc.hookd" in out
          and "tccutil" in out and last_line(out).endswith("нет доступа к папкам"), (code, out[-1200:]))
    check("--check ничего не правит: plist службы тот же", os.stat(plist).st_mtime_ns == st_before)
    # служба закреплена за другим деревом guard
    other = os.path.realpath(os.path.join(root, "work"))
    with open(pin, "w") as fh:
        fh.write(other + "\n")
    code, out, err, _ = ins("--check", PANTHEON_HOOKD_PROBE_WAIT="1")
    check("--check: pantheon-hookd.hooks указывает на другое дерево — код 1, «служба другого дерева» и оба пути",
          code == 1 and "служба другого дерева" in last_line(out) and other in out
          and hooks_c in out, (code, out[-900:]))
    with open(pin, "w") as fh:
        fh.write(pin_text)
    # canary-diff и окно с записью в папку демона
    logs = os.path.join(home, ".local", "state", "pantheon", "logs")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(os.path.join(logs, "hookd-fallback.log"), "a") as fh:
        fh.write(f"{now}\tcanary-diff\t0123456789abcdef\tslow=2:deny\tdaemon=0:allow\n")
    sdir = os.path.join(home, ".local", "state", "pantheon", "settings")
    os.makedirs(sdir)
    with open(os.path.join(sdir, "athena-x.json"), "w") as fh:
        json.dump({"sandbox": {"filesystem": {"allowWrite": [os.path.join(home, ".cache")]}}}, fh)
    code, out, err, _ = ins("--check")
    check("--check: canary-diff за сутки и окно с записью в ~/.cache — код 1, оба названы",
          code == 1 and "тревога: canary-diff 1" in out and "athena-x.json: allowWrite" in out
          and "canary-diff" in last_line(out) and "папка демона открыта окнам" in last_line(out), (code, out[-1200:]))
    os.remove(os.path.join(logs, "hookd-fallback.log"))
    shutil.rmtree(sdir)
    # проба без итога (задание не запустилось): срок вышел — код 1 и причина
    code, out, err, _ = ins("--check", FAKE_NORUN="1", PANTHEON_HOOKD_PROBE_WAIT="1")
    check("--check: проба без итога за срок — код 1, «итога нет за 1 с»",
          code == 1 and "итога нет за 1 с" in out and "проба доступа не прошла" in last_line(out), (code, out[-600:]))
    # старая установка: /bin/sh первым
    pl["ProgramArguments"] = ["/bin/sh", os.path.join(HOOKS, "python.sh"), os.path.join(HOOKS, "daemon.py")]
    with open(plist, "wb") as fh:
        plistlib.dump(pl, fh)
    code, out, err, _ = ins("--check")
    check("--check: служба старой установки (/bin/sh первым) — код 1, «переставить»",
          code == 1 and "старой командой" in out and "служба старой установки" in last_line(out), (code, out[-600:]))
    # служба не поставлена
    code, out, err, _ = ins("--uninstall")
    code, out, err, _ = ins("--check")
    check("--check: службы нет — код 1, «не поставлена» и команда установки",
          code == 1 and "не поставлена" in out and "служба не поставлена" in last_line(out), (code, out[-600:]))
    # проба шла не через pantheon-hookd (ответственный — другой процесс): находка
    home2 = os.path.join(root, "in2")
    os.makedirs(home2)
    code, out, err, _ = inst(home2, lctl, "--check")
    check("--check: нет pantheon-hookd — код 1, доступ не проверить", code == 1 and "нет pantheon-hookd" in out,
          (code, out[-600:]))


def main():
    root = TH.short_root()
    os.makedirs(os.path.join(root, "work"))
    try:
        test_templates()
        test_cli(root)
        test_probe(root)
        test_fd_daemon(root)
        test_flush_paths(root)
        svc = test_build_svc(root) if MAC else None
        if not MAC:
            print("пропущено: нужен macOS — pantheon-hookd (launch.h)")
        if svc:
            test_hardened(root, svc)
            test_wrapper(root, svc)
        test_install(root, svc)
    finally:
        for p in PROCS:
            try:
                TH.stop(p)
            except Exception:  # noqa: BLE001
                pass
        for dirpath, dirs, _ in os.walk(root):
            for d in dirs:
                try:
                    os.chmod(os.path.join(dirpath, d), stat.S_IRWXU)
                except OSError:
                    pass
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
