#!/usr/bin/env python3
"""Проверка «подключено» HTTP-серверов MCP (lib/mcp_probe.py, metis-1153) и её раздел в `project-tools check`.

Запуск: python3 -I plugins/project-tools/tests/test_mcp_probe.py  (код выхода 0 — все прошли; Python 3.11+)
Проверяет: initialize → notifications/initialized → tools/list с Mcp-Session-Id и версией протокола, ответы JSON и SSE;
не MCP, ошибка JSON-RPC, HTTP 500, нет tools — fail; 401 и WWW-Authenticate — «не проверен — нужен вход», с ключом в
headers — «нужен ключ», и ключи из headers не уходят; stdio, SSE, ${VAR}, не http(s) — без сети; таймаут и сбой сети —
fail с причиной; общий бюджет времени; не одобренный и выключенный сервер — без сети; текст ошибки сервера в вывод не
попадает. Через CLI: раздел «Серверы MCP», --no-net, --json без и с --probe. Живой сервер на 127.0.0.1 — только где
можно открыть порт (CI); в окне роли без сокетов этот случай пишет «пропущено».
"""
import http.client
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
CLI = os.path.join(PLUGIN, "lib", "project_tools.py")
sys.path.insert(0, os.path.join(PLUGIN, "lib"))
import mcp_probe as mp  # noqa: E402

FAILS = []
OKS = []


def check(name, ok, info=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"\n     {info}"))
    (OKS if ok else FAILS).append(name)


INIT_OK = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                                                 "serverInfo": {"name": "x", "version": "1"}}}
TOOLS_OK = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "a"}, {"name": "b"}]}}
JSON = {"content-type": "application/json"}


class Fake:
    """Транспорт для probe: ответы по методу, журнал запросов."""

    def __init__(self, init=None, tools=None, sse=False, session="s-1"):
        self.calls = []
        self.init = init or (200, dict(JSON, **({"mcp-session-id": session} if session else {})), INIT_OK)
        self.tools = tools or (200, JSON, TOOLS_OK)
        self.sse = sse

    def __call__(self, url, body, headers, timeout):
        msg = json.loads(body)
        self.calls.append((url, msg.get("method"), dict(headers), timeout))
        if msg.get("method") == "notifications/initialized":
            return 202, {}, b""
        status, h, payload = self.init if msg.get("method") == "initialize" else self.tools
        if isinstance(payload, (dict, list)):
            if self.sse:
                h = dict(h, **{"content-type": "text/event-stream"})
                payload = ("event: message\nid: 7\ndata: " + json.dumps(payload) + "\n\n").encode()
            else:
                payload = json.dumps(payload).encode()
        return status, h, payload


HTTP = {"type": "http", "url": "https://mcp.example.test/mcp"}


def test_ok_json_and_sse():
    for sse in (False, True):
        f = Fake(sse=sse)
        got = mp.probe(HTTP, f)
        check(f"ответ {'SSE' if sse else 'JSON'}: подключается, инструментов 2",
              got["state"] == "ok" and got["tools"] == 2 and "инструментов 2" in got["why"], got)
        methods = [c[1] for c in f.calls]
        check("порядок: initialize, notifications/initialized, tools/list",
              methods == ["initialize", "notifications/initialized", "tools/list"], methods)
        h = f.calls[2][2]
        check("tools/list несёт Mcp-Session-Id и MCP-Protocol-Version из initialize",
              h.get("Mcp-Session-Id") == "s-1" and h.get("MCP-Protocol-Version") == "2025-03-26", h)
        check("Accept — JSON и event-stream", "text/event-stream" in f.calls[0][2]["Accept"], f.calls[0][2])
        check("таймаут на запрос не больше TIMEOUT", all(0 < c[3] <= mp.TIMEOUT for c in f.calls), f.calls)
    f = Fake(session=None)
    got = mp.probe({"url": "http://127.0.0.1:9/mcp"}, f)
    check("url без type и command — HTTP; без сессии заголовка Mcp-Session-Id нет",
          got["state"] == "ok" and "Mcp-Session-Id" not in f.calls[2][2], (got, f.calls))
    batch = (200, JSON, [{"jsonrpc": "2.0", "method": "notifications/x"}, TOOLS_OK])
    check("ответ-пачка JSON-RPC: берётся сообщение со своим id", mp.probe(HTTP, Fake(tools=batch))["state"] == "ok")


def test_not_mcp():
    for name, fake, want in (
            ("initialize — HTML", Fake(init=(200, {"content-type": "text/html"}, b"<html>hi</html>")),
             "initialize — не MCP"),
            ("initialize без protocolVersion", Fake(init=(200, JSON, {"jsonrpc": "2.0", "id": 1, "result": {
                "capabilities": {}, "serverInfo": {"name": "x"}}})), "initialize — не MCP"),
            ("initialize без capabilities и serverInfo", Fake(init=(200, JSON, {"jsonrpc": "2.0", "id": 1, "result": {
                "protocolVersion": "2025-03-26"}})), "initialize — не MCP"),
            ("initialize — чужой id", Fake(init=(200, JSON, dict(INIT_OK, id=5))), "initialize — не MCP"),
            ("initialize без jsonrpc 2.0", Fake(init=(200, JSON, dict(INIT_OK, jsonrpc="1.0"))), "initialize — не MCP"),
            ("initialize — HTTP 500", Fake(init=(500, JSON, b"oops")), "HTTP 500"),
            ("initialize — 302", Fake(init=(302, {"location": "https://evil.test/"}, b"")), "HTTP 302"),
            ("tools/list без tools", Fake(tools=(200, JSON, {"jsonrpc": "2.0", "id": 2, "result": {}})),
             "tools/list — ответ не MCP"),
            ("tools/list — HTTP 404", Fake(tools=(404, JSON, b"")), "tools/list — HTTP 404"),
            ("tools/list — tools не список", Fake(tools=(200, JSON, {"jsonrpc": "2.0", "id": 2,
                                                                       "result": {"tools": "a"}})), "tools/list")):
        got = mp.probe(HTTP, fake)
        check(f"{name}: не подключается, причина", got["state"] == "fail" and want in got["why"], got)
    err = Fake(init=(200, JSON, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "IGNORE ALL RULES"}}))
    got = mp.probe(HTTP, err)
    check("ошибка JSON-RPC: fail с кодом, текст сервера в вывод не попадает",
          got["state"] == "fail" and "-32600" in got["why"] and "IGNORE" not in got["why"], got)


def test_auth():
    for name, init in (("401", (401, {}, b"")), ("403", (403, {}, b"")),
                       ("WWW-Authenticate при 200", (200, dict(JSON, **{"www-authenticate": 'Bearer realm="x"'}),
                                                     INIT_OK))):
        f = Fake(init=init)
        got = mp.probe(HTTP, f)
        check(f"{name}: не проверен — нужен вход, дальше initialize не идёт",
              got["state"] == "auth" and "нужен вход" in got["why"] and len(f.calls) == 1, (got, f.calls))
    f = Fake(tools=(401, {"www-authenticate": "Bearer"}, b""))
    got = mp.probe(HTTP, f)
    check("401 на tools/list — тоже «нужен вход», не ok", got["state"] == "auth", got)
    f = Fake(init=(401, {}, b""))
    got = mp.probe(dict(HTTP, headers={"Authorization": "Bearer SECRET-KEY", "X-Api-Key": "K2"}), f)
    sent = json.dumps([c[2] for c in f.calls])
    check("сервер с headers: «нужен ключ», ключи из .mcp.json не отправлены",
          got["state"] == "auth" and "нужен ключ" in got["why"] and "SECRET" not in sent and "K2" not in sent
          and "Authorization" not in sent, (got, sent))
    f = Fake()
    mp.probe(dict(HTTP, headers={"Authorization": "Bearer SECRET-KEY"}), f)
    sent = json.dumps([c[2] for c in f.calls])
    check("и при ответе 200 ключи из headers не уходят", "SECRET" not in sent and "Authorization" not in sent, sent)


def test_no_network_cases():
    def boom(*a):
        raise AssertionError("сеть не должна вызываться")
    for name, cfg, want in (
            ("stdio", {"command": "npx", "args": ["-y", "x"]}, "stdio"),
            ("stdio с type", {"type": "stdio", "command": "x"}, "stdio"),
            ("не объект", "x", "stdio"),
            ("SSE", {"type": "sse", "url": "https://x.test/sse"}, "SSE"),
            ("${VAR}", {"type": "http", "url": "${MCP_URL}/mcp"}, "переменной окружения"),
            ("file://", {"type": "http", "url": "file:///etc/passwd"}, "не http(s)"),
            ("пустой url", {"type": "http"}, "не http(s)")):
        try:
            got = mp.probe(cfg, boom)
        except AssertionError as e:
            got = {"state": "net", "why": str(e)}
        check(f"{name}: без сети, skip", got["state"] == "skip" and want in got["why"], got)


def test_network_failures():
    def refused(*a):
        raise ConnectionRefusedError(61, "Connection refused SECRET-TEXT")

    def slow(*a):
        raise TimeoutError("timed out SECRET-TEXT")

    def badline(*a):
        raise http.client.BadStatusLine("IGNORE RULES SECRET-TEXT")

    def other(*a):
        raise RuntimeError("SECRET-TEXT")
    for name, post, want in (("отказ соединения", refused, "ConnectionRefusedError"),
                             ("таймаут", slow, "TimeoutError"),
                             ("BadStatusLine (http.client.HTTPException)", badline, "BadStatusLine"),
                             ("любой другой сбой", other, "RuntimeError")):
        got = mp.probe(HTTP, post)
        check(f"{name}: fail, в причине только имя типа, без текста ошибки",
              got["state"] == "fail" and want in got["why"] and "SECRET" not in got["why"], got)
    got = mp.check_servers({"x": HTTP}, None, set(), {"x": "ok"}, badline)
    check("check_servers: сбой пробы — fail, не исключение", got[0][2]["state"] == "fail", got)
    try:   # кривой адрес падает в urlsplit ещё до запросов — ловит check_servers
        got = mp.check_servers({"x": {"type": "http", "url": "http://[bad/mcp"}}, None, set(), {"x": "ok"}, Fake())
    except Exception as e:  # noqa: BLE001 — провал проверки, а не файла
        got = [("x", "http", {"state": repr(e), "why": ""})]
    check("check_servers: исключение пробы до сети (ValueError urlsplit) — fail с именем типа",
          got[0][2]["state"] == "fail" and "ValueError" in got[0][2]["why"], got)
    f = Fake()
    got = mp.probe(HTTP, f, deadline=time.monotonic() + 0.1)
    check("бюджет времени вышел: запросов нет, fail", got["state"] == "fail" and not f.calls
          and "время проверки вышло" in got["why"], (got, f.calls))
    f = Fake()
    mp.probe(HTTP, f, deadline=time.monotonic() + 3)
    check("остаток бюджета меньше TIMEOUT — таймаут запроса урезан", all(c[3] <= 3 for c in f.calls), f.calls)


def test_check_servers_approval():
    servers = {"web": HTTP, "off": dict(HTTP, url="https://off.test/"), "new": dict(HTTP, url="https://new.test/"),
               "local": {"command": "node", "args": ["x"]}}
    pins = {"web": "ok", "off": "ok", "new": "ok"}
    f = Fake()
    out = {n: (k, g) for n, k, g in mp.check_servers(servers, {"web", "off"}, {"off"}, pins, f)}
    urls = {c[0] for c in f.calls}
    check("одобренный — проверен по сети", out["web"][1]["state"] == "ok" and HTTP["url"] in urls, out)
    check("выключенный — skip без сети", out["off"][1]["state"] == "skip" and "выключен" in out["off"][1]["why"]
          and "https://off.test/" not in urls, out)
    check("не одобренный — skip без сети, адрес не тронут", out["new"][1]["state"] == "skip"
          and "не одобрен" in out["new"][1]["why"] and "https://new.test/" not in urls, out)
    check("stdio — skip «не запускаю»", out["local"] == ("stdio", out["local"][1]) and "stdio" in out["local"][1]["why"])
    f = Fake()
    out = {n: g for n, _, g in mp.check_servers(servers, None, set(), pins, f)}
    check("approved None (enableAll) — проверены все HTTP с отпечатком", out["new"]["state"] == "ok"
          and out["off"]["state"] == "ok")
    f = Fake()
    out = {n: g for n, _, g in mp.check_servers(servers, None, set(), {"web": "drift"}, f)}
    check("enableAll без отпечатков на этом Mac — сети нет: «не одобрен на этом Mac», изменённый — «изменён»",
          not f.calls and out["new"]["state"] == "skip" and "не одобрен на этом Mac" in out["new"]["why"]
          and out["web"]["state"] == "skip" and "изменён после одобрения" in out["web"]["why"], (out, f.calls))
    on, off = mp.approved_names({"enabledMcpjsonServers": ["a"]}, {"enabledMcpjsonServers": ["b"],
                                                                   "disabledMcpjsonServers": ["c"]},
                                {"disabledMcpServers": ["d"], "enabledMcpjsonServers": ["e"]},
                                {"disabledMcpjsonServers": ["u"]})
    check("approved_names: одобрения из settings, settings.local и ~/.claude.json проекта, отказы отовсюду",
          on == {"a", "b", "e"} and off == {"c", "d", "u"}, (on, off))
    on, _ = mp.approved_names({}, {"enableAllProjectMcpServers": True}, {}, {"enableAllProjectMcpServers": True})
    check("enableAllProjectMcpServers в проекте — все", on is None, on)
    on, _ = mp.approved_names({}, {}, {}, {"enableAllProjectMcpServers": True})
    check("enableAll только в ~/.claude/settings.json проверку не открывает", on == set(), on)


# --- CLI ---------------------------------------------------------------------------------------------------------
def fp(cfg):
    """Отпечаток записи так же, как project_tools.fingerprint (сверка — тест ниже)."""
    import hashlib
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def make_project(servers, settings, pins=None):
    """pins — имя → запись, чей отпечаток «одобрен на этом Mac» (approved.json, как пишет apply)."""
    home = os.path.realpath(tempfile.mkdtemp(prefix="mcp-probe-test-"))
    os.makedirs(os.path.join(home, ".claude"))
    root = os.path.join(home, "projects", "p")
    os.makedirs(os.path.join(root, ".claude"))
    with open(os.path.join(root, ".mcp.json"), "w") as fh:
        json.dump({"mcpServers": servers}, fh)
    with open(os.path.join(root, ".claude", "settings.json"), "w") as fh:
        json.dump(settings, fh)
    if pins:
        d = os.path.join(home, ".local", "state", "pantheon", "project-tools")
        os.makedirs(d)
        with open(os.path.join(d, "approved.json"), "w") as fh:
            json.dump({root: {n: fp(c) for n, c in pins.items()}}, fh)
    return home, root


def cli(home, root, *args):
    env = {"PATH": os.environ["PATH"], "HOME": home}
    return subprocess.run([sys.executable, "-I", CLI, "check", "--dir", root, *args], env=env, capture_output=True,
                          text=True, timeout=60)


def test_cli_section():
    home, root = make_project({"remote": {"type": "http", "url": "https://new.test/mcp"},
                               "local": {"command": "node", "args": ["x"]}}, {})
    r = cli(home, root)
    check("check: раздел «Серверы MCP», не одобренный HTTP — без сети, stdio — не запускаю",
          "Серверы MCP" in r.stdout and "remote (http): не одобрен" in r.stdout and "local (stdio): stdio" in r.stdout,
          f"{r.returncode} {r.stdout!r} {r.stderr!r}")
    r = cli(home, root, "--no-net")
    check("check --no-net: раздела нет", r.returncode in (0, 3) and "Серверы MCP" not in r.stdout, r.stdout)
    r = cli(home, root, "--json")
    check("check --json без --probe: поля servers нет", r.returncode == 0 and "servers" not in json.loads(r.stdout),
          r.stdout)
    r = cli(home, root, "--json", "--probe")
    got = {s["name"]: s for s in json.loads(r.stdout).get("servers", [])} if r.returncode == 0 else {}
    check("check --json --probe: servers с состоянием", got.get("remote", {}).get("state") == "skip"
          and got.get("local", {}).get("kind") == "stdio", r.stdout)
    r = cli(home, root, "--json", "--probe", "--no-net")
    check("--no-net сильнее --probe", r.returncode == 0 and "servers" not in json.loads(r.stdout), r.stdout)
    home, root = make_project({}, {})
    r = cli(home, root)
    check("пустой .mcp.json — раздела нет", "Серверы MCP" not in r.stdout, r.stdout)
    sys.path.insert(0, os.path.join(PLUGIN, "lib"))
    import project_tools
    cfg = {"type": "http", "url": "https://x.test/mcp"}
    check("fp теста совпадает с project_tools.fingerprint", fp(cfg) == project_tools.fingerprint(cfg))
    odd = "bad\x1b[31mname"
    home, root = make_project({odd: {"type": "http", "url": "https://x.test/mcp"}}, {})
    r = cli(home, root, "--json", "--probe")
    check("--json: имя сервера через safe_name (управляющих символов нет)",
          r.returncode == 0 and "\x1b" not in r.stdout and "\\u001b" not in r.stdout
          and "недопустимыми" in r.stdout, r.stdout)


class Handler(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.seen.append((self.path, body.get("method"), dict(self.headers)))
        if self.path == "/redirect":
            self.send_response(302)   # 302 urllib сам перевёл бы в GET на Location — проверка, что не идём
            self.send_header("Location", "/mcp")
            self.end_headers()
            return
        if self.path == "/slow":   # тело по байту раз в 0.2 с: Content-Length большой, сокет не молчит
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "100000")
            self.end_headers()
            for _ in range(200):
                try:
                    self.wfile.write(b" ")
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(0.2)
            return
        if self.path == "/oauth":
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer resource_metadata="http://x/.well-known"')
            self.end_headers()
            return
        if body.get("method") == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if body.get("method") == "initialize":
            data, sse = INIT_OK, False
        elif self.headers.get("Mcp-Session-Id") == "live-1":
            data, sse = TOOLS_OK, True
        else:
            self.send_response(400)
            self.end_headers()
            return
        raw = (f"data: {json.dumps(data)}\n\n" if sse else json.dumps(data)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if sse else "application/json")
        self.send_header("Mcp-Session-Id", "live-1")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_live_server():
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except (OSError, socket.error) as e:
        print(f"пропущено: живой сервер — порт не открыть ({e}); идёт в CI")
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        got = mp.probe({"type": "http", "url": base + "/mcp"})
        check("живой сервер: http_post, JSON и SSE, сессия — подключается", got["state"] == "ok" and got["tools"] == 2,
              got)
        Handler.seen.clear()
        got = mp.probe({"type": "http", "url": base + "/redirect"})
        check("302 не выполняется: fail, на /mcp запросов нет",
              got["state"] == "fail" and "302" in got["why"] and all(s[0] == "/redirect" for s in Handler.seen),
              (got, Handler.seen))
        got = mp.probe({"type": "http", "url": base + "/oauth", "headers": {}})
        check("живой 401 + WWW-Authenticate: нужен вход", got["state"] == "auth" and "нужен вход" in got["why"], got)
        t0 = time.monotonic()
        got = mp.probe({"type": "http", "url": base + "/slow"}, deadline=time.monotonic() + 2)
        took = time.monotonic() - t0
        check("медленное тело: срок сверяется между кусками — fail не позже бюджета",
              got["state"] == "fail" and "время проверки вышло" in got["why"] and took < 3.5, (got, took))
        live = {"type": "http", "url": base + "/mcp"}
        home, root = make_project({"live": live}, {"enabledMcpjsonServers": ["live"]}, pins={"live": live})
        r = cli(home, root)
        check("check: одобренный живой сервер с отпечатком — «+ live (http): подключается»",
              "+ live (http): подключается" in r.stdout, f"{r.stdout!r} {r.stderr!r}")
        Handler.seen.clear()
        home, root = make_project({"live": live}, {"enabledMcpjsonServers": ["live"]},
                                  pins={"live": {"type": "http", "url": "https://old.test/mcp"}})
        r = cli(home, root)
        check("url сменили после одобрения (отпечаток не совпал): к местному серверу запросов нет",
              "live (http): изменён после одобрения" in r.stdout and not Handler.seen, (r.stdout, Handler.seen))
        home, root = make_project({"live": live}, {"enableAllProjectMcpServers": True,
                                                   "enabledMcpjsonServers": ["live"]})
        r = cli(home, root)
        check("запись без отпечатка (одобрена только общим settings.json): запросов нет",
              "live (http): не одобрен на этом Mac" in r.stdout and not Handler.seen, (r.stdout, Handler.seen))
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            try:
                v()
            except Exception as e:  # noqa: BLE001 — провал случая, а не всего файла
                check(f"{k}: исключение", False, repr(e))
    # итог в формате раннера (TEST_SUMMARY run-tests.py)
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else f'{len(OKS)} из {len(OKS)} прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
