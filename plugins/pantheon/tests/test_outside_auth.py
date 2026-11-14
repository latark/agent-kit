#!/usr/bin/env python3
"""`pantheon outside auth` — ссылка входа MCP из окна роли открывается в браузере владельца (lib/outside_auth.py,
metis-1127).

Запуск: python3 -I plugins/pantheon/tests/test_outside_auth.py  (код выхода 0 — все прошли)
Проверяет на заглушке open (OPEN — скрипт sh, пишет свои аргументы в файл) и заглушке живых окон: заявка из окна
роли с адресом Supabase OAuth → проход серверов (serve_round) открывает его одним аргументом open, уведомление «окно X
просит вход в Supabase», итог done без адреса в runs/ и журнале; адрес не из белого списка (чужой хост, http, порт,
имя пользователя, «..», «%», пробел, не тот путь) — команда отказывает кодом 2 без заявки, а подложенную заявку проход
не открывает; заявка от закрытого окна гаснет (stopped), список окон не прочитан — failed, open не зовётся; старая
заявка, сбой open, чужой формат, лимит открытий на окно — failed; очередь STATE (ваши сессии) открывается без проверки
окна; pending и pending_serve видят заявку; live_windows — по culprits (ps и claude agents, сбой — None).
"""
import atexit
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311  # noqa: E402  pantheon.py — только на Python 3.11+

if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)] + sys.argv[1:])

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="outside-auth-"))
tempfile.tempdir = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIBDIR = os.path.join(os.path.dirname(HERE), "lib")
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE", "XDG_"))]:
    os.environ.pop(k)
NOTIFY_LOG = os.path.join(_ROOT, "notify.log")
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "TMPDIR": _ROOT, "PANTHEON_NOTIFY_LOG": NOTIFY_LOG})
sys.path.insert(0, LIBDIR)
import pantheon as P  # noqa: E402
O = P.outside_mod()
A = O.sub_mod("auth")

FAILS, TOTAL = [], [0]
QDIR = os.path.join(_ROOT, "cache", "outside")
OTHER = os.path.join(_ROOT, "cache2", "outside")
OWNQ = os.path.join(STATE, "outside", "queue")
for d in (QDIR, OTHER, OWNQ):
    os.makedirs(d)
URL = ("https://api.supabase.com/v1/oauth/authorize?response_type=code&client_id=cid-1&code_challenge=Chal-9x"
       "&code_challenge_method=S256&redirect_uri=http%3A%2F%2Flocalhost%3A51234%2Fcallback&state=St4te-q7Zp")
RU = "redirect_uri=http%3A%2F%2Flocalhost%3A51234%2Fcallback"


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-800:]}]"))
    if not cond:
        FAILS.append(name)


O.queue_dirs = lambda: [(OWNQ, None), (QDIR, "w"), (OTHER, "w2")]
O.own_qdir = lambda: QDIR
O.servers = lambda: {}
for name in ("sweep", "drop_orphan_stops", "drop_orphan_work"):
    setattr(O, name, lambda *a, **k: None)
O.requests = lambda *a, **k: []
LIVE = [{"w", "w2"}]
REAL_LIVE_WINDOWS = A.live_windows
A.live_windows = lambda: LIVE[0]

OPEN_LOG = os.path.join(_ROOT, "open.log")
OPEN_RC = os.path.join(_ROOT, "open.rc")
FAKE_OPEN = os.path.join(_ROOT, "fake-open")
with open(FAKE_OPEN, "w") as fh:
    fh.write(f"#!/bin/sh\nprintf 'argc=%s\\n' \"$#\" >> '{OPEN_LOG}'\nfor a in \"$@\"; do printf 'arg=%s\\n' \"$a\" "
             f">> '{OPEN_LOG}'; done\nexit \"$(cat '{OPEN_RC}' 2>/dev/null || echo 0)\"\n")
os.chmod(FAKE_OPEN, 0o755)
A.OPEN = FAKE_OPEN


def read(p):
    try:
        with open(p, errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def reset():
    for p in (OPEN_LOG, OPEN_RC, NOTIFY_LOG, A.rate_path()):
        with contextlib.suppress(OSError):
            os.unlink(p)
    LIVE[0] = {"w", "w2"}


def run(url=URL, extra=(), rounds=True):
    """main(["auth", …]) без ожидания, затем круг прохода серверов → (код, вывод, rid, итог)."""
    out = io.StringIO()
    before = set(os.listdir(QDIR))
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = O.main(["auth", url, *extra, "--wait", "0"])
        rid = next((n[:-len(A.SUFFIX)] for n in sorted(set(os.listdir(QDIR)) - before) if n.endswith(A.SUFFIX)),
                   None)
        if rounds and rid:
            O.serve_round()
            code = O.wait_result(QDIR, rid, 5)
    return code, out.getvalue(), rid, (O.load_result(QDIR, rid) if rid else None)


def put(qdir, req=None, rid=None, age=0, url=URL):
    """Заявка прямо в папку заявок (мимо проверки команды) → rid."""
    rid = rid or time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    req = req if req is not None else {
        "v": 1, "id": rid, "kind": "auth", "url": url,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - age))}
    with open(os.path.join(qdir, rid + A.SUFFIX), "w") as fh:
        json.dump(req, fh)
    return rid


def round_result(qdir, rid):
    with contextlib.redirect_stdout(io.StringIO()):
        O.serve_round()
    return O.load_result(qdir, rid) or {}


# 1. заявка из живого окна — страница Supabase открыта в браузере владельца
reset()
code, out, rid, res = run()
log = read(OPEN_LOG)
check("окно: код 0, итог done", code == 0 and (res or {}).get("state") == "done", (code, out, res))
check("окно: open позван одним аргументом — адрес как есть", log == f"argc=1\narg={URL}\n", log)
check("окно: уведомление «окно w просит вход в Supabase» с client_id и хостом redirect_uri",
      "Окно w просит вход в Supabase (клиент cid-1, ответ на localhost)" in read(NOTIFY_LOG), read(NOTIFY_LOG))
check("окно: вывод команды называет client_id и хост redirect_uri", "клиент cid-1, ответ на localhost" in out, out)
check("окно: заявка снята с диска", not os.path.exists(os.path.join(QDIR, rid + A.SUFFIX)))
public = read(os.path.join(STATE, "outside", "runs", rid + ".json")) + read(os.path.join(STATE, "logs", "outside.jsonl"))
check("окно: в runs/ и журнале — хост, без state и code_challenge адреса",
      "api.supabase.com" in public and "St4te-q7Zp" not in public and "Chal-9x" not in public, public)
check("окно: вывод команды — без адреса", "St4te-q7Zp" not in out, out)

# 2. адрес не из белого списка
BAD = {
    "http": URL.replace("https://", "http://"),
    "чужой хост": URL.replace("api.supabase.com", "evil.example.com"),
    "хост-приставка": URL.replace("api.supabase.com", "api.supabase.com.evil.example.com"),
    "имя пользователя": URL.replace("https://", "https://api.supabase.com@"),
    "чужой порт": URL.replace("api.supabase.com", "api.supabase.com:8443"),
    "не тот путь": URL.replace("/v1/oauth/authorize", "/v1/projects"),
    "путь-приставка": URL.replace("/v1/oauth/authorize", "/v1/oauth/authorizeX"),
    "«..» в пути": URL.replace("/v1/oauth/authorize", "/v1/oauth/authorize/../../projects"),
    "«.» в пути": URL.replace("/v1/oauth/authorize", "/v1/oauth/authorize/./x"),
    "«%» в пути": URL.replace("/v1/oauth/authorize", "/v1/oauth/%61uthorize"),
    "пробел": URL + " -a Calculator",
    "обратная черта": URL + "&next=\\\\evil.example.com",
    "не ASCII": URL.replace("api.supabase.com", "api.supab\u0430se.com"),
    "file:": "file:///Applications/Calculator.app",
    "ключ open": "-a Calculator",
    "пусто": "",
    "длинный": URL + "&x=" + "a" * A.URL_MAX,
    # запрос ссылки и redirect_uri (находка проверки безопасности: код доступа не должен уйти на чужой адрес)
    "фрагмент": URL + "#x",
    "пустой фрагмент": URL + "#",
    "запрос не по строгому разбору": URL + "&junk",
    "два redirect_uri": URL + "&redirect_uri=http%3A%2F%2Fevil.example.com%2Fcallback",
    "повтор state": URL + "&state=other",
    "без redirect_uri": URL.replace("&" + RU, ""),
    "redirect_uri на чужой хост": URL.replace(RU, RU.replace("localhost", "evil.example.com")),
    "redirect_uri https://evil": URL.replace(RU, "redirect_uri=https%3A%2F%2Fevil.example.com%2Fcallback"),
    "redirect_uri https на localhost": URL.replace(RU, RU.replace("http%3A", "https%3A")),
    "redirect_uri localhost-приставка": URL.replace(RU, RU.replace("localhost", "localhost.evil.example.com")),
    "redirect_uri с именем пользователя": URL.replace(RU, RU.replace("localhost", "x%40localhost")),
    "redirect_uri без порта": URL.replace(RU, RU.replace("%3A51234", "")),
    "redirect_uri порт не числом": URL.replace(RU, RU.replace("51234", "abc")),
    "redirect_uri не тот путь": URL.replace(RU, RU.replace("callback", "other")),
    "redirect_uri с фрагментом": URL.replace(RU, RU + "%23x"),
    "redirect_uri с запросом": URL.replace(RU, RU + "%3Fx%3D1"),
    "client_id с мусором": URL.replace("client_id=cid-1", "client_id=cid%3Cscript%3E"),
    "client_id пустой": URL.replace("client_id=cid-1", "client_id="),
    "без client_id": URL.replace("&client_id=cid-1", ""),
    "response_type не code": URL.replace("response_type=code", "response_type=token"),
    "без response_type": URL.replace("response_type=code&", ""),
}
for what, bad in BAD.items():
    check(f"белый список: {what} — отказ check_url", bad != URL and A.check_url(bad)[0] is None, A.check_url(bad))
check("белый список: адрес Supabase OAuth — принят",
      A.check_url(URL) == ({"host": "api.supabase.com", "client": "cid-1", "redirect": "localhost"}, None),
      A.check_url(URL))
check("белый список: порт 443, подпуть и ответ на 127.0.0.1 — приняты",
      all((A.check_url(u)[0] or {}).get("host") == "api.supabase.com" for u in (
          URL.replace("api.supabase.com", "api.supabase.com:443"), URL.replace("/authorize", "/authorize/x"),
          URL.replace(RU, RU.replace("localhost", "127.0.0.1")))))
LONG = "c" * 60
check("client_id длиннее 40 — показан первыми 40 знаками",
      (A.check_url(URL.replace("client_id=cid-1", "client_id=" + LONG))[0] or {}).get("client") == LONG[:40])
reset()
code, out, rid, res = run(BAD["redirect_uri на чужой хост"], rounds=False)
check("redirect_uri на чужой хост: команда — код 2, заявки нет", code == 2 and rid is None
      and "redirect_uri" in out.strip().splitlines()[-1], (code, out, rid))
reset()
rid = put(QDIR, url=BAD["два redirect_uri"])
res = round_result(QDIR, rid)
check("два redirect_uri: подложенная заявка — failed, open не позван",
      res.get("state") == "failed" and not read(OPEN_LOG), (res, read(OPEN_LOG)))
reset()
code, out, rid, res = run(BAD["чужой хост"], rounds=False)
check("белый список: команда — код 2, заявки нет, причина последней строкой",
      code == 2 and rid is None and "не в белом списке" in out.strip().splitlines()[-1], (code, out, rid))
for what in ("чужой хост", "http", "«..» в пути"):
    reset()
    rid = put(QDIR, url=BAD[what])
    res = round_result(QDIR, rid)
    check(f"белый список: подложенная заявка ({what}) — failed, open не позван",
          res.get("state") == "failed" and not read(OPEN_LOG), (res, read(OPEN_LOG)))

# 3. заявка от закрытого окна гаснет
reset()
LIVE[0] = {"w2"}
code, out, rid, res = run()
check("закрытое окно: итог stopped, код 1, open не позван",
      (res or {}).get("state") == "stopped" and code == 1 and not read(OPEN_LOG), (code, out, res, read(OPEN_LOG)))
check("закрытое окно: причина — окно закрыто", "окно w закрыто" in out.strip().splitlines()[-1], out)
check("закрытое окно: уведомления нет", not read(NOTIFY_LOG), read(NOTIFY_LOG))
reset()
LIVE[0] = None
code, out, rid, res = run()
check("окна не прочитаны: failed, open не позван",
      (res or {}).get("state") == "failed" and not read(OPEN_LOG) and "не прочитан" in out, (out, res))
reset()


def broken_live():
    raise RuntimeError("ps сломан")


A.live_windows = broken_live
code, out, rid, res = run()
A.live_windows = lambda: LIVE[0]
check("сбой чтения окон: проход не упал, заявка failed, open не позван",
      (res or {}).get("state") == "failed" and not read(OPEN_LOG), (out, res))
reset()
LIVE[0] = None
rid = put(OWNQ)
res = round_result(OWNQ, rid)
check("очередь STATE (ваша сессия): открыта без проверки окна", res.get("state") == "done"
      and read(OPEN_LOG) == f"argc=1\narg={URL}\n", (res, read(OPEN_LOG)))

# 4. прочие отказы
reset()
rid = put(QDIR, age=A.AUTH_TTL + 60)
res = round_result(QDIR, rid)
check("старая заявка: failed, open не позван", res.get("state") == "failed" and "устарела" in res.get("why", "")
      and not read(OPEN_LOG), res)
reset()
with open(OPEN_RC, "w") as fh:
    fh.write("1")
code, out, rid, res = run()
check("сбой open: failed, код 1, уведомления нет", (res or {}).get("state") == "failed" and code == 1
      and "open вернул код 1" in out and not read(NOTIFY_LOG), (out, res))
reset()
rid = put(QDIR, req={"v": 1, "id": "20261114-000000-abcdef", "kind": "auth", "url": URL, "time": "x"})
res = round_result(QDIR, rid)
check("чужой формат (id ≠ имя файла): failed, open не позван", res.get("state") == "failed" and not read(OPEN_LOG), res)
reset()
codes = [run()[0] for _ in range(A.RATE_MAX + 1)]
check("лимит: RATE_MAX открытий подряд — 0, следующее — отказ",
      codes == [0] * A.RATE_MAX + [1] and read(OPEN_LOG).count("argc=") == A.RATE_MAX, (codes, read(OPEN_LOG)))
reset()
for args in ([], [URL, "--wait", "x"], [URL, "--bad", "1"]):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = O.main(["auth", *args])
    check(f"неверный вызов {args[1:2]}: код 2", code == 2, out.getvalue())

# 5. тик видит заявку
reset()
rid = put(QDIR)
check("pending и pending_serve: заявка входа есть", A.pending() and O.pending_serve())
round_result(QDIR, rid)
check("pending: после круга заявок нет", not A.pending())

# 6. live_windows по culprits
C = P.culprits_mod()
saved = (C.ps_all, C.agents_strict, C.context)
C.ps_all, C.agents_strict = (lambda: None), (lambda: [])
check("live_windows: ps не прочитан — None", REAL_LIVE_WINDOWS() is None)
C.ps_all, C.agents_strict = (lambda: []), (lambda: None)
check("live_windows: claude agents не прочитан — None", REAL_LIVE_WINDOWS() is None)
C.ps_all = lambda: [{"pid": 5, "ppid": 1, "args": "sleep 1"}]
C.agents_strict = lambda: [{"pid": 5, "name": "w"}]
C.context = lambda agents: {"sessions": {int(a["pid"]): a["name"] for a in agents}}
got = REAL_LIVE_WINDOWS()
check("live_windows: живая сессия w — окно w", isinstance(got, set) and "w" in got and "w2" not in got, got)
C.ps_all, C.agents_strict, C.context = saved

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
