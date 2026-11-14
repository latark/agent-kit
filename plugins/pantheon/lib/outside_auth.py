"""`pantheon outside auth <адрес> [--wait С]` — ссылка входа MCP (OAuth) из окна роли открывается в браузере
владельца сама (metis-1127).

Зачем. Окну роли нужен вход владельца в MCP-сервер (Supabase и др.): Claude Code окна печатает ссылку OAuth со своим
слушателем на 127.0.0.1 и state. Раньше она шла через Зевса текстом, владелец копировал её руками, а после перезапуска
окна ссылка уже не работала. Браузер окно само не откроет: песочница, и браузер владельца окну закрыт.

Как. Тот же канал, что у `outside serve` и `outside login`: заявка `<rid>.auth.json` ложится в папку заявок окна
(outside.own_qdir), исполняет её проход серверов (outside.serve_round → auth_round) вне окна; плановый проход зовёт его, пока
заявки есть (outside.pending_serve → pending). Проход:
  1. адрес — по белому списку ALLOWED (по умолчанию только вход OAuth Supabase: https://api.supabase.com/v1/oauth/
     authorize): только https, хост и начало пути из списка, без имени пользователя, порта кроме 443, «%», «\\»,
     сегментов «.» и «..», только печатные ASCII. Без фрагмента «#»; запрос — parse_qs (strict), каждый параметр один
     раз, response_type=code, client_id из [A-Za-z0-9._-], redirect_uri — только слушатель окна на этом Mac:
     http://localhost|127.0.0.1:<порт>/callback (REDIRECT_HOSTS, REDIRECT_PATHS) без имени пользователя, «?» и «#»:
     иначе код доступа к аккаунту владельца после «Authorize» ушёл бы на чужой адрес. Не так — отказ, ничего не
     открывается. Уведомление и вывод называют client_id (до 40 знаков) и хост redirect_uri;
  2. заявка старше AUTH_TTL (10 мин) — гаснет: ссылка OAuth к этому времени уже устарела;
  3. окно, подавшее заявку (имя — по месту папки заявок, а не из текста заявки), живо — culprits.live_windows по
     `claude agents` и ps; окна нет — заявка гаснет (state stopped), ничего не открывается; список живых окон не
     прочесть — отказ «подай заново». Очередь STATE (ваши сессии вне окна) окна не имеет — проверки нет;
  4. не больше RATE_MAX открытий на окно за RATE_WINDOW: агент в цикле не засыпает браузер владельца вкладками;
  5. `open <адрес>` (OPEN, список аргументов, без shell и без ввода пользователя) — основной браузер владельца, и
     уведомление «окно X просит вход в Y».
В итоге (`<rid>.result.json`, runs/<rid>.json) и журнале прохода (logs/outside.jsonl) — только хост и client_id: адрес с
state и code_challenge туда не пишется (runs/ читают окна).

Код выхода команды: 0 — страница открыта, 1 — отказ или окно закрыто (причина последней строкой), 2 — неверный вызов
или адрес не из белого списка (проверка ещё в окне), 75 — итога за --wait нет (pantheon outside status ID).
"""
import contextlib
import json
import os
import re
import secrets
import subprocess
import time
import urllib.parse

P = None   # lib/pantheon.py
O = None   # lib/outside.py

SUFFIX = ".auth.json"
# белый список входов OAuth: хост → (служба для уведомления, начала пути). Только Supabase (решение задачи metis-1127);
# новый вход — строкой сюда с задачей
ALLOWED = {"api.supabase.com": ("Supabase", ("/v1/oauth/authorize",))}
URL_MAX = 8192
URL_RE = re.compile(r"[\x21-\x7e]+")   # печатные ASCII без пробела
# redirect_uri — слушатель Claude Code окна: http://localhost:<порт>/callback (так его строит Claude Code для MCP OAuth)
REDIRECT_HOSTS = ("localhost", "127.0.0.1")
REDIRECT_PATHS = ("/callback",)
CLIENT_RE = re.compile(r"[A-Za-z0-9._-]+")
CLIENT_SHOW = 40                       # знаков client_id в уведомлении и выводе
AUTH_TTL = 10 * 60                     # с: заявка старше — гаснет (ссылка OAuth уже не годится)
RATE_MAX, RATE_WINDOW = 3, 10 * 60     # открытий на окно за окно времени, с
OPEN = "/usr/bin/open"                 # тест подменяет заглушкой
OPEN_TIMEOUT = 15                      # с
WAIT_DEFAULT = 120                     # с: проход серверов зовёт плановый проход раз в минуту
USAGE = "pantheon outside auth <адрес https://api.supabase.com/v1/oauth/authorize?…> [--wait С]"


def set_core(p, o):
    global P, O
    P, O = p, o


def check_redirect(raw):
    """redirect_uri ссылки — слушатель Claude Code окна на этом Mac: http, хост REDIRECT_HOSTS, порт числом, путь из
    REDIRECT_PATHS, без имени пользователя, запроса и фрагмента → (хост, None) или (None, причина). Иначе код доступа к
    аккаунту владельца после «Authorize» уйдёт на чужой адрес."""
    if "#" in raw or "?" in raw:   # прочие знаки (пробел, «\», не ASCII) портят порт, хост или точный путь ниже
        return None, "redirect_uri — без «#» и «?»"
    try:
        r = urllib.parse.urlsplit(raw)
        port = r.port
    except ValueError:
        return None, "redirect_uri не разобрать"
    if r.scheme != "http" or "@" in r.netloc or (r.hostname or "") not in REDIRECT_HOSTS or port is None:
        return None, f"redirect_uri — только http://{' или '.join(REDIRECT_HOSTS)}:<порт> (слушатель окна на этом Mac)"
    if r.path not in REDIRECT_PATHS:
        return None, f"путь redirect_uri — не {', '.join(REDIRECT_PATHS)}"
    return r.hostname, None


def check_query(query):
    """Запрос ссылки OAuth: каждый параметр один раз, response_type=code, client_id из CLIENT_RE, redirect_uri по
    check_redirect → ({client, redirect}, None) или (None, причина)."""
    try:
        q = urllib.parse.parse_qs(query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None, "запрос адреса не разобрать"
    dup = sorted(k for k, v in q.items() if len(v) != 1)
    if dup:
        return None, f"параметр адреса повторён: {', '.join(dup)[:80]}"
    one = {k: v[0] for k, v in q.items()}
    if one.get("response_type") != "code":
        return None, "в адресе нет response_type=code"
    client = one.get("client_id")
    if not CLIENT_RE.fullmatch(client or ""):
        return None, "client_id нет или он не из [A-Za-z0-9._-]"
    if "redirect_uri" not in one:
        return None, "в адресе нет redirect_uri"
    rhost, why = check_redirect(one["redirect_uri"])
    if why:
        return None, why
    return {"client": client[:CLIENT_SHOW], "redirect": rhost}, None


def check_url(url):
    """Адрес входа OAuth из белого списка → ({host, client, redirect}, None) или (None, причина)."""
    if not isinstance(url, str) or not url or len(url) > URL_MAX:
        return None, f"адрес пустой или длиннее {URL_MAX} знаков"
    if not URL_RE.fullmatch(url) or "\\" in url:
        return None, "адрес — только печатные ASCII без пробелов и «\\»"
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError:
        return None, "адрес не разобрать"
    if u.scheme != "https":
        return None, "адрес входа — только https"
    if "@" in u.netloc or port not in (None, 443):
        return None, "в адресе имя пользователя или чужой порт"
    host = (u.hostname or "").lower()
    if host not in ALLOWED:
        return None, f"хост {host or '—'} не в белом списке входов ({', '.join(sorted(ALLOWED))})"
    segs = u.path.split("/")
    if "%" in u.path or "." in segs or ".." in segs \
            or not any(u.path == p or u.path.startswith(p + "/") for p in ALLOWED[host][1]):
        return None, f"путь адреса — не вход OAuth {ALLOWED[host][0]} ({', '.join(ALLOWED[host][1])})"
    if "#" in url:
        return None, "в адресе фрагмент «#»"
    info, why = check_query(u.query)
    if why:
        return None, why
    return {"host": host, **info}, None


def check(req, rid):
    if not isinstance(req, dict) or req.get("v") != 1 or req.get("id") != rid or req.get("kind") != "auth":
        return "заявка входа MCP не в формате (v1, kind auth, id = имя файла)"
    return check_url(req.get("url"))[1]


# --- проход серверов -----------------------------------------------------------------------------------------------

def live_windows():
    """Имена живых окон песочницы (culprits.live_windows: `claude agents` и ps) или None — не прочитать."""
    C = P.culprits_mod()
    raw, agents = C.ps_all(), C.agents_strict()
    if raw is None or not isinstance(agents, list):
        return None
    return C.live_windows(C.context(agents), {q["pid"]: q for q in raw})


def open_url(url):
    """`open <адрес>` вне окна: список аргументов, без shell → None или причина (без адреса)."""
    try:
        r = subprocess.run([OPEN, url], stdin=subprocess.DEVNULL, capture_output=True, timeout=OPEN_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return f"open не запустился: {type(e).__name__}"
    return None if r.returncode == 0 else f"open вернул код {r.returncode}"


def rate_path():
    return O.root("auth-opened.json")


def rate_ok(window, now):
    """Открытий этим окном за RATE_WINDOW меньше RATE_MAX → True и отметка; иначе False."""
    data = P.read_json(rate_path(), {})
    data = data if isinstance(data, dict) else {}
    key = window or "-"
    old = data.get(key)
    seen = [t for t in (old if isinstance(old, list) else []) if isinstance(t, (int, float)) and now - t < RATE_WINDOW]
    if len(seen) >= RATE_MAX:
        return False
    data[key] = seen + [now]
    os.makedirs(O.root(), mode=0o700, exist_ok=True)
    P.write_json(rate_path(), {k: v for k, v in data.items() if v})
    return True


def handle(qdir, window, rid, req, alive):
    """Заявка rid из папки qdir окна window → итог done (страница открыта), stopped (окно закрыто) или failed.
    alive — множество живых окон, None — не прочитано."""
    who = window or "ваша сессия"
    info = (check_url(req.get("url"))[0] if isinstance(req, dict) else None) or {}
    host = info.get("host")

    def end(state, why):
        O.log_event(id=rid, kind="auth", window=window, host=host, ok=False, why=why)
        return O.save_result(qdir, rid, {"state": state, "kind": "auth", **({"host": host} if host else {}),
                                         "why": "не открыта: " + why})

    why = check(req, rid)
    if why:
        return end("failed", why)
    age = P.now() - (O._epoch(req) or P.now())
    if age > AUTH_TTL:
        return end("failed", f"заявка пролежала {int(age // 60)} мин — ссылка входа устарела, подай новую")
    if window is not None:
        if alive is None:
            return end("failed", "список живых окон не прочитан — подай заново")
        if window not in alive:
            return end("stopped", f"окно {window} закрыто — заявка погашена, его ссылка входа уже не работает")
    if not rate_ok(window, P.now()):
        return end("failed", f"больше {RATE_MAX} входов за {RATE_WINDOW // 60} мин из окна {who} — подожди")
    service = ALLOWED[host][0]
    what = f"клиент {info['client']}, ответ на {info['redirect']}"
    why = open_url(req["url"])
    if why:
        return end("failed", why)
    O.log_event(id=rid, kind="auth", window=window, host=host, client=info["client"], ok=True)
    with contextlib.suppress(Exception):   # уведомление не главное: страница уже открыта
        P.notify(f"Окно {who} просит вход в {service} ({what}): страница входа открыта в браузере — нажмите "
                 "Authorize, если ждёте этот вход", title="Пантеон · вход MCP", group=f"auth-{window or 'own'}")
    return O.save_result(qdir, rid, {"state": "done", "code": 0, "kind": "auth", "host": host,
                                     "client": info["client"],
                                     "note": f"страница входа {service} ({what}) открыта в браузере владельца — ждём его "
                                             "«Authorize»; после входа проверь сервер в /mcp"})


def _take_requests():
    """[(qdir, окно, rid, заявка)] — заявки входа MCP во всех папках заявок, снятые с диска."""
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
                if O._take_in(dfd, name):   # иначе снял другой проход
                    out.append((qdir, window, rid, O._parse(text)))
        finally:
            os.close(dfd)
    return out


def pending():
    """Плановому проходу: в папках заявок есть заявка входа MCP."""
    for qdir, _ in O.queue_dirs():
        with contextlib.suppress(OSError):
            if any(n.endswith(SUFFIX) for n in os.listdir(qdir)):
                return True
    return False


def auth_round():
    """Круг прохода серверов: заявки входа MCP. Живые окна читаются один раз на круг и только при заявке из окна."""
    todo = _take_requests()
    try:   # сбой чтения окон не роняет проход серверов (он же сторож серверов): заявки окон — failed
        alive = live_windows() if any(w is not None for _, w, _, _ in todo) else set()
    except Exception as e:  # noqa: BLE001
        O.log_event(kind="auth-error", why=f"живые окна: {type(e).__name__}")
        alive = None
    for qdir, window, rid, req in todo:
        try:
            handle(qdir, window, rid, req, alive)
        except Exception as e:  # noqa: BLE001 — сбой одной заявки: итог failed, круг идёт; причина — класс без текста
            O.log_event(id=rid, kind="auth-error", window=window, why=type(e).__name__)
            O.save_result(qdir, rid, {"state": "failed", "kind": "auth",
                                      "why": f"не открыта: сбой прохода: {type(e).__name__}"})


# --- команда роли --------------------------------------------------------------------------------------------------

def cmd_auth(args):
    f = O._flags(args[1:], {"--wait"}) if args else None
    if f is None:
        O.err(f"pantheon outside: {USAGE}")
        return 2
    info, why = check_url(args[0])
    if why:
        O.err(f"pantheon outside auth: {why} — не открываю")
        return 2
    try:
        wait = max(0, min(int(f.get("--wait", WAIT_DEFAULT)), O.WAIT_MAX))
    except ValueError:
        O.err("pantheon outside: --wait — целое число")
        return 2
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    req = {"v": 1, "id": rid, "kind": "auth", "url": args[0], "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "by": " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "").split())[:40]}
    q = O.own_qdir()
    try:
        dfd = O._open_dir(q, create=True)
        if dfd is None:
            raise OSError(f"{q} — не папка")
        try:
            O._write_in(dfd, rid + SUFFIX, json.dumps(req, ensure_ascii=False))
            with contextlib.suppress(OSError):
                O._write_in(dfd, rid + ".result.json", json.dumps(
                    {"id": rid, "state": "queued", "kind": "auth", "host": info["host"], "updated": P.stamp()},
                    ensure_ascii=False, indent=1))
        finally:
            os.close(dfd)
    except OSError as e:
        O.err(O.cant_write("заявку не записать", e))
        return 1
    print(f"заявка {rid}: вход в {ALLOWED[info['host']][0]} (клиент {info['client']}, ответ на {info['redirect']}) — "
          "страницу откроет в браузере владельца проход серверов")
    if not wait:
        print(f"итог: pantheon outside status {rid}")
        return 0
    return O.wait_result(q, rid, wait)
