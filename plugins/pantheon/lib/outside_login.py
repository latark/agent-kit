"""`pantheon outside login <ID сервера> [--app ИМЯ] [--wait С]` — вход тестовой учётной записью в приложение сервера
outside, не показывая пароль роли (metis-1134).

Зачем. talos проверяет экраны за входом, а файл ключей направления (outside/env) окну роли закрыт и должен остаться
закрытым. Браузер talos — chrome-devtools-mcp с --isolated: профиль временный, своего порта отладки наружу нет, поэтому
проход положить cookie прямо в него не может. Проход входит сам и отдаёт роли готовую сессию.

Как. Заявка `<rid>.login.json` — в папке заявок окна (own_qdir), рядом с заявками serve; в ней только ID сервера и
приложение, без ключей. Исполняет её проход серверов (outside.serve_round → login_round), вне окна роли:
  1. сервер ID жив и поднят из этой же папки заявок (чужой сервер — отказ);
  2. ключи — те же файлы outside/env, что у сервера (outside.dev_keys): TALOS_EMAIL, TALOS_PASSWORD, адрес Supabase
     и публичный ключ (NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY и близкие имена);
  3. Supabase Auth `POST /auth/v1/token?grant_type=password` из процесса прохода (urllib, без subprocess: пароля нет
     в аргументах процессов); адрес — только https, кроме 127.0.0.1/localhost;
  4. сессия — cookie @supabase/ssr (`sb-<ref>-auth-token`, «base64-» + base64url JSON, куски по 3180 знаков). Их
     держит только приёмник входа (metis-1161): процесс прохода `python3 -I outside_login.py --receive <fd>` со
     своим портом из ряда серверов (сокет открывает проход и отдаёт дескриптором). Сессию он получает каналом stdin —
     ни на диске, ни в аргументах процессов её нет; в папке заявок окна файла сессии нет.
  5. роли — одноразовый адрес входа `http://127.0.0.1:<порт приёмника>/pantheon-login/<код>` (код secrets, 32 байта).
     Первый заход по нему — ответ 302 с Set-Cookie (те же cookie @supabase/ssr, хост 127.0.0.1: cookie не делятся по
     портам, поэтому их видит и dev-сервер) и переход на `http://127.0.0.1:<порт сервера>/`. Второй заход — отказ 410,
     чужой путь или код — 404; после удачного захода, через RECEIVE_TTL (10 мин) или после MAX_MISSES чужих кодов
     приёмник выходит сам. HEAD по верному коду — 405 без cookie: проверка ссылки код не сжигает. Срок чтения
     запроса — REQUEST_TIMEOUT (5 с): молчащий клиент не держит однопоточный приёмник. talos просто открывает адрес
     (navigate_page) — без evaluate_script с токенами: его режет классификатор auto (Афина, 14.11).
В итоге роли (`<rid>.result.json`), журнале прохода (logs/outside.jsonl) и runs/<rid>.json — только «вошла / не
вошла», причина без значений и адрес входа. Код адреса — только в `<rid>.result.json` папки заявок окна, подавшего
заявку; в журнале и runs/<rid>.json (их читают окна) — только порт приёмника. Пароля, почты и токенов нет нигде,
кроме тела запроса к Supabase и памяти приёмника; любая причина отказа проходит через _scrub (значения ключей
вырезаются). Файлы `<rid>.session.json` прежней версии (0.11.310) с токенами проход удаляет из папок заявок.

Почему не форма /auth: для неё проходу нужен свой браузер, а Supabase Auth — один запрос с публичным ключом.
Почему не прокси перед dev-сервером: cookie хоста 127.0.0.1 общие для всех портов, хватает приёмника рядом.
"""
import base64
import contextlib
import hmac
import http.server
import json
import os
import re
import secrets
import select
import socket
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

P = None   # lib/pantheon.py
O = None   # lib/outside.py

SUFFIX = ".login.json"
SESSION_SUFFIX = ".session.json"    # файл сессии прежней версии (0.11.310): проход его удаляет
RECEIVE_TTL = 10 * 60               # с: срок адреса входа и жизни приёмника
RECEIVE_READY = 5                   # с: ждать от приёмника «готов»
MAX_MISSES = 20                     # чужих кодов — приёмник выходит
REQUEST_TIMEOUT = 5                 # с: срок чтения запроса одним соединением (молчащий клиент не вешает приёмник)
LOGIN_PATH = "/pantheon-login/"
COOKIE_MAX_AGE = 400 * 24 * 3600
STALE_CHUNKS = 5                    # кусков cookie прежней сессии стереть
HTTP_TIMEOUT = 20                   # с
WAIT_DEFAULT = 60                   # с: CLI ждёт итог входа по умолчанию
CHUNK = 3180                        # @supabase/ssr MAX_CHUNK_SIZE
EMAIL_KEY, PASSWORD_KEY = "TALOS_EMAIL", "TALOS_PASSWORD"
URL_KEYS = ("NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_URL", "VITE_SUPABASE_URL", "PUBLIC_SUPABASE_URL")
ANON_KEYS = ("NEXT_PUBLIC_SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY",
             "VITE_SUPABASE_ANON_KEY", "PUBLIC_SUPABASE_ANON_KEY")
SYSTEM_CA = "/etc/ssl/cert.pem"     # CA системы: у python.org Python своих нет (CERTIFICATE_VERIFY_FAILED); тест подменяет
CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,59}")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
USAGE = "pantheon outside login <ID сервера> [--app ИМЯ] [--wait С]"


def set_core(p, o):
    global P, O
    P, O = p, o


def ssl_context():
    """Контекст TLS. Нет ни одного загруженного CA (python.org Python без своих) — берём CA системы из SYSTEM_CA."""
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        vp = ssl.get_default_verify_paths()
        if not (vp.cafile and os.path.exists(vp.cafile)) and not (vp.capath and os.path.isdir(vp.capath)) \
                and os.path.isfile(SYSTEM_CA):
            ctx.load_verify_locations(cafile=SYSTEM_CA)
    return ctx


def post_json(url, body, headers, timeout=HTTP_TIMEOUT):
    """POST JSON → (код HTTP, разобранный ответ или None). Сеть — только здесь (тест подменяет)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:   # noqa: S310 — адрес проверен в supabase_url
            status, raw = r.status, r.read(1024 * 1024)
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read(64 * 1024)
    try:
        return status, json.loads(raw.decode() or "null")
    except ValueError:
        return status, None


def _scrub(text, values):
    """Причина без значений ключей: каждое непустое значение длиннее 3 знаков → «***»."""
    for v in sorted({v for v in values if v and len(v) > 3}, key=len, reverse=True):
        text = text.replace(v, "***")
    return text


def supabase_url(keys):
    """(адрес Supabase без хвоста «/», None), (None, причина) или (None, None) — ключа адреса нет. https, кроме
    локального Supabase."""
    name = next((k for k in URL_KEYS if keys.get(k)), None)
    if not name:
        return None, None
    u = urllib.parse.urlsplit(keys[name].strip())
    if u.scheme not in ("https", "http") or not u.hostname:
        return None, f"{name} — не адрес http(s)"
    if u.scheme == "http" and u.hostname not in LOCAL_HOSTS:
        return None, f"{name} — http не к 127.0.0.1: пароль уходит только по https"
    return f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}", None


def cookie_name(url):
    """Имя cookie сессии @supabase/ssr по умолчанию: sb-<первая часть имени хоста>-auth-token."""
    return f"sb-{urllib.parse.urlsplit(url).hostname.split('.')[0]}-auth-token"


def session_cookies(url, session, host):
    """Сессия Supabase → cookie @supabase/ssr (кодирование base64url, куски по CHUNK) для host, как storageState."""
    value = "base64-" + base64.urlsafe_b64encode(json.dumps(session, separators=(",", ":")).encode()) \
        .decode().rstrip("=")
    name = cookie_name(url)
    parts = [value] if len(value) <= CHUNK else [value[i:i + CHUNK] for i in range(0, len(value), CHUNK)]
    expires = int(time.time()) + 400 * 24 * 3600
    return [{"name": name if len(parts) == 1 else f"{name}.{i}", "value": v, "domain": host, "path": "/",
             "expires": expires, "httpOnly": False, "secure": False, "sameSite": "Lax"} for i, v in enumerate(parts)]


def set_cookie_headers(cookies):
    """[[имя, значение]] → значения Set-Cookie: cookie сессии и стирание кусков прежней (иначе @supabase/ssr склеит
    чужие куски)."""
    names = [n for n, _ in cookies]
    base = names[0].rsplit(".", 1)[0] if len(names) > 1 else names[0]
    out = [f"{n}={v}; Path=/; Max-Age={COOKIE_MAX_AGE}; SameSite=Lax" for n, v in cookies]
    stale = ([base] if len(names) > 1 else []) + [f"{base}.{i}" for i in range(STALE_CHUNKS) if f"{base}.{i}" not in names]
    return out + [f"{n}=; Path=/; Max-Age=0; SameSite=Lax" for n in stale]


def answer(state, method, path, now=None):
    """Ответ приёмника на запрос → (код HTTP, [(заголовок, значение)], тело). state: code, cookies, target, deadline,
    used, misses — меняется: удачный заход GET ставит used, чужой код под LOGIN_PATH прибавляет misses. HEAD по
    верному коду — 405 без cookie и без used: проверка ссылки код не сжигает."""
    now = time.time() if now is None else now
    if method not in ("GET", "HEAD") or not path.startswith(LOGIN_PATH):
        return 404, [], "нет такого адреса"
    code = path[len(LOGIN_PATH):].split("?", 1)[0]
    if not hmac.compare_digest(code.encode(), str(state["code"]).encode()):
        state["misses"] = state.get("misses", 0) + 1
        return 404, [], "нет такого адреса"
    if state.get("used"):
        return 410, [], "адрес входа уже использован — подай pantheon outside login заново"
    if now >= state["deadline"]:
        return 410, [], "срок адреса входа вышел — подай pantheon outside login заново"
    if method == "HEAD":   # проверка ссылки (HEAD) код не сжигает: без used и без cookie (argus #453 С)
        return 405, [("Allow", "GET"), ("Cache-Control", "no-store")], "вход — только заходом GET (navigate_page)"
    state["used"] = True
    return 302, [("Set-Cookie", h) for h in set_cookie_headers(state["cookies"])] + [
        ("Location", state["target"]), ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")], \
        "вход: переход на сервер"


def handler_class(state):
    """Обработчик http.server для приёмника: ответ — answer(state, …), журнала запросов нет (в пути — код). Срок
    чтения запроса — REQUEST_TIMEOUT: молчащий клиент (preconnect браузера) не держит однопоточный приёмник дольше
    (argus #453 Б); по сроку обработчик закрывает соединение без ответа."""
    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT   # StreamRequestHandler.setup → settimeout на принятом сокете

        def _go(self, method):
            status, headers, body = answer(state, method, self.path)
            raw = body.encode()
            self.send_response(status)
            for k, v in headers + [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(raw)))]:
                self.send_header(k, v)
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(raw)

        def do_GET(self):  # noqa: N802 — имя метода задаёт http.server
            self._go("GET")

        def do_HEAD(self):  # noqa: N802
            self._go("HEAD")

        def log_message(self, *a):   # путь с кодом не пишем никуда
            pass

    return Handler


def receive_main(fd):
    """Приёмник входа (процесс прохода): слушающий сокет — дескриптор fd, сессия — JSON из stdin. Готов — «ready» в
    stdout. Выход — после удачного захода, через срок или после MAX_MISSES чужих кодов."""
    sock = socket.socket(fileno=fd)
    state = json.loads(sys.stdin.buffer.read(1024 * 1024).decode())
    state.update(used=False, misses=0)
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_class(state), bind_and_activate=False)
    srv.socket.close()
    srv.socket, srv.timeout = sock, 1
    sys.stdout.write("ready\n")
    sys.stdout.flush()
    while not state["used"] and state["misses"] < MAX_MISSES and time.time() < state["deadline"]:
        srv.handle_request()
    srv.server_close()
    return 0


_RECEIVERS = []


def start_receiver(cookies, target, taken=()):
    """Поднять приёмник входа: сокет на свободном порту ряда серверов (не taken, не порты владельца), процесс
    `outside_login.py --receive` с сессией в stdin → (порт, код, срок epoch). Сбой — OSError (причина без значений)."""
    sock = listen_socket(taken)
    port = sock.getsockname()[1]
    code, deadline = spawn_receiver(sock, cookies, target)
    return port, code, deadline


def listen_socket(taken=()):
    """Слушающий сокет 127.0.0.1 на первом свободном порту ряда серверов, кроме taken и портов владельца. Сбой —
    OSError с классом последней ошибки (в окне роли — PermissionError: портов нет)."""
    sock, last = None, None
    for p in O.SERVER_PORTS:
        if p in taken or p in O.OWNER_PORTS:
            continue
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))   # без SO_REUSEADDR, как outside.port_free
            s.listen(16)
            sock = s
            break
        except OSError as e:
            s.close()
            last = e
    if sock is None:
        raise OSError(f"нет свободного порта {O.SERVER_PORTS.start}–{O.SERVER_PORTS.stop - 1}"
                      + (f" ({type(last).__name__})" if last else ""))
    return sock


def spawn_receiver(sock, cookies, target):
    """Процесс приёмника на сокете sock (копию прохода закрывает), сессия — в stdin, не в аргументах и не на диске →
    (код, срок epoch). Не ответил «ready» за RECEIVE_READY — гасит и OSError."""
    code, deadline = secrets.token_urlsafe(32), time.time() + RECEIVE_TTL
    try:
        proc = subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "--receive", str(sock.fileno())],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                pass_fds=(sock.fileno(),), start_new_session=True, env={"LANG": "C.UTF-8"})
    finally:
        sock.close()   # копия прохода: сокет держит приёмник
    ok = False
    try:
        proc.stdin.write(json.dumps({"code": code, "cookies": [[c["name"], c["value"]] for c in cookies],
                                     "target": target, "deadline": deadline}).encode())
        proc.stdin.close()
        ready, _, _ = select.select([proc.stdout], [], [], RECEIVE_READY)
        ok = bool(ready) and proc.stdout.readline().strip() == b"ready"
    except OSError:
        ok = False
    finally:
        proc.stdout.close()
    if not ok:
        with contextlib.suppress(OSError):
            proc.kill()
        proc.wait(5)
        raise OSError("приёмник входа не ответил")
    _RECEIVERS.append(proc)
    return code, deadline


def reap_receivers():
    """Вышедшие приёмники — дождаться (без зомби у прохода). → число живых."""
    _RECEIVERS[:] = [p for p in _RECEIVERS if p.poll() is None]
    return len(_RECEIVERS)


def sign_in(keys):
    """Вход по паролю → (сессия, None) или (None, причина без значений)."""
    missing = [k for k in (EMAIL_KEY, PASSWORD_KEY) if not keys.get(k)]
    anon = next((keys[k] for k in ANON_KEYS if keys.get(k)), None)
    if not anon:
        missing.append(" или ".join(ANON_KEYS[:2]))
    url, why = supabase_url(keys)
    if why:
        return None, why, None
    if not url:
        missing.append(" или ".join(URL_KEYS[:2]))
    if missing:
        return None, "в файле ключей нет: " + ", ".join(missing), None
    try:
        status, body = post_json(f"{url}/auth/v1/token?grant_type=password",
                                 {"email": keys[EMAIL_KEY], "password": keys[PASSWORD_KEY]},
                                 {"apikey": anon, "Authorization": f"Bearer {anon}"})
    except (OSError, ValueError) as e:   # urllib.error.URLError — OSError; причина — только класс
        why = type(e).__name__
        if isinstance(e, urllib.error.URLError) and isinstance(e.reason, BaseException):
            why += f" ({type(e.reason).__name__})"   # только имена классов: ни текста, ни адреса
        return None, f"Supabase не ответил: {why}", url
    if status == 200 and isinstance(body, dict) and body.get("access_token") and body.get("refresh_token"):
        if not body.get("expires_at") and isinstance(body.get("expires_in"), int):
            body["expires_at"] = int(time.time()) + body["expires_in"]
        return body, None, url
    code = ""
    if isinstance(body, dict):
        code = next((str(body[k]) for k in ("error_code", "code", "error") if isinstance(body.get(k), str)
                     and CODE_RE.fullmatch(str(body[k]))), "")
    return None, f"Supabase отказал: HTTP {status}" + (f", {code}" if code else ""), url


# --- проход серверов -----------------------------------------------------------------------------------------------

def check(req, rid):
    if not isinstance(req, dict) or req.get("v") != 1 or req.get("id") != rid or req.get("kind") != "login":
        return "заявка входа не в формате (v1, kind login, id = имя файла)"
    if not isinstance(req.get("server"), str) or not O.ID_RE.fullmatch(req["server"]):
        return "в заявке нет ID сервера"
    app = req.get("app")
    if app is not None and not (isinstance(app, str) and O.APP_RE.fullmatch(app)):
        return "имя приложения не по образцу"
    return None


def handle(qdir, window, rid, req):
    """Заявка входа rid из папки qdir → итог done (вошла) или failed (не вошла, причина без значений)."""
    sid = req.get("server") if isinstance(req, dict) else None
    base = {"kind": "login", **({"server": sid} if isinstance(sid, str) else {})}
    values = []

    def fail(why):
        why = _scrub(why, values)
        O.log_event(id=rid, kind="login", window=window, server=sid, ok=False, why=why)
        return O.save_result(qdir, rid, {"state": "failed", **base, "why": "не вошла: " + why})

    why = check(req, rid)
    if why:
        return fail(why)
    age = P.now() - (O._epoch(req) or P.now())
    if age > O.REQ_TTL:
        return fail(f"заявка пролежала {int(age // 60)} мин — подай заново")
    srv = O.servers().get(sid)
    if not isinstance(srv, dict):
        return fail(f"сервера {sid} нет — подними его: pantheon outside serve, затем login с его ID")
    if srv.get("qdir") != qdir:
        return fail(f"сервер {sid} поднят не из этого окна")
    port, app = srv.get("port"), req.get("app") or srv.get("app")
    keys, used, _ = O.dev_keys(O.origin_id(srv.get("common")), app)
    values = list(keys.values())
    if not used:
        return fail("файла ключей проекта нет — TALOS_EMAIL и TALOS_PASSWORD кладёт владелец в outside/env")
    session, why, url = sign_in(keys)
    if not session:
        return fail(why)
    cookies = session_cookies(url, session, "127.0.0.1")
    origin = f"http://127.0.0.1:{port}"
    values += [c["value"] for c in cookies] + [str(session.get(k)) for k in ("access_token", "refresh_token")]
    try:
        rport, code, until = start_receiver(cookies, origin + "/",
                                            {int(v.get("port") or 0) for v in O.servers().values()})
    except OSError as e:
        return fail(f"приёмник входа не поднять: {_scrub(str(e), values)}")
    login_url = f"http://127.0.0.1:{rport}{LOGIN_PATH}{code}"
    O.log_event(id=rid, kind="login", window=window, server=sid, ok=True, cookies=len(cookies), receiver=rport)
    note = (f"вошла: открой адрес входа {login_url} в chrome-devtools (navigate_page) — он один раз ставит cookie и "
            f"ведёт на {origin}/. Адрес одноразовый, до {P.stamp(until)}; evaluate_script и файл сессии не нужны")
    # код адреса — только в итоге своей папки заявок; runs/<rid>.json читают окна, там адрес без кода (argus #453 Д)
    public = {"state": "done", "code": 0, **base, "receiver": rport, "until": P.stamp(until),
              "note": f"вошла: одноразовый адрес входа на порту {rport} — в итоге заявки у окна, подавшего её"}
    return O.save_result(qdir, rid, public, private={"login_url": login_url, "note": note})


def _take_requests():
    """[(qdir, окно, rid, заявка)] — заявки входа во всех папках заявок, снятые с диска."""
    out = []
    for qdir, window in O.queue_dirs():
        dfd = O._open_dir(qdir)
        if dfd is None:
            continue
        try:
            for name in sorted(os.listdir(dfd)):
                if not name.endswith(SUFFIX):
                    continue
                rid = name[:-len(SUFFIX)]
                text = O._read_in(dfd, name)
                if not O.ID_RE.fullmatch(rid):
                    O._unlink_in(dfd, name)
                    continue
                if not O._take_in(dfd, name):   # снял другой проход
                    continue
                out.append((qdir, window, rid, O._parse(text)))
        finally:
            os.close(dfd)
    return out


def drop_session_files():
    """Файлы сессий прежней версии (`<rid>.session.json` с токенами, 0.11.310) в папках заявок — удалить (обычные
    файлы, не ссылки). → число."""
    n = 0
    for qdir, _ in O.queue_dirs():
        dfd = O._open_dir(qdir)
        if dfd is None:
            continue
        try:
            for name in os.listdir(dfd):
                if not name.endswith(SESSION_SUFFIX):
                    continue
                with contextlib.suppress(OSError):
                    st = os.lstat(name, dir_fd=dfd)
                    if stat.S_ISREG(st.st_mode):
                        os.unlink(name, dir_fd=dfd)
                        n += 1
        finally:
            os.close(dfd)
    return n


def login_round():
    """Круг прохода серверов: заявки входа, затем уборка вышедших приёмников и файлов сессий прежней версии."""
    for qdir, window, rid, req in _take_requests():
        try:
            handle(qdir, window, rid, req)
        except Exception as e:  # noqa: BLE001 — сбой одной заявки: итог failed, круг идёт; причина — класс без текста
            O.log_event(id=rid, kind="login-error", window=window, why=type(e).__name__)
            O.save_result(qdir, rid, {"state": "failed", "kind": "login",
                                      "why": f"не вошла: сбой прохода: {type(e).__name__}"})
    reap_receivers()
    drop_session_files()


# --- команда роли --------------------------------------------------------------------------------------------------

def cmd_login(args):
    f = O._flags(args[1:], {"--app", "--wait"}) if args else None
    if f is None or not O.ID_RE.fullmatch(args[0]):
        O.err(f"pantheon outside: {USAGE}")
        return 2
    try:
        wait = max(0, min(int(f.get("--wait", WAIT_DEFAULT)), O.WAIT_MAX))
    except ValueError:
        O.err("pantheon outside: --wait — целое число")
        return 2
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    req = {"v": 1, "id": rid, "kind": "login", "server": args[0], "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "by": " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "").split())[:40]}
    if f.get("--app"):
        req["app"] = f["--app"]
    why = check(req, rid)
    if why:
        O.err(f"pantheon outside: {why}")
        return 2
    q = O.own_qdir()
    try:
        dfd = O._open_dir(q, create=True)
        if dfd is None:
            raise OSError(f"{q} — не папка")
        try:
            O._write_in(dfd, rid + SUFFIX, json.dumps(req, ensure_ascii=False))
            with contextlib.suppress(OSError):
                O._write_in(dfd, rid + ".result.json", json.dumps(
                    {"id": rid, "state": "queued", "kind": "login", "server": args[0], "updated": P.stamp()},
                    ensure_ascii=False, indent=1))
        finally:
            os.close(dfd)
    except OSError as e:
        O.err(O.cant_write("заявку не записать", e))
        return 1
    print(f"заявка {rid}: вход в приложение сервера {args[0]} — её исполнит проход серверов")
    if not wait:
        print(f"итог: pantheon outside status {rid}")
        return 0
    return O.wait_result(q, rid, wait)


if __name__ == "__main__" and sys.argv[1:2] == ["--receive"] and len(sys.argv) == 3 and sys.argv[2].isdigit():
    os._exit(receive_main(int(sys.argv[2])))
