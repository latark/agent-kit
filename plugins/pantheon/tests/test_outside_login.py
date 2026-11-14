#!/usr/bin/env python3
"""`pantheon outside login` — вход тестовой учётной записью без показа пароля роли (lib/outside_login.py, metis-1134).

Запуск: python3 -I plugins/pantheon/tests/test_outside_login.py  (код выхода 0 — все прошли)
Проверяет на заглушке Supabase (post_json подменён, сети нет): вход → итог done с одноразовым адресом входа
приёмника (start_receiver подменён: cookie @supabase/ssr, один и куски по 3180, уходят ему), в папке заявок окна файла
сессии и токенов нет (metis-1161), пароль ушёл только в тело запроса; отказ Supabase (пароль в ответе) → failed с
кодом ошибки без значений; нет файла ключей, нет TALOS_PASSWORD, http к чужому хосту, сбой сети, сбой приёмника,
чужой и несуществующий сервер — failed без запроса или без значений. Пароля и токенов нет в stdout, stderr, журнале
прохода (logs/outside.jsonl), runs/<ID>.json, итоге и файле заявки. Ответы приёмника (answer): первый заход — 302 и
Set-Cookie, второй и просроченный — 410, чужой код — 404, HEAD — 405 без cookie (код не сожжён); молчащий клиент на
паре сокетов не держит обработчик дольше срока чтения; кода адреса нет в runs/<ID>.json и журнале. Приёмник вживую (процесс, порт) — где порт дают, иначе
строка «пропущено». Заявку входа берёт проход серверов (serve_round), команду — main(["login", …]); файлы сессий
прежней версии убираются.
"""
import atexit
import base64
import contextlib
import io
import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

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


REAL_POST_JSON = L.post_json
L.post_json = fake_post
RECV = []            # вызовы приёмника: (cookies, target, taken)
RECV_FAIL = [None]
RECV_CODE = "Code-" + "k" * 38


def fake_receiver(cookies, target, taken=()):
    RECV.append((cookies, target, set(taken)))
    if RECV_FAIL[0]:
        raise RECV_FAIL[0]
    return 4390, RECV_CODE, time.time() + L.RECEIVE_TTL


REAL_START_RECEIVER = L.start_receiver
L.start_receiver = fake_receiver
TOKEN = "at-" + "x" * 40


def write_env(text, name="own__repo.env"):
    os.makedirs(ENV, exist_ok=True)
    with open(os.path.join(ENV, name), "w") as fh:
        fh.write(text)


def clear_env():
    shutil.rmtree(ENV, ignore_errors=True)


GOOD_ENV = (f"NEXT_PUBLIC_SUPABASE_URL=https://abcdref.supabase.co\nNEXT_PUBLIC_SUPABASE_ANON_KEY={ANON}\n"
            f"TALOS_EMAIL={EMAIL}\nTALOS_PASSWORD='{PASSWORD}'\n")


def session(user_pad=0):
    return {"access_token": TOKEN, "refresh_token": "rt-1", "token_type": "bearer", "expires_in": 3600,
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


def everything_text(tops=(STATE, QDIR, OTHER)):
    """Весь текст STATE (журнал, runs, env кроме самого файла ключей) и папок заявок — всех файлов."""
    parts = []
    for top in tops:
        for d, _, files in os.walk(top):
            if d.startswith(ENV):
                continue
            for f in files:
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
LOGIN_URL = f"http://127.0.0.1:4390{L.LOGIN_PATH}{RECV_CODE}"
check("вход: итог done, одноразовый адрес входа, файла сессии нет",
      res and res.get("state") == "done" and res.get("login_url") == LOGIN_URL and "session" not in res, res)
check("вход: вывод — адрес входа и navigate_page, без evaluate_script",
      LOGIN_URL in out and "navigate_page" in out and "поле script" not in out, out)
check("вход: пароль ушёл в тело запроса к Supabase, по https, с публичным ключом",
      CALLS and CALLS[-1][1] == {"email": EMAIL, "password": PASSWORD}
      and CALLS[-1][0] == "https://abcdref.supabase.co/auth/v1/token?grant_type=password"
      and CALLS[-1][2].get("apikey") == ANON, CALLS)
cks, target, taken = RECV[-1] if RECV else ([], None, set())
check("вход: приёмнику — переход на / сервера, порты серверов заняты",
      target == "http://127.0.0.1:4301/" and {4301, 4302} <= taken, (target, taken))
check("вход: одна cookie sb-abcdref-auth-token для 127.0.0.1",
      [c["name"] for c in cks] == ["sb-abcdref-auth-token"] and cks[0]["domain"] == "127.0.0.1", cks)
check("вход: cookie — base64url JSON сессии", cks and decode_cookies(cks).get("access_token") == TOKEN, cks)
check("вход: expires_at дописан из expires_in", cks and isinstance(decode_cookies(cks).get("expires_at"), int))
qtext = everything_text((QDIR, OTHER))
check("вход: в папке заявок окна нет файла сессии и файла с токенами",
      not [n for n in os.listdir(QDIR) if n.endswith(L.SESSION_SUFFIX)] and TOKEN not in qtext
      and cks and cks[0]["value"] not in qtext, os.listdir(QDIR))
check("вход: пароля и почты нет в выводе и файле заявки", PASSWORD not in out and EMAIL not in out, out)
txt = everything_text()
check("вход: пароля, почты и токенов нет в журнале, runs и итоге",
      PASSWORD not in txt and EMAIL not in txt and TOKEN not in txt and "rt-1" not in txt and txt, txt[-500:])
JOURNAL = os.path.join(STATE, "logs", "outside.jsonl")
check("вход: кода входа нет в журнале прохода, запись входа есть",
      os.path.exists(JOURNAL) and RECV_CODE not in open(JOURNAL).read() and '"receiver": 4390' in open(JOURNAL).read())
check("вход: заявка снята", not [n for n in os.listdir(QDIR) if n.endswith(L.SUFFIX)])
RUN_JSON = os.path.join(STATE, "outside", "runs", f"{rid}.json")
run_rec = P.read_json(RUN_JSON, {}) if rid else {}
check("вход: в runs/<rid>.json (его читают окна) кода адреса нет, порт приёмника и итог done есть (argus #453 Д)",
      os.path.exists(RUN_JSON) and RECV_CODE not in open(RUN_JSON).read() and run_rec.get("state") == "done"
      and run_rec.get("receiver") == 4390 and "login_url" not in run_rec, run_rec)
check("вход: кода адреса нет нигде в STATE (журнал, runs), он только в итоге папки заявок окна",
      RECV_CODE not in everything_text((STATE,)) and RECV_CODE in open(os.path.join(QDIR, rid + ".result.json")).read())

# 1б. приёмник не поднялся (текст сбоя с токеном и паролем) — failed без значений
RECV_FAIL[0] = OSError(f"bind {TOKEN} {PASSWORD}")
code, out, rid, res = run([SID])
RECV_FAIL[0] = None
check("приёмник: сбой — failed «приёмник входа не поднять», без токена и пароля",
      code == 1 and "приёмник входа не поднять" in (res or {}).get("why", "")
      and TOKEN not in out + everything_text() and PASSWORD not in out + everything_text(), res)

# 2. большая сессия — куски по 3180
REPLY[0] = (200, session(user_pad=5000))
code, out, rid, res = run([SID])
cks = RECV[-1][0] if code == 0 and RECV else []
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

# 4б. TLS: у python.org Python нет своих CA → CA системы из SYSTEM_CA (metis-1134)
class NoCaCtx:
    loaded = []

    def get_ca_certs(self):
        return []

    def load_verify_locations(self, cafile=None, **kw):
        NoCaCtx.loaded.append(cafile)


FAKE_CA = os.path.join(_ROOT, "fake-cert.pem")
with open(FAKE_CA, "w") as fh:
    fh.write("x")
real_ctx, real_vp, real_ca = ssl.create_default_context, ssl.get_default_verify_paths, L.SYSTEM_CA
ssl.create_default_context = lambda *a, **k: NoCaCtx()
ssl.get_default_verify_paths = lambda: type("VP", (), {"cafile": "/nonexistent/cafile", "capath": "/nonexistent/capath"})()
L.SYSTEM_CA = FAKE_CA
try:
    L.ssl_context()
finally:
    ssl.create_default_context, ssl.get_default_verify_paths, L.SYSTEM_CA = real_ctx, real_vp, real_ca
check("TLS: контекст без CA получает cafile из SYSTEM_CA", NoCaCtx.loaded == [FAKE_CA], NoCaCtx.loaded)
seen = {}


class FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return b"{}"


real_urlopen = urllib.request.urlopen
urllib.request.urlopen = lambda req, **kw: (seen.update(kw), FakeResp())[1]
try:
    REAL_POST_JSON("https://x.invalid/a", {}, {})
finally:
    urllib.request.urlopen = real_urlopen
check("TLS: post_json передаёт контекст в urlopen", isinstance(seen.get("context"), ssl.SSLContext), seen)

# 4в. причина с классом reason у URLError, без текста
REPLY[0] = urllib.error.URLError(ssl.SSLCertVerificationError(f"verify failed {PASSWORD}"))
code, out, rid, res = run([SID])
check("сеть: URLError(SSLCertVerificationError) — причина с классом reason, без текста",
      code == 1 and "Supabase не ответил: URLError (SSLCertVerificationError)" in (res or {}).get("why", "")
      and PASSWORD not in out + everything_text(), res)

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
      and RECV[-1][0][0]["name"] == "sb-127-auth-token", res)
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

# 9. уборка файлов сессий прежней версии (0.11.310, с токенами) — круг прохода; ссылку не трогает; scrub
old = os.path.join(QDIR, "20261101-000000-dddddd" + L.SESSION_SUFFIX)
with open(old, "w") as fh:
    fh.write(json.dumps({"cookies": [{"value": TOKEN}]}))
link = os.path.join(OTHER, "20261101-000000-eeeeee" + L.SESSION_SUFFIX)
os.symlink(FAKE_CA, link)
O.serve_round()
check("уборка: файл сессии прежней версии удалён кругом прохода, ссылка и её цель целы",
      not os.path.exists(old) and os.path.islink(link) and os.path.exists(FAKE_CA))
os.unlink(link)
check("scrub: значение ключа вырезается", L._scrub(f"x {PASSWORD} y", [PASSWORD, "ab"]) == "x *** y")

# 9б. папку заявок не прочесть — _take_requests входа → [], без исключения (metis-1186: круг идёт до уборки serve_round)
_real_ld, _ld_calls = os.listdir, []


def _ld_boom(path="."):
    if isinstance(path, int):
        _ld_calls.append(path)
        raise PermissionError("нет доступа")
    return _real_ld(path)


os.listdir = _ld_boom
try:
    _taken, _err = L._take_requests(), None
except OSError as e:
    _taken, _err = None, e
finally:
    os.listdir = _real_ld
check("listdir папки заявок упал: login._take_requests → [], без исключения", _taken == [] and _err is None
      and _ld_calls, (_taken, _err, _ld_calls))

# 10. приёмник: ответы (без сети) — первый заход ставит cookie и ведёт на сервер, второй и просроченный — отказ
ck = [["sb-abcdref-auth-token", "base64-AAA"]]
st0 = {"code": RECV_CODE, "cookies": ck, "target": "http://127.0.0.1:4301/", "deadline": time.time() + 60,
       "used": False, "misses": 0}
s, h, _ = L.answer(st0, "GET", L.LOGIN_PATH + RECV_CODE)
hd = dict(h)
setc = [v for k, v in h if k == "Set-Cookie"]
check("приёмник: первый заход — 302 на / сервера, Set-Cookie сессии",
      s == 302 and hd.get("Location") == "http://127.0.0.1:4301/" and setc
      and setc[0].startswith("sb-abcdref-auth-token=base64-AAA; Path=/;") and "SameSite=Lax" in setc[0], h)
check("приёмник: прежние куски .0–.4 стираются (Max-Age=0)",
      "sb-abcdref-auth-token.0=; Path=/; Max-Age=0; SameSite=Lax" in setc and len(setc) == 1 + L.STALE_CHUNKS, setc)
s2, h2, b2 = L.answer(st0, "GET", L.LOGIN_PATH + RECV_CODE)
check("приёмник: второй заход по коду — 410 без cookie", s2 == 410 and not h2 and "уже использован" in b2, (s2, h2))
st1 = {**st0, "used": False, "deadline": time.time() - 1}
s3, h3, b3 = L.answer(st1, "GET", L.LOGIN_PATH + RECV_CODE)
check("приёмник: просроченный код — 410 без cookie, не помечен использованным",
      s3 == 410 and not h3 and "срок" in b3 and not st1["used"], (s3, h3))
st2 = {**st0, "used": False, "misses": 0}
s4, h4, _ = L.answer(st2, "GET", L.LOGIN_PATH + RECV_CODE[:-1] + "z")
s5, _, _ = L.answer(st2, "GET", "/" + RECV_CODE)
s6, _, _ = L.answer(st2, "POST", L.LOGIN_PATH + RECV_CODE)
check("приёмник: чужой код — 404 и счёт промахов; чужой путь и POST — 404, код цел",
      s4 == 404 and not h4 and st2["misses"] == 1 and s5 == 404 and s6 == 404 and not st2["used"], st2)
st4 = {**st0, "used": False, "misses": 0}
s7, h7, _ = L.answer(st4, "HEAD", L.LOGIN_PATH + RECV_CODE)
s8, h8, _ = L.answer(st4, "GET", L.LOGIN_PATH + RECV_CODE)
check("приёмник: HEAD по верному коду — 405 без Set-Cookie и без used; следом GET входит (argus #453 С)",
      s7 == 405 and not [k for k, _ in h7 if k == "Set-Cookie"] and dict(h7).get("Allow") == "GET"
      and s8 == 302 and st4["used"], (s7, h7, s8))
chunked = L.set_cookie_headers([["sb-r-auth-token.0", "a"], ["sb-r-auth-token.1", "b"]])
check("приёмник: куски — стирается цельная cookie и лишние куски, свои не стираются",
      "sb-r-auth-token=; Path=/; Max-Age=0; SameSite=Lax" in chunked
      and not any(c.startswith(("sb-r-auth-token.0=;", "sb-r-auth-token.1=;")) for c in chunked)
      and any(c.startswith("sb-r-auth-token.4=;") for c in chunked), chunked)

# 10б. обработчик HTTP приёмника на паре сокетов (порт не нужен): заголовки ответа, второй заход — 410
def http_once(state, path, method="GET"):
    a, b = socket.socketpair()
    with a, b:
        b.sendall(f"{method} {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode())
        L.handler_class(state)(a, ("127.0.0.1", 0), None)
        a.shutdown(socket.SHUT_WR)
        raw = b""
        while chunk := b.recv(65536):
            raw += chunk
    return raw.decode(errors="replace")


st3 = {"code": RECV_CODE, "cookies": ck, "target": "http://127.0.0.1:4301/", "deadline": time.time() + 60,
       "used": False, "misses": 0}
r1 = http_once(st3, L.LOGIN_PATH + RECV_CODE)
r2 = http_once(st3, L.LOGIN_PATH + RECV_CODE)
check("HTTP: первый заход — 302, Location и Set-Cookie в заголовках",
      r1.startswith("HTTP/1.0 302") and "\r\nLocation: http://127.0.0.1:4301/\r\n" in r1
      and "\r\nSet-Cookie: sb-abcdref-auth-token=base64-AAA; Path=/;" in r1, r1[:400])
check("HTTP: второй заход — 410 без Set-Cookie", r2.startswith("HTTP/1.0 410") and "Set-Cookie" not in r2, r2[:300])
st5 = {**st3, "used": False, "misses": 0}
r3 = http_once(st5, L.LOGIN_PATH + RECV_CODE, "HEAD")
check("HTTP: HEAD — 405 без Set-Cookie, код не сожжён", r3.startswith("HTTP/1.0 405") and "Set-Cookie" not in r3
      and not st5["used"], r3[:300])


def silent_client(first=b""):
    """Клиент на паре сокетов шлёт first и молчит → (обработчик вышел сам, за сколько с). Срок чтения — 1 с."""
    a, b = socket.socketpair()
    L.REQUEST_TIMEOUT, keep = 1, L.REQUEST_TIMEOUT
    try:
        handler = L.handler_class({**st3, "used": False, "misses": 0})
    finally:
        L.REQUEST_TIMEOUT = keep
    def serve():
        with contextlib.suppress(OSError):
            handler(a, ("127.0.0.1", 0), None)

    t0 = time.monotonic()
    th = threading.Thread(target=serve, daemon=True)
    with a, b:
        if first:
            b.sendall(first)
        th.start()
        th.join(6)
        done, took = not th.is_alive(), time.monotonic() - t0
        b.close()   # на откате правки — EOF, обработчик выходит и тест не висит
        th.join(5)
    return done, took


done, took = silent_client()
check("HTTP: молчащий клиент — обработчик выходит сам за срок чтения (argus #453 Б)", done and took < 4, (done, took))
done, took = silent_client(b"GET " + (L.LOGIN_PATH + RECV_CODE).encode() + b" HTTP/1.0\r\nHost: x\r\n")
check("HTTP: заголовки без конца — обработчик выходит сам за срок чтения", done and took < 4, (done, took))

# 10в. процесс приёмника: сессия — в stdin, не в аргументах; срок вышел — выходит сам с кодом 0
pa, pb = socket.socketpair()
L.RECEIVE_TTL, ttl = 0, L.RECEIVE_TTL
try:
    code0, _ = L.spawn_receiver(pa, L.session_cookies("https://abcdref.supabase.co", session(), "127.0.0.1"),
                                "http://127.0.0.1:4301/")
    proc = L._RECEIVERS[-1]
    proc.wait(10)
except OSError as e:
    code0, proc = None, None
    check("процесс приёмника: ответил «ready»", False, e)
finally:
    L.RECEIVE_TTL = ttl
    pb.close()
check("процесс приёмника: «ready», вышел сам по сроку с кодом 0, сокет прохода закрыт",
      proc is not None and proc.returncode == 0 and pa.fileno() == -1, proc and proc.returncode)
check("процесс приёмника: в аргументах нет токенов, кода и пароля",
      proc is not None and "--receive" in proc.args
      and not any(TOKEN in a or (code0 or "?") in a or PASSWORD in a for a in proc.args), proc and proc.args)
check("процесс приёмника: вышедшие убраны", L.reap_receivers() == 0, L._RECEIVERS)

# 11. приёмник вживую: свой процесс, сокет на порту ряда серверов (в окне роли порта нет — пропуск)
L.start_receiver = REAL_START_RECEIVER


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch(url):
    """→ (код HTTP, заголовки) или (None, класс ошибки)."""
    try:
        with urllib.request.build_opener(NoRedirect).open(url, timeout=5) as r:
            return r.status, r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers
    except OSError as e:
        return None, type(e).__name__


live_cookies = L.session_cookies("https://abcdref.supabase.co", session(), "127.0.0.1")
try:
    port, code, until = L.start_receiver(live_cookies, "http://127.0.0.1:4301/", {4301})
except OSError as e:
    port = None
    print(f"skip приёмник вживую — пропущено: нет местного порта ({e})")
if port:
    proc = L._RECEIVERS[-1]
    check("вживую: в аргументах процесса приёмника нет токенов, кода и пароля",
          not any(TOKEN in a or code in a or PASSWORD in a for a in proc.args) and "--receive" in proc.args, proc.args)
    s, hd = fetch(f"http://127.0.0.1:{port}{L.LOGIN_PATH}{code}x")
    check("вживую: чужой код — 404", s == 404, s)
    s, hd = fetch(f"http://127.0.0.1:{port}{L.LOGIN_PATH}{code}")
    check("вживую: адрес входа — 302 на сервер с cookie сессии",
          s == 302 and hd.get("Location") == "http://127.0.0.1:4301/"
          and any(v.startswith("sb-abcdref-auth-token=base64-") for v in hd.get_all("Set-Cookie") or []), (s, hd))
    proc.wait(5)
    s2, _ = fetch(f"http://127.0.0.1:{port}{L.LOGIN_PATH}{code}")
    check("вживую: после входа приёмник вышел, второй заход — отказ", proc.returncode == 0 and s2 != 302, (s2, proc.returncode))
    L.RECEIVE_TTL, ttl = 0, L.RECEIVE_TTL
    port, code, _ = L.start_receiver(live_cookies, "http://127.0.0.1:4301/", {4301})
    L.RECEIVE_TTL = ttl
    L._RECEIVERS[-1].wait(5)
    s3, _ = fetch(f"http://127.0.0.1:{port}{L.LOGIN_PATH}{code}")
    check("вживую: просроченный код — приёмник вышел сам, отказ", s3 != 302 and L._RECEIVERS[-1].returncode == 0, s3)
    check("вживую: вышедшие приёмники убраны", L.reap_receivers() == 0)

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
