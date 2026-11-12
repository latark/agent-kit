#!/usr/bin/env python3
"""Команды pantheon, которые Зевс зовёт из окна Пританея (hq), под его песочницей (metis-1009).

Запуск: python3 -I plugins/pantheon/tests/test_hq_commands.py  (код выхода 0 — все прошли)
        HQ_AUDIT_OUT=<файл.md> — ещё и таблица аудита «команда → код → последняя строка» в этот файл.

Окно hq пишет только в ~/ai/pantheon (кроме .git и alerts.md), STATE/hq-rw/{locks,autostart-reset,start-req,saved}
и свой кэш (сборка — pantheon.py, hq_state_dirs и раздел «штаб»). Тест запускает каждую команду списка CMDS
настоящим процессом `run.py` с PANTHEON_ROLE=hq в двух видах песочницы:
  1) права файлов: STATE и его папки — только чтение (chmod), открыты те же папки hq-rw — идёт везде;
  2) seatbelt: профиль `deny file-write*` кроме папок окна hq, как у test_outside_stop — только на macOS вне
     песочницы (внутри окна sandbox-exec вложенный — «пропущено: нужен macOS»).
Проверяет: ни одна команда не печатает Traceback; код — 0..7, а при коде не 0 последняя строка вывода называет
причину; `start <направление> "текст"` кладёт поручение во входящие направления и заявку start-req (код 0) и не
пишет STATE/settings/run; `resume <направление>` — строка resume: true в той же заявке (metis-1066);
`start --restart` — отказ (код 2) со ссылкой на start_gate, до остановки копий;
`start --at-cancel` — отмена строкой в заявке, её гасит плановый проход; `agents` — список и одна строка о снимке.
`claude` в PATH — заглушка с пустым списком сессий: тест не видит и не трогает ваших сессий.
"""
import atexit
import fnmatch
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311  # noqa: E402  pantheon.py — только на Python 3.11+

if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)] + sys.argv[1:])

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="hq-commands-"))
tempfile.tempdir = _ROOT


def _cleanup():
    for d, dirs, _files in os.walk(_ROOT):  # папки только для чтения rmtree не удалит
        for n in dirs:
            try:
                os.chmod(os.path.join(d, n), 0o700)
            except OSError:
                pass
    shutil.rmtree(_ROOT, True)


atexit.register(_cleanup)

LIBDIR = os.path.join(os.path.dirname(HERE), "lib")
RUN_PY = os.path.join(LIBDIR, "run.py")
FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-900:]}]"))
    if not cond:
        FAILS.append(name)


for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE", "XDG_"))]:
    os.environ.pop(k)

DIRECTION = "win-a"
ONESHOT_ID = f"at-20991231-2359-{DIRECTION}"
HQ_RW_DIRS = ("locks", "autostart-reset", "start-req", "saved")

# Команды роли Зевса (roles/hq.tmpl, HQ_EXCLUDED в pantheon.py, строки задачи metis-1009). Второе поле — что ещё
# проверить сверх общего (нет Traceback, код 0..7, причина последней строкой).
CMDS = [
    ["start", DIRECTION, "поручение: проверь сборку"],
    ["start", DIRECTION],
    ["start", DIRECTION, "--restart"],
    ["start", DIRECTION, "--restart", "поручение"],
    ["start", DIRECTION, "--at", "23:59", "поручение"],
    ["start", "--at-list"],
    ["start", "--at-cancel", ONESHOT_ID],
    ["start", "workshop", "metis-0001"],
    ["start", "zeus"],
    ["agents"],
    ["who"],
    ["status"],
    ["jobs"],
    ["wake", DIRECTION],
    ["stop", DIRECTION],
    ["resume", DIRECTION],
    ["pause", DIRECTION],
    ["restart", "--status"],
    ["saved", "--by", "zeus"],
    ["alert", "проверка из окна hq"],
    ["archive"],
    ["night", "status"],
    ["usage"],
    ["executors"],
    ["task", "show", "metis-0001"],
    ["consent", "metis-0001"],
    ["handoff", "route", "--", "команда не найдена"],
    ["outside", "status"],
    ["reap", "--auto"],
    ["reap"],
]


def build(base):
    """Пантеон в base: HOME, STATE с domains.json, направление с inbox/, разовый запуск для --at-cancel, свежее слово
    владельца Зевсу, заглушка claude. → (env, home, state)."""
    home = os.path.join(base, "home")
    state = os.path.join(home, ".local", "state", "pantheon")
    pan = os.path.join(home, "ai", "pantheon")
    for d in (os.path.join(pan, "directions", DIRECTION, "inbox"), os.path.join(pan, "directions", DIRECTION, "tasks"),
              os.path.join(state, "settings", "run"), os.path.join(state, "locks"), os.path.join(state, "owner-log"),
              os.path.join(home, "Library", "Caches", "pantheon-sandbox", "hq", "xdg"), os.path.join(base, "tmp"),
              os.path.join(base, "bin"), os.path.join(home, "projects", "a")):
        os.makedirs(d, exist_ok=True)
    for n in HQ_RW_DIRS:
        os.makedirs(os.path.join(state, "hq-rw", n), mode=0o700, exist_ok=True)
    with open(os.path.join(pan, "directions", DIRECTION, "STATUS.md"), "w") as fh:
        fh.write("# win-a\n")
    with open(os.path.join(pan, "schedule.toml"), "w") as fh:
        fh.write('primary_host = "mac-a"\n')
    with open(os.path.join(pan, "directions.toml"), "w") as fh:
        fh.write(f'[[direction]]\nname = "{DIRECTION}"\nfolders = ["~/projects/a"]\n')
    with open(os.path.join(state, "domains.json"), "w") as fh:
        json.dump({"domains": {DIRECTION: ["~/projects/a"]}}, fh)
    with open(os.path.join(state, "settings", "win-a.json"), "w") as fh:
        json.dump({"sandbox": {"enabled": True}}, fh)
    with open(os.path.join(state, "oneshot.json"), "w") as fh:
        json.dump({"items": [{"id": ONESHOT_ID, "target": DIRECTION, "at": 4102433940.0, "expires": 4102437540.0,
                              "text": "x", "by": "zeus", "created": "2099-12-31 00:00:00", "done_at": None,
                              "result": None, "wait": None}]}, fh)
    with open(os.path.join(state, "owner-log", "zeus.md"), "w") as fh:  # свежее слово: шлюзы проходят до записи
        fh.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S')}\n\nзапусти\n")
    fake = os.path.join(base, "bin", "claude")
    with open(fake, "w") as fh:
        fh.write("#!/bin/sh\ncase \"$1\" in agents) echo '[]';; esac\nexit 0\n")
    os.chmod(fake, 0o755)
    env = {"HOME": home, "PANTHEON_STATE": state, "PANTHEON_HOME": pan, "PANTHEON_ROLE": "hq",
           "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "TMPDIR": os.path.join(base, "tmp"),
           "XDG_CACHE_HOME": os.path.join(home, "Library", "Caches", "pantheon-sandbox", "hq", "xdg"),
           "PATH": os.path.join(base, "bin") + ":/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8"}
    return env, home, state


def lock_state(state):
    """STATE и всё в нём — только чтение, кроме папок hq-rw окна: так песочница hq видна правам файлов."""
    keep = {os.path.join(state, "hq-rw", n) for n in HQ_RW_DIRS}
    for d, dirs, files in os.walk(state, topdown=False):
        for f in files:
            os.chmod(os.path.join(d, f), 0o444)
        if d not in keep:
            os.chmod(d, 0o555)


def unlock_state(state):
    for d, dirs, files in os.walk(state):
        os.chmod(d, 0o700)
        for f in files:
            os.chmod(os.path.join(d, f), 0o600)


def run(env, argv, prefix=()):
    try:
        r = subprocess.run([*prefix, PY311, "-I", RUN_PY, *argv], env=env, cwd=env["PANTHEON_HOME"],
                           capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or ""), "таймаут 90 с"
    return r.returncode, r.stdout, r.stderr


def last_line(out, err):
    lines = [x for x in (err.strip().splitlines() or out.strip().splitlines()) if x.strip()]
    return lines[-1] if lines else ""


def excluded(argv):
    """Команда в HQ_EXCLUDED окна hq — в окне она идёт мимо песочницы (excludedCommands), если вызвана одна."""
    sys.path.insert(0, LIBDIR)
    import pantheon as P  # noqa: E402
    line = "pantheon " + " ".join(argv)
    return any(fnmatch.fnmatchcase(line, pat) for pat in P.HQ_EXCLUDED + P.SANDBOX_EXCLUDED)


def suite(kind, prefix_of):
    """Все CMDS в одном виде песочницы. prefix_of(env, home, state) → префикс команды (seatbelt) или ()."""
    base = os.path.join(_ROOT, kind)
    env, home, state = build(base)
    prefix = prefix_of(env, home, state)
    if not prefix:
        lock_state(state)
    rows = []
    inbox = os.path.join(env["PANTHEON_HOME"], "directions", DIRECTION, "inbox")
    req = os.path.join(state, "hq-rw", "start-req", DIRECTION + ".req")
    runs = os.path.join(state, "settings", "run")
    for argv in CMDS:
        rc, out, err = run(env, argv, prefix)
        line = last_line(out, err)
        rows.append((argv, rc, line))
        name = f"{kind}: pantheon {' '.join(argv)}"
        check(f"{name} — без Traceback, код 0..7", rc is not None and 0 <= rc <= 7 and "Traceback" not in out + err,
              (rc, out[-400:], err[-600:]))
        if rc not in (None, 0):
            check(f"{name} — код {rc}: причина последней строкой", len(line) > 15, (rc, out[-300:], err[-300:]))
        if argv == CMDS[0]:
            got = sorted(os.listdir(inbox))
            body = open(os.path.join(inbox, got[0]), encoding="utf-8").read() if got else ""
            lines = open(req).read().splitlines() if os.path.exists(req) else []
            check(f"{name} — код 0, поручение во входящих, заявка start-req {{target, time, by}}",
                  rc == 0 and len(got) == 1 and "проверь сборку" in body and "От: Пританей" in body
                  and len(lines) == 1 and set(json.loads(lines[0])) == {"target", "time", "by"}, (rc, got, lines, err))
            check(f"{name} — STATE/settings/run не тронут", os.listdir(runs) == [], os.listdir(runs))
            sys.path.insert(0, LIBDIR)
            import awake as A  # noqa: E402
            check(f"{name} — файл не «поручение Зевса» для подъёма по входящим (заявка поднимет сама)",
                  got and not A.zeus_order(os.path.join(inbox, got[0]), got[0]), got)
        if argv[:3] == ["start", DIRECTION, "--restart"]:
            check(f"{name} — отказ код 2 со ссылкой на start_gate", rc == 2 and "start_gate" in line, (rc, line))
        if argv[:3] == ["start", DIRECTION, "--at"]:
            check(f"{name} — код 1, строка: oneshot.json закрыт, поднять сейчас — start с поручением",
                  rc == 1 and "oneshot.json" in line and f"pantheon start {DIRECTION}" in line, (rc, line))
        if argv[:2] == ["start", "--at-cancel"]:
            data = [json.loads(x) for x in open(req).read().splitlines()] if os.path.exists(req) else []
            check(f"{name} — код 0, строка cancel в заявке", rc == 0 and any(x.get("cancel") == ONESHOT_ID for x in data),
                  (rc, line, data))
        if argv == ["resume", DIRECTION]:  # metis-1066: STATE/stopped окну закрыт — заявка, её исполняет проход
            data = [json.loads(x) for x in open(req).read().splitlines()] if os.path.exists(req) else []
            check(f"{name} — код 0, строка resume: true в заявке", rc == 0 and any(x.get("resume") is True for x in data),
                  (rc, line, data))
        if argv == ["agents"]:
            check(f"{name} — код 0 и одна строка о снимке", rc == 0 and "снимок" in line, (rc, line))
        if argv == ["reap", "--auto"] and rc == 3:
            check(f"{name} — код 3: «задача планового прохода»", "планового прохода" in line, line)
    if not prefix:
        unlock_state(state)
    # плановый проход вне окна: отмена гасит разовый запуск, заявка поднимает окно (разовый запуск zeus-request)
    for k in [k for k in os.environ if k.startswith("PANTHEON_")]:
        os.environ.pop(k)
    os.environ.update({k: v for k, v in env.items() if k != "PANTHEON_ROLE"})
    sys.path.insert(0, LIBDIR)
    import importlib
    import pantheon as P  # noqa: E402
    importlib.reload(P)
    got = P.take_start_requests(json.load(open(os.path.join(state, "domains.json")))["domains"], time.time())
    items = {x["id"]: x for x in P.night_mod().oneshot_items()}
    check(f"{kind}: проход — отмена из заявки погасила {ONESHOT_ID}",
          (items.get(ONESHOT_ID) or {}).get("done_at") and "отменён" in str(items[ONESHOT_ID].get("result")), (got, items))
    check(f"{kind}: проход — заявка подняла окно разовым запуском zeus-request",
          any(x.get("by") == "zeus-request" and x.get("target") == DIRECTION for x in items.values()), (got, items))
    return rows


def _seatbelt():
    sb = "/usr/bin/sandbox-exec"
    if sys.platform != "darwin" or not os.path.exists(sb):
        return None
    r = subprocess.run([sb, "-p", "(version 1)(allow default)", "/usr/bin/true"], capture_output=True, text=True,
                       timeout=30)
    return sb if r.returncode == 0 else None


def seatbelt_prefix(sb):
    def make(env, home, state):
        pan = env["PANTHEON_HOME"]
        allow = [pan, os.path.join(home, "Library", "Caches", "pantheon-sandbox", "hq"), env["TMPDIR"], "/dev"]
        allow += [os.path.join(state, "hq-rw", n) for n in HQ_RW_DIRS]
        deny = [os.path.join(pan, ".git"), os.path.join(pan, "alerts.md")]
        q = lambda p: json.dumps(os.path.realpath(p))  # noqa: E731
        profile = ("(version 1)(allow default)(deny file-write* (require-not (require-any "
                   + " ".join(f"(subpath {q(p)})" for p in allow) + ")))"
                   + "".join(f"(deny file-write* (subpath {q(p)}))" for p in deny))
        return (sb, "-p", profile)
    return make


# у root права файлов не закрывают запись — тогда вид 1 ничего не проверяет
if os.geteuid() == 0:
    print("пропущено: права файлов не держат root — вид «chmod»")
    rows = []
else:
    rows = suite("chmod", lambda env, home, state: ())
SB = _seatbelt()
if SB is None:
    print("пропущено: нужен macOS — sandbox-exec недоступен или проба идёт внутри песочницы")
    sb_rows = []
else:
    sb_rows = suite("seatbelt", seatbelt_prefix(SB))

out_md = os.environ.get("HQ_AUDIT_OUT")
if out_md:
    sb_by = {tuple(a): (rc, ln) for a, rc, ln in sb_rows}
    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write("| команда | мимо песочницы (excludedCommands) | код (chmod) | последняя строка (chmod) | код (seatbelt) |\n"
                 "|---|---|---|---|---|\n")
        for argv, rc, ln in rows:
            s = sb_by.get(tuple(argv), ("—", ""))[0]
            cell = ln.replace("|", "\\|")[:220]
            fh.write(f"| `pantheon {' '.join(argv)}` | {'да' if excluded(argv) else 'нет'} | {rc} | {cell} | {s} |\n")

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]}" + (f"  FAIL: {len(FAILS)}" if FAILS else ""))
sys.exit(1 if FAILS else 0)
