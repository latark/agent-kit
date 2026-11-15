"""Проверка «подключено» для HTTP-серверов MCP (metis-1153, вариант А владельца 14.11 11:49).

`project-tools check` раньше говорил только «всё по карте»: сервер в .mcp.json и одобрен. Отвечает ли он — не знал.
Здесь — проверка для серверов с адресом (type "http" или поле url без command):
  1. POST initialize (JSON-RPC 2.0, MCP) — ответ должен быть MCP: result с protocolVersion и capabilities или serverInfo;
  2. POST notifications/initialized и tools/list с Mcp-Session-Id из ответа — список инструментов получен.
Итог по серверу — state:
  ok     подключается: оба ответа MCP, инструментов N;
  auth   не проверен — нужен вход: 401/403 или заголовок WWW-Authenticate (OAuth) — сервер не считается подключённым,
         вход делает владелец в окне (/mcp → Authenticate); сервер с ключом в headers .mcp.json — «нужен ключ»;
  fail   не подключается: сеть, таймаут, не HTTP 200, не MCP, ошибка JSON-RPC — причина в why;
  skip   не проверен: stdio (процесс не запускаем — его запускает Claude Code в окне), не одобрен в настройках проекта,
         не одобрен на этом Mac (нет отпечатка записи от `project-tools apply`), изменён после одобрения (отпечаток не
         совпал), выключен вами, адрес из переменной окружения, старый транспорт SSE, схема не http(s).
Сеть открывает только отпечаток на этом Mac (pins, metis-1153 круг 2): одобрение из общего .claude/settings.json или
enableAllProjectMcpServers приходит с git pull и само по себе адрес из репозитория не трогает.
Сеть — с таймаутом на запрос (TIMEOUT) и на весь проход (BUDGET, и на чтение тела — кусками, срок сверяется между
ними), без ключей владельца: заголовки из .mcp.json, cookie и Authorization не отправляются; перенаправления не
выполняются (3xx — fail); ответ читается не больше MAX_BODY. Любой сбой пробы — fail с именем типа ошибки, без её
текста; проверка не роняет `project-tools check`.
Только stdlib.
"""
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL = "2025-06-18"
TIMEOUT = 8            # секунд на один запрос
BUDGET = 30            # секунд на все серверы проекта
MAX_BODY = 1 << 20
ACCEPT = "application/json, text/event-stream"
CLIENT = {"name": "project-tools", "version": "1"}
CHUNK = 16384


class OutOfTime(Exception):
    """Срок проверки (BUDGET или TIMEOUT запроса) вышел — в том числе посреди чтения тела."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):   # 3xx не выполняем: ответом остаётся сам 3xx
        return None


def read_body(r, end):
    """Тело кусками до MAX_BODY; срок end (monotonic) сверяется между кусками: сервер, который цедит по байту, не
    растянет проверку дальше срока (таймаут сокета — на один recv, а не на всё тело)."""
    out = b""
    while len(out) < MAX_BODY:
        if time.monotonic() > end:
            raise OutOfTime("тело не дочитано к сроку")
        piece = r.read1(min(CHUNK, MAX_BODY - len(out))) if hasattr(r, "read1") else r.read(CHUNK)
        if not piece:
            break
        out += piece
    return out


def http_post(url, body, headers, timeout):
    """POST → (код HTTP, заголовки с именами в нижнем регистре, тело до MAX_BODY байт). Сбой сети — OSError, срок —
    OutOfTime, кривой ответ — http.client.HTTPException."""
    end = time.monotonic() + timeout
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, read_body(r, end)
    except urllib.error.HTTPError as e:
        try:
            data = read_body(e, end)
        except (OSError, OutOfTime, http.client.HTTPException):
            data = b""
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, data


def server_kind(cfg):
    """http — streamable HTTP (type http или url без command), sse — старый транспорт, stdio — процесс."""
    if not isinstance(cfg, dict):
        return "stdio"
    t = str(cfg.get("type") or "").lower()
    if t == "sse":
        return "sse"
    if t in ("http", "streamable-http") or (cfg.get("url") and not cfg.get("command")):
        return "http"
    return "stdio"


def rpc_message(status, headers, data, want_id):
    """Сообщение JSON-RPC с id want_id из ответа: JSON или поток text/event-stream (строки data:). → dict или None."""
    text = data.decode("utf-8", "replace")
    ctype = str(headers.get("content-type") or "").lower()
    chunks = []
    if "text/event-stream" in ctype:
        cur = []
        for line in text.splitlines() + [""]:
            if line.startswith("data:"):
                cur.append(line[5:].lstrip())
            elif not line.strip() and cur:
                chunks.append("\n".join(cur))
                cur = []
    else:
        chunks = [text]
    for c in chunks:
        try:
            msg = json.loads(c)
        except ValueError:
            continue
        for m in msg if isinstance(msg, list) else [msg]:
            if isinstance(m, dict) and m.get("jsonrpc") == "2.0" and m.get("id") == want_id:
                return m
    return None


def _auth(status, headers, keyed):
    if status in (401, 403) or headers.get("www-authenticate"):
        if keyed:
            return {"state": "auth", "why": "не проверен — нужен ключ из headers .mcp.json, ключи владельца проверка не "
                                            "отправляет"}
        return {"state": "auth", "why": "не проверен — нужен вход (OAuth): /mcp в окне → Authenticate; до входа сервер "
                                        "не подключён"}
    return None


def probe(cfg, post=http_post, deadline=None):
    """Проверка одного сервера (см. шапку) → {"state", "why", "tools"}. post — транспорт (тесты подменяют)."""
    kind = server_kind(cfg)
    if kind == "stdio":
        return {"state": "skip", "why": "stdio — процесс не запускаю, его запускает Claude Code в окне (/mcp)"}
    if kind == "sse":
        return {"state": "skip", "why": "старый транспорт SSE — не проверяю, проверка в окне (/mcp)"}
    url = str(cfg.get("url") or "")
    if "${" in url:
        return {"state": "skip", "why": "адрес из переменной окружения — не проверяю"}
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        return {"state": "skip", "why": "адрес не http(s) — не проверяю"}
    keyed = bool(cfg.get("headers"))
    deadline = deadline or time.monotonic() + BUDGET

    def call(body, session, version):
        left = deadline - time.monotonic()
        if left <= 0.5:
            raise OutOfTime("время проверки вышло")
        h = {"Content-Type": "application/json", "Accept": ACCEPT}
        if session:
            h["Mcp-Session-Id"] = session
        if version:
            h["MCP-Protocol-Version"] = version
        return post(url, json.dumps(body).encode(), h, min(TIMEOUT, left))

    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT}}
    try:
        status, headers, data = call(init, None, None)
        bad = _auth(status, headers, keyed)
        if bad:
            return bad
        if status != 200:
            return {"state": "fail", "why": f"не подключается: initialize — HTTP {status}, не ответ MCP"}
        m = rpc_message(status, headers, data, 1)
        res = m.get("result") if m else None
        if m and isinstance(m.get("error"), dict):
            code = m["error"].get("code")   # текст ошибки сервера в вывод не берём: чужой текст агенту — данные
            return {"state": "fail", "why": f"не подключается: initialize — ошибка MCP {code if isinstance(code, int) else '?'}"}
        if not isinstance(res, dict) or not isinstance(res.get("protocolVersion"), str) \
                or not isinstance(res.get("capabilities", res.get("serverInfo")), dict):
            return {"state": "fail", "why": "не подключается: ответ на initialize — не MCP"}
        session, version = headers.get("mcp-session-id"), res["protocolVersion"]
        call({"jsonrpc": "2.0", "method": "notifications/initialized"}, session, version)
        status, headers, data = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session, version)
        bad = _auth(status, headers, keyed)
        if bad:
            return bad
        m = rpc_message(status, headers, data, 2) if status == 200 else None
        tools = (m.get("result") or {}).get("tools") if m and isinstance(m.get("result"), dict) else None
        if not isinstance(tools, list):
            why = f"HTTP {status}" if status != 200 else "ответ не MCP или без списка tools"
            return {"state": "fail", "why": f"не подключается: tools/list — {why}"}
    except OutOfTime:
        return {"state": "fail", "why": "не подключается: время проверки вышло"}
    except Exception as e:  # noqa: BLE001 — любой сбой пробы (OSError, HTTPException, кривой JSON) — fail, не падение
        # текст ошибки в вывод не берём: в нём бывает ответ сервера, а вывод читает агент (только имя типа)
        return {"state": "fail", "why": f"не подключается: {type(e).__name__}"}
    return {"state": "ok", "why": f"подключается: initialize и tools/list ответили, инструментов {len(tools)}",
            "tools": len(tools)}


def approved_names(shared, local, proj, user):
    """Одобренные вами серверы .mcp.json проекта (как их запускает Claude Code) и выключенные: (одобренные или None —
    «все», выключенные). None — enableAllProjectMcpServers в настройках проекта."""
    off = set(proj.get("disabledMcpServers") or [])
    for layer in (shared, local, user, proj):
        off |= set(layer.get("disabledMcpjsonServers") or [])
    if any(layer.get("enableAllProjectMcpServers") is True for layer in (shared, local, proj)):
        return None, off
    on = set()
    for layer in (shared, local, proj):
        on |= set(layer.get("enabledMcpjsonServers") or [])
    return on, off


def check_servers(servers, approved, off, pins, post=http_post):
    """Все серверы .mcp.json → [(имя, kind, итог probe)], по имени. pins — имя → "ok" (отпечаток записи на этом Mac
    совпал), "drift" (не совпал); имени нет — отпечатка нет. Выключенный, не одобренный, без отпечатка или изменённый
    после одобрения HTTP-сервер — skip без сети."""
    deadline = time.monotonic() + BUDGET
    out = []
    for name in sorted(servers):
        cfg = servers[name]
        net = server_kind(cfg) != "stdio"
        if name in off:
            got = {"state": "skip", "why": "выключен вами — не проверяю"}
        elif net and approved is not None and name not in approved:
            got = {"state": "skip", "why": "не одобрен в настройках проекта — адрес не трогаю"}
        elif net and pins.get(name) == "drift":
            got = {"state": "skip", "why": "изменён после одобрения — не проверяю (project-tools check: ⚠ выше)"}
        elif net and pins.get(name) != "ok":
            got = {"state": "skip", "why": "не одобрен на этом Mac — не проверяю (отпечатка нет: project-tools apply)"}
        else:
            try:
                got = probe(cfg, post, deadline)
            except Exception as e:  # noqa: BLE001 — сбой пробы одного сервера не роняет check
                got = {"state": "fail", "why": f"не подключается: {type(e).__name__}"}
        out.append((name, server_kind(cfg), got))
    return out
