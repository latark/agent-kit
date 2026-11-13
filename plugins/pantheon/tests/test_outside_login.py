#!/usr/bin/env python3
"""`pantheon outside login` — вход тестовой учётной записью без показа пароля роли (lib/outside_login.py, metis-1134).

Запуск: python3 -I plugins/pantheon/tests/test_outside_login.py  (код выхода 0 — все прошли)
Проверяет на заглушке Supabase (post_json подменён, сети нет): вход → итог done, файл сессии 600 с cookie
@supabase/ssr (один и куски по 3180), пароль ушёл только в тело запроса; отказ Supabase (пароль в ответе) → failed с
кодом ошибки без значений; нет файла ключей, нет TALOS_PASSWORD, http к чужому хосту, сбой сети, чужой и
несуществующий сервер — failed без запроса или без значений. Значения пароля нет в stdout, stderr, журнале прохода
(logs/outside.jsonl), runs/<ID>.json, итоге и файле заявки. Заявку входа берёт проход серверов (serve_round), команду —
main(["login", …]); старые файлы сессий убираются.
"""
import atexit
import base64
import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311  # noqa: E402  pantheon.py — только на Python 3.11+

if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)] + sys.argv[1:])

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="outside-login-"))
tempfile.tempdir = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIBDIR = os.path.join(os.path.dirname(HERE), "lib")
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE", "XDG_"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "TMPDIR": _ROOT})
sys.path.insert(0, LIBDIR)
import pantheon as P  # noqa: E402
O = P.outside_mod()
L = O.login_mod()

FAILS, TOTAL = [], [0]
PASSWORD = "Pw-s3cret-Ko7xQ"
EMAIL = "talos-probe@example.test"
ANON = "anon-public-key-123"
QDIR = os.path.join(_ROOT, "cache", "outside")
OTHER = os.path.join(_ROOT, "cache2", "outside")
SID, FOREIGN = "20261113-220000-aaaaaa", "20261113-220000-bbbbbb"
ENV = os.path.join(STATE, "outside", "env")


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-800:]}]"))
    if not cond:
        FAILS.append(name)


os.makedirs(QDIR)
os.makedirs(OTHER)
SERVERS = {SID: {"pid": 1, "port": 4301, "qdir": QDIR, "window": "w", "common": "/x/.git", "app": "web"},
           FOREIGN: {"pid": 1, "port": 4302, "qdir": OTHER, "window": "w2", "common": "/x/.git"}}
O.servers = lambda: dict(SERVERS)
O.queue_dirs = lambda: [(QDIR, "w"), (OTHER, "w2")]
O.own_qdir = lambda: QDIR
O.origin_id = lambda common: "own/repo"
for name in ("sweep", "drop_orphan_stops", "drop_orphan_work"):
    setattr(O, name, lambda *a, **k: None)
O.requests = lambda *a, **k: []
CALLS = []
REPLY = [None]


def fake_post(url, body, headers, timeout=None):
    CALLS.append((url, body, headers))
    r = REPLY[0]
    if isinstance(r, Exception):
        raise r
    return r


L.post_json = fake_post


def write_env(text, name="own__repo.env"):
    os.makedirs(ENV, exist_ok=True)
    with open(os.path.join(ENV, name), "w") as fh:
        fh.write(text)


def clear_env():
    shutil.rmtree(ENV, ignore_errors=True)


GOOD_ENV = (f"NEXT_PUBLIC_SUPABASE_URL=https://abcdref.supabase.co\nNEXT_PUBLIC_SUPABASE_ANON_KEY={ANON}\n"
            f"TALOS_EMAIL={EMAIL}\nTALOS_PASSWORD='{PASSWORD}'\n")


def session(user_pad=0):
    return {"access_token": "at-" + "x" * 40, "refresh_token": "rt-1", "token_type": "bearer", "expires_in": 3600,
            "user": {"id": "u1", "email": EMAIL, "pad": "p" * user_pad}}


def run(args, rounds=True):
    """cmd_login без ожидания, затем круг прохода серверов и wait_result → (код, stdout+stderr, rid, итог)."""
    out, errb = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errb):
        code = O.main(["login", *args, "--wait", "0"])
        rid = next((n[:-len(L.SUFFIX)] for n in sorted(os.listdir(QDIR)) if n.endswith(L.SUFFIX)), None)
        reqtext = open(os.path.join(QDIR, rid + L.SUFFIX)).read() if rid else ""
        if rounds and rid:
            O.serve_round()
            code = O.wait_result(QDIR, rid, 5)
    res = O.load_result(QDIR, rid) if rid else None
    return code, out.getvalue() + errb.getvalue() + reqtext, rid, res


def everything_text():
    """Весь текст STATE (журнал, runs, env кроме самого файла ключей) и папок заявок, кроме файлов сессий."""
    parts = []
    for top in (STATE, QDIR, OTHER):
        for d, _, files in os.walk(top):
            if d.startswith(ENV):
                continue
            for f in files:
                if f.endswith(L.SESSION_SUFFIX):
                    continue
                with open(os.path.join(d, f), errors="replace") as fh:
                    parts.append(fh.read())
    return "\n".join(parts)


def decode_cookies(cookies):
    v = "".join(c["value"] for c in sorted(cookies, key=lambda c: c["name"]))
    assert v.startswith("base64-")
    b = v[len("base64-"):]
    return json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))


# 1. вход
write_env(GOOD_ENV)
REPLY[0] = (200, session())
code, out, rid, res = run([SID])
check("вход: код 0", code == 0, out)
check("вход: итог done, путь к файлу сессии", res and res.get("state") == "done" and res.get("session"), res)
check("вход: вывод «вошла: сессия»", "вошла: сессия" in out, out)
check("вход: пароль ушёл в тело запроса к Supabase, по https, с публичным ключом",
      CALLS and CALLS[-1][1] == {"email": EMAIL, "password": PASSWORD}
      and CALLS[-1][0] == "https://abcdref.supabase.co/auth/v1/token?grant_type=password"
      and CALLS[-1][2].get("apikey") == ANON, CALLS)
sp = (res or {}).get("session") or os.path.join(QDIR, "нет")
try:
    st = os.lstat(sp)
    sess = json.load(open(sp))
except OSError:
    st, sess = None, {}
check("вход: файл сессии 600 в папке заявок окна",
      st is not None and stat.S_IMODE(st.st_mode) == 0o600 and os.path.dirname(sp) == QDIR, sp)
cks = sess.get("cookies") or []
check("вход: одна cookie sb-abcdref-auth-token для 127.0.0.1",
      [c["name"] for c in cks] == ["sb-abcdref-auth-token"] and cks[0]["domain"] == "127.0.0.1", cks)
check("вход: cookie — base64url JSON сессии", cks and decode_cookies(cks).get("access_token") == "at-" + "x" * 40, cks)
check("вход: expires_at дописан из expires_in", cks and isinstance(decode_cookies(cks).get("expires_at"), int))
check("вход: адрес сервера и script в файле сессии",
      sess.get("url") == "http://127.0.0.1:4301" and "document.cookie" in (sess.get("script") or ""), sess)
check("вход: пароля нет в файле сессии", st is not None and PASSWORD not in open(sp).read())
check("вход: пароля и почты нет в выводе и файле заявки", PASSWORD not in out and EMAIL not in out, out)
txt = everything_text()
check("вход: пароля и почты нет в журнале, runs и итоге", PASSWORD not in txt and EMAIL not in txt and txt, txt[-500:])
check("вход: заявка снята", not [n for n in os.listdir(QDIR) if n.endswith(L.SUFFIX)])

# 2. большая сессия — куски по 3180
REPLY[0] = (200, session(user_pad=5000))
code, out, rid, res = run([SID])
cks = json.load(open(res["session"]))["cookies"] if res and res.get("session") else []
check("куски: .0, .1 … по 3180 знаков, склеиваются в сессию",
      len(cks) >= 2 and [c["name"] for c in cks][:2] == ["sb-abcdref-auth-token.0", "sb-abcdref-auth-token.1"]
      and all(len(c["value"]) <= L.CHUNK for c in cks) and decode_cookies(cks).get("refresh_token") == "rt-1",
      [c["name"] for c in cks])

# 3. отказ Supabase: ответ повторяет пароль — в причину не попадает
REPLY[0] = (400, {"error_code": "invalid_credentials", "msg": f"bad password {PASSWORD} for {EMAIL}"})
code, out, rid, res = run([SID])
check("отказ: код 1, итог failed", code == 1 and res and res.get("state") == "failed", (code, res))
check("отказ: причина — HTTP и код ошибки", "HTTP 400, invalid_credentials" in (res or {}).get("why", ""), res)
check("отказ: «не вошла» в выводе", "не вошла" in out, out)
txt = everything_text()
check("отказ: пароля и почты нет в выводе, журнале, runs и итоге",
      PASSWORD not in out + txt and EMAIL not in out + txt, out)
check("отказ: файла сессии нет", not os.path.exists(os.path.join(QDIR, rid + L.SESSION_SUFFIX)))

# 3б. код ошибки совпал с паролем (похож на код) — вырезается из причины (_scrub в handle)
write_env(GOOD_ENV.replace(PASSWORD, "pw_like_code_77"))
REPLY[0] = (400, {"error_code": "pw_like_code_77"})
code, out, rid, res = run([SID])
check("отказ: значение ключа в коде ошибки вырезано", code == 1 and "pw_like_code_77" not in out + everything_text()
      and "HTTP 400, ***" in (res or {}).get("why", ""), res)
write_env(GOOD_ENV)

# 4. сбой сети с паролем в тексте исключения — только имя класса
REPLY[0] = OSError(f"connect failed {PASSWORD}")
code, out, rid, res = run([SID])
check("сеть: failed, причина — класс без текста",
      code == 1 and "Supabase не ответил: OSError" in (res or {}).get("why", "") and PASSWORD not in out + everything_text(),
      res)

# 5. нет env
clear_env()
n = len(CALLS)
code, out, rid, res = run([SID])
check("нет env: failed, «файла ключей проекта нет», запроса нет",
      code == 1 and "файла ключей проекта нет" in (res or {}).get("why", "") and len(CALLS) == n, res)
write_env(GOOD_ENV.replace(f"TALOS_PASSWORD='{PASSWORD}'\n", ""))
code, out, rid, res = run([SID])
check("нет TALOS_PASSWORD: failed с именем ключа, запроса нет",
      code == 1 and "в файле ключей нет: TALOS_PASSWORD" in (res or {}).get("why", "") and len(CALLS) == n, res)
REPLY[0] = (200, session())
write_env(GOOD_ENV, name="own__repo__web.env")   # файл приложения сервера (app из записи сервера)
code, out, rid, res = run([SID])
check("файл приложения: --app из записи сервера, вход", code == 0 and len(CALLS) == n + 1, res)
clear_env()

# 6. http к чужому хосту — пароль не уходит
write_env(GOOD_ENV.replace("https://abcdref.supabase.co", "http://evil.example.com"))
n = len(CALLS)
code, out, rid, res = run([SID])
check("http не к 127.0.0.1: failed, запроса нет", code == 1 and len(CALLS) == n and "https" in (res or {}).get("why", ""),
      res)
write_env(GOOD_ENV.replace("https://abcdref.supabase.co", "http://127.0.0.1:54321"))
REPLY[0] = (200, session())
code, out, rid, res = run([SID])
check("локальный Supabase по http: вход, cookie sb-127-auth-token",
      code == 0 and CALLS[-1][0].startswith("http://127.0.0.1:54321/auth/v1/token")
      and json.load(open(res["session"]))["cookies"][0]["name"] == "sb-127-auth-token", res)
write_env(GOOD_ENV)

# 7. чужой и несуществующий сервер
n = len(CALLS)
code, out, rid, res = run([FOREIGN])
check("чужой сервер: failed, запроса нет", code == 1 and "не из этого окна" in (res or {}).get("why", "")
      and len(CALLS) == n, res)
code, out, rid, res = run(["20261113-220000-cccccc"])
check("нет сервера: failed, подсказка serve", code == 1 and "pantheon outside serve" in (res or {}).get("why", ""), res)

# 8. команда: плохой ID — код 2 без заявки; без кругов — заявка лежит, в ней только ID сервера
out = io.StringIO()
with contextlib.redirect_stderr(out), contextlib.redirect_stdout(out):
    code = O.main(["login", "../x"])
check("плохой ID: код 2, причина последней строкой", code == 2 and "outside login" in out.getvalue().strip()
      .splitlines()[-1], out.getvalue())
code, out, rid, res = run([SID, "--app", "web"], rounds=False)
req = json.load(open(os.path.join(QDIR, rid + L.SUFFIX)))
check("заявка: только ID сервера и приложение, без ключей",
      code == 0 and req.get("server") == SID and req.get("app") == "web" and PASSWORD not in json.dumps(req)
      and res.get("state") == "queued", req)
os.unlink(os.path.join(QDIR, rid + L.SUFFIX))

# 9. уборка старых файлов сессий; scrub
old = os.path.join(QDIR, "20261101-000000-dddddd" + L.SESSION_SUFFIX)
with open(old, "w") as fh:
    fh.write("{}")
os.utime(old, (time.time() - L.SESSION_TTL - 10,) * 2)
fresh = [n for n in os.listdir(QDIR) if n.endswith(L.SESSION_SUFFIX) and n != os.path.basename(old)]
check("уборка: старый файл сессии удалён, свежие остались",
      L.drop_old_sessions() == 1 and not os.path.exists(old)
      and all(os.path.exists(os.path.join(QDIR, n)) for n in fresh) and fresh)
check("scrub: значение ключа вырезается", L._scrub(f"x {PASSWORD} y", [PASSWORD, "ab"]) == "x *** y")
src = open(os.path.join(LIBDIR, "outside_login.py")).read()
check("модуль без subprocess: пароль не в аргументах процессов", "import subprocess" not in src and "Popen(" not in src)

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
