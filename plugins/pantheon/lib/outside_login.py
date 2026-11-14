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
  4. сессия — cookie @supabase/ssr (`sb-<ref>-auth-token`, «base64-» + base64url JSON, куски по 3180 знаков) в файле
     `<rid>.session.json` формата storageState (cookies, origins) с полем script — функция для evaluate_script.
     Файл — 600, в папке заявок окна; старше SESSION_TTL проход его удаляет.
В итоге роли (`<rid>.result.json`), журнале прохода (logs/outside.jsonl) и runs/<rid>.json — только «вошла / не
вошла», причина без значений и путь к файлу сессии. Пароля и почты нет нигде, кроме тела запроса к Supabase; любая
причина отказа проходит через _scrub (значения ключей вырезаются). Токены сессии видит роль — это сессия тестовой
учётной записи с коротким сроком, а не пароль.

Почему не форма /auth: для неё проходу нужен свой браузер, а Supabase Auth — один запрос с публичным ключом.
"""
import base64
import contextlib
import json
import os
import re
import secrets
import ssl
import stat
import time
import urllib.error
import urllib.parse
import urllib.request

P = None   # lib/pantheon.py
O = None   # lib/outside.py

SUFFIX = ".login.json"
SESSION_SUFFIX = ".session.json"
SESSION_TTL = 3 * 3600              # с: файл сессии старше — удалить (сервер живёт не дольше SERVE_MAX)
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


def cookie_script(cookies):
    """Функция для evaluate_script chrome-devtools на странице сервера: ставит cookie и отдаёт их число."""
    data = json.dumps([[c["name"], c["value"]] for c in cookies])
    return ("() => { const cs = " + data + "; for (const [n, v] of cs) document.cookie = "
            "`${n}=${v}; path=/; max-age=34560000; samesite=lax`; return cs.length; }")


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

def _write_private(qdir, name, text):
    """Файл 600 в папке заявок (outside._write_in: временный O_EXCL и rename, ссылка не пишется насквозь) → путь."""
    dfd = O._open_dir(qdir)
    if dfd is None:
        raise OSError(f"{qdir} — не папка")
    try:
        O._write_in(dfd, name, text)
    finally:
        os.close(dfd)
    return os.path.join(qdir, name)


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
    text = json.dumps({"url": origin, "cookies": cookies, "origins": [], "script": cookie_script(cookies)},
                      ensure_ascii=False, indent=1)
    try:
        path = _write_private(qdir, rid + SESSION_SUFFIX, text)
    except OSError as e:
        return fail(f"файл сессии не записать: {type(e).__name__}")
    O.log_event(id=rid, kind="login", window=window, server=sid, ok=True, cookies=len(cookies))
    note = (f"вошла: сессия — {path} (cookie для {origin}). Открой {origin} в chrome-devtools, выполни поле script "
            "файла через evaluate_script и перезагрузи страницу")
    return O.save_result(qdir, rid, {"state": "done", "code": 0, **base, "session": path, "note": note})


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


def drop_old_sessions(t=None):
    """Файлы сессий старше SESSION_TTL — удалить (обычные файлы, не ссылки). → число."""
    t = P.now() if t is None else t
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
                    if stat.S_ISREG(st.st_mode) and t - st.st_mtime > SESSION_TTL:
                        os.unlink(name, dir_fd=dfd)
                        n += 1
        finally:
            os.close(dfd)
    return n


def login_round():
    """Круг прохода серверов: заявки входа, затем уборка старых файлов сессий."""
    for qdir, window, rid, req in _take_requests():
        try:
            handle(qdir, window, rid, req)
        except Exception as e:  # noqa: BLE001 — сбой одной заявки: итог failed, круг идёт; причина — класс без текста
            O.log_event(id=rid, kind="login-error", window=window, why=type(e).__name__)
            O.save_result(qdir, rid, {"state": "failed", "kind": "login",
                                      "why": f"не вошла: сбой прохода: {type(e).__name__}"})
    drop_old_sessions()


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
