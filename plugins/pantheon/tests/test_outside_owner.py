"""Профиль outside закрывает каналы «от владельца» (metis-1026, модель угроз К1, К4, К6, К7, К10).

Код роли идёт под профилем плана (`pantheon outside test/serve`, sandbox-exec). Ему закрыты: чтение ключей демона
Claude Code (~/.claude/daemon: control.key и roster.json дают ввод в PTY любой сессии — строку в owner-log), входа
(~/.claude/.credentials*), IDE (~/.claude/ide) и terminal-notifier (по щелчку выполняет команду от имени владельца);
запись в доску VIEW (галочка — «ход владельца») и в папку hookd (подмена сокета guard); Apple Events (osascript).

Проверка двумя слоями. Разбор профиля (везде): правила SBPL вычисляются для путей, позднее правило сильнее — так же,
как в sandbox-exec. Живой прогон (macOS, не во вложенной песочнице): тот же профиль под sandbox-exec на поддельном HOME —
чтение, запись, запуск и mach-lookup дают отказ. В окне роли и под `pantheon outside test` песочница вложенная
(sandbox_apply — код 71): живая часть печатает «пропущено». Запуск: python3.14 -I tests/test_outside_owner.py.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="outside-owner-"))
HOME = os.path.join(ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1"})
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import pantheon as P  # noqa: E402

O = P.outside_mod()
FAILS, TOTAL = [], [0]
MAC = sys.platform == "darwin"


def check(name, cond, extra=""):
    TOTAL[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name} {extra}")


# --- разбор SBPL: формы верхнего уровня, правила файлов, «позднее сильнее» -------------------------------------------

def forms(text):
    """Формы верхнего уровня профиля: строки и #"регулярки" со скобками внутри не ломают счёт."""
    out, depth, start, i = [], 0, None, 0
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            if depth == 0:
                start = i
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                out.append(text[start:i + 1])
        i += 1
    return out


TOKEN = re.compile(r'\((subpath|literal|regex|global-name) (#?)"((?:[^"\\]|\\.)*)"\)')


def rules(text):
    """[(действие, [операции], [(вид, значение)])] — по порядку профиля."""
    out = []
    for f in forms(text):
        head = f[1:-1].split("(", 1)[0].split()
        if not head or head[0] not in ("allow", "deny"):
            continue
        filt = [(kind, val if rx else val.replace('\\"', '"').replace("\\\\", "\\"))
                for kind, rx, val in TOKEN.findall(f)]
        out.append((head[0], head[1:], filt))
    return out


def hit(kind, val, path):
    if kind == "subpath":
        return path == val or path.startswith(val.rstrip("/") + "/")
    if kind == "literal":
        return path == val
    if kind == "regex":
        return re.search(val, path) is not None
    return False


def decide(text, op, path):
    """Решение профиля для операции op (file-read-data, file-write-create) над path: последнее подходящее правило."""
    verdict = "allow"
    for act, ops, filt in rules(text):
        if not any(op.startswith(o.rstrip("*")) for o in ops if o.startswith("file")):
            continue
        if not filt or any(hit(k, v, path) for k, v in filt):
            verdict = act
    return verdict


def has_rule(text, act, op, name=None):
    return any(a == act and op in ops and (name is None or ("global-name", name) in filt)
               for a, ops, filt in rules(text))


H = os.path.realpath(HOME)
CL = os.path.join(H, ".claude")
NOTIFIER_BIN = [os.path.join(x, "bin", "terminal-notifier") for x in P.NOTIFIER_PATHS]
READ_DENY = [os.path.join(CL, "daemon", "control.key"), os.path.join(CL, "daemon", "roster.json"),
             os.path.join(CL, "daemon"), os.path.join(CL, ".credentials.json"), os.path.join(CL, ".credentials"),
             os.path.join(CL, "ide", "51234.lock"), *NOTIFIER_BIN,
             os.path.join(H, ".config", "cdp-daemon", "token")]           # К8 — держать
WRITE_DENY = [os.path.join(os.path.realpath(P.VIEW), "metis-1026.md"), os.path.join(os.path.realpath(P.VIEW), "board.jsonl"),
              os.path.join(os.path.realpath(P.HOOKD_DIR), "hookd.sock"), os.path.realpath(P.HOOKD_DIR),
              os.path.join(os.path.realpath(STATE), "owner-log", "zeus.md")]   # К5 — держать
READ_OPEN = [os.path.join(CL, "settings.json"), os.path.join(CL, "daemon.json"), os.path.join(CL, "daemonx", "a"),
             os.path.join(CL, "projects", "x.jsonl"), os.path.join(H, "ai", "pantheon-view", "x.md")]
WRITE_OPEN = [os.path.join(H, "ai", "pantheon-viewer", "x"), os.path.join(H, ".cache", "pantheon", "other", "x"),
              os.path.join(ROOT, "work", "x")]

print("профиль outside: каналы «от владельца» закрыты (metis-1026)")
for label, db in (("profile.sb", ()), ("profile-db.sb", (5432,))):
    text = O.profile_text((), db)
    for p in READ_DENY:
        check(f"{label}: чтение {os.path.relpath(p, ROOT) if p.startswith(ROOT) else p} — отказ",
              decide(text, "file-read-data", p) == "deny")
    for p in WRITE_DENY:
        check(f"{label}: запись {os.path.relpath(p, ROOT)} — отказ", decide(text, "file-write-create", p) == "deny")
    for p in READ_OPEN:
        check(f"{label}: чтение {os.path.relpath(p, ROOT)} открыто (правила не шире нужного)",
              decide(text, "file-read-data", p) == "allow")
    for p in WRITE_OPEN:
        check(f"{label}: запись {os.path.relpath(p, ROOT)} открыта", decide(text, "file-write-create", p) == "allow")
    check(f"{label}: Apple Events закрыты (appleevent-send)", has_rule(text, "deny", "appleevent-send"))
    check(f"{label}: служба Apple Events закрыта (mach-lookup)",
          has_rule(text, "deny", "mach-lookup", "com.apple.coreservices.appleevents"))

# переопределённая доска (PANTHEON_VIEW) — профиль берёт её, а не путь по умолчанию
_view = P.VIEW
P.VIEW = os.path.join(ROOT, "elsewhere-view")
check("PANTHEON_VIEW: запись в переопределённую доску — отказ",
      decide(O.profile_text(), "file-write-create", os.path.join(ROOT, "elsewhere-view", "a.md")) == "deny")
P.VIEW = _view

# --- живой прогон под sandbox-exec (65 — профиль не разобран; 71 — вложенная песочница, пропуск) ---------------------
SX = "/usr/bin/sandbox-exec"
PROBE = r"""
import ctypes, os, subprocess, sys
out = {}
def try_(name, fn):
    try:
        fn(); out[name] = "ok"
    except PermissionError:
        out[name] = "deny"
    except OSError as e:
        out[name] = "err:" + type(e).__name__
a = sys.argv[1:]
try_("read-key", lambda: open(a[0]).read())
try_("read-cred", lambda: open(a[1]).read())
try_("write-view", lambda: open(os.path.join(a[2], "x.md"), "w").write("x"))
try_("write-hookd", lambda: open(os.path.join(a[3], "hookd.sock"), "w").write("x"))
try_("read-open", lambda: open(a[4]).read())
try:
    out["notifier"] = "rc%d" % subprocess.run([a[5]], capture_output=True).returncode
except PermissionError:
    out["notifier"] = "deny"
lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
port = ctypes.c_uint(0)
bp = ctypes.c_uint.in_dll(lib, "bootstrap_port")
out["ae"] = "rc%d" % lib.bootstrap_look_up(bp, b"com.apple.coreservices.appleevents", ctypes.byref(port))
print(" ".join(f"{k}={v}" for k, v in out.items()))
"""


def live():
    d = os.path.join(CL, "daemon")
    os.makedirs(d, mode=0o700)
    os.makedirs(os.path.join(CL, "ide"))
    for f in (os.path.join(d, "control.key"), os.path.join(CL, ".credentials.json"), os.path.join(CL, "settings.json")):
        with open(f, "w") as fh:
            fh.write("fake\n")
    os.makedirs(P.VIEW, exist_ok=True)
    os.makedirs(P.HOOKD_DIR, exist_ok=True)
    fake_notifier = os.path.join(ROOT, "notifier")
    os.makedirs(os.path.join(fake_notifier, "bin"))
    exe = os.path.join(fake_notifier, "bin", "terminal-notifier")
    with open(exe, "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(exe, 0o755)
    keep = P.NOTIFIER_PATHS
    P.NOTIFIER_PATHS = [*keep, fake_notifier]
    prof = os.path.join(ROOT, "profile.sb")
    with open(prof, "w") as fh:
        fh.write(O.profile_text())
    P.NOTIFIER_PATHS = keep
    probe = os.path.join(ROOT, "probe.py")
    with open(probe, "w") as fh:
        fh.write(PROBE)
    args = [os.path.join(d, "control.key"), os.path.join(CL, ".credentials.json"), P.VIEW, P.HOOKD_DIR,
            os.path.join(CL, "settings.json"), exe]
    bare = subprocess.run([sys.executable, "-I", probe, *args], capture_output=True, text=True, timeout=60)
    r = subprocess.run([SX, "-f", prof, sys.executable, "-I", probe, *args], capture_output=True, text=True, timeout=60)
    if r.returncode == 71 and "sandbox_apply" in r.stderr:
        print("пропущено: вложенная песочница (sandbox_apply) — живая проверка профиля идёт вне окон")
        return
    check("живой: без профиля проба читает, пишет и запускает (контроль)",
          bare.stdout.split() == ["read-key=ok", "read-cred=ok", "write-view=ok", "write-hookd=ok", "read-open=ok",
                                  "notifier=rc0", "ae=rc0"], (bare.stdout, bare.stderr[-300:]))
    got = dict(x.split("=", 1) for x in r.stdout.split())
    check("живой: control.key под профилем — отказ (К1)", got.get("read-key") == "deny", (r.stdout, r.stderr[-300:]))
    check("живой: .credentials под профилем — отказ", got.get("read-cred") == "deny", r.stdout)
    check("живой: запись в доску VIEW — отказ (К4)", got.get("write-view") == "deny", r.stdout)
    check("живой: запись в папку hookd — отказ (К10)", got.get("write-hookd") == "deny", r.stdout)
    check("живой: обычный файл ~/.claude читается (контроль)", got.get("read-open") == "ok", r.stdout)
    check("живой: terminal-notifier не запускается (К6)", got.get("notifier") in ("deny", "rc126"), r.stdout)
    check("живой: служба Apple Events не находится (К7)", got.get("ae", "rc0") != "rc0", r.stdout)


if MAC and os.path.exists(SX):
    live()
else:
    print("пропущено: нужен macOS — живая проверка профиля sandbox-exec")

shutil.rmtree(ROOT, True)
print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
if FAILS:
    print("FAIL: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
