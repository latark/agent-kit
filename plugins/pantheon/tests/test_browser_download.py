#!/usr/bin/env python3
"""`pantheon browser download` (lib/browser.py, metis-0830): файл через браузер владельца в inbox направления задачи.

Запуск: python3.14 -I plugins/pantheon/tests/test_browser_download.py  (код выхода 0 — все прошли)
Всё во временных папках (HOME, PANTHEON_HOME, PANTHEON_STATE подменены). Демон — подделка на месте transport(): /open
ведёт вкладку, а свой JS прохода (DL_START_JS, DL_CHUNK_JS, DL_DROP_JS) выполняет настоящий node с заглушками
fetch, Cache Storage и FileReader — так проверяется и сам JS, а не только Python. Нет node — строка «пропущено».
Проверяется:
- карантин: метка com.apple.quarantine на файле (macOS), не поставилась — сбой и файла нет; .dmg, .app, .command,
  .sh и прочее из DL_EXEC_EXT — с хвостом .download;
- путь: файл в <направление задачи>/inbox/<сайт или --to>/, байт в байт, права 0644 (без исполняемого бита), sha256
  в итоге, имя в .gitignore папки; вкладка — своя (session окна), переход на главную сайта, /cmd не зовётся, тело
  в кэше сайта удалено; недокачанное — вне inbox и убрано;
- согласие: сайт не из списка без «да» по задаче — отказ без /open; «да» владельца по задаче — можно; файл с чужого
  сайта (редирект) — отказ;
- отказы и сбои без мусора: больше предела (по заголовку и по потоку), text/html, 404, ошибка fetch, главная увела на
  другой адрес, обрезанный кусок, неверная sha256, время вышло — в inbox ничего, новая папка убрана, about:blank;
- имя: Content-Disposition (filename*, UTF-8 в filename), ../, скрытое, длинное; тот же файл — не дублируется, другой
  с тем же именем — «(2)»; ссылка вместо папки — сбой без записи; --to и --task — проверка вызова.
"""
import atexit
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402,F401  CLI pantheon — только на Python 3.11+

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="browser-dl-test-"))
atexit.register(shutil.rmtree, ROOT, True)
HOME, PAN, STATE = (os.path.join(ROOT, d) for d in ("home", "pantheon", "state"))
for d in (HOME, PAN, STATE, os.path.join(STATE, "owner-log")):
    os.makedirs(d, exist_ok=True)
for k in list(os.environ):
    if k.startswith(("PANTHEON_", "CLAUDE_CODE_", "XDG_")) or k == "CLAUDECODE":
        del os.environ[k]
NOTIFY = os.path.join(ROOT, "notify.log")
os.environ.update({"HOME": HOME, "PANTHEON_HOME": PAN, "PANTHEON_STATE": STATE, "PANTHEON_NOTIFY_LOG": NOTIFY,
                   "PANTHEON_TEST": "1"})
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)
import pantheon as P  # noqa: E402

B = P.browser_mod()
TOKEN = "cd" * 32
os.makedirs(os.path.join(HOME, ".config", "cdp-daemon"))
with open(os.path.join(HOME, ".config", "cdp-daemon", "token"), "w") as fh:
    fh.write(TOKEN + "\n")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


NODE = shutil.which("node")
if not NODE:
    print("пропущено: нужен node — свой JS скачивания выполняется в нём")
    print("\n0/0 прошли")
    sys.exit(0)

# --- направление и задача ------------------------------------------------------------------------------------------
DIR = "athena-shop"
TASKS = os.path.join(PAN, "directions", DIR, "tasks")
os.makedirs(TASKS)
os.makedirs(os.path.join(PAN, "directions", DIR, "inbox"))
for tid in ("athena-0205", "athena-0300"):
    with open(os.path.join(TASKS, tid + ".md"), "w", encoding="utf-8") as fh:
        fh.write(f"---\ntype: task\nid: {tid}\ntitle: \"Сделки\"\nstatus: doing\nproject: Shop\ndirection: {DIR}\n"
                 "created: 2026-11-01\nupdated: 2026-11-05T10:00:00\nschema_version: 1\n---\n\n# Сделки\n")
INBOX = os.path.join(PAN, "directions", DIR, "inbox")

# --- node: исполнитель своего JS прохода ---------------------------------------------------------------------------
DRIVER = r"""
const readline = require('readline');
const { resolveObjectURL } = require('buffer');
const FILES = {}, store = new Map(), fetches = [];
globalThis.self = globalThis;
globalThis.isSecureContext = true;
globalThis.location = { origin: 'about:blank' };
globalThis.FileReader = class {
  readAsDataURL(b) {
    b.arrayBuffer().then(ab => { this.result = 'data:application/octet-stream;base64,' + Buffer.from(ab).toString('base64'); this.onload(); },
                         e => { this.error = e; this.onerror(); });
  }
};
let cachesOn = true;
const cachesApi = {
  open: async n => ({
    put: async (k, r) => { store.set(n + '|' + k, await r.blob()); },
    match: async k => store.has(n + '|' + k) ? new Response(store.get(n + '|' + k)) : undefined }),
  delete: async n => { let d = false; for (const k of [...store.keys()]) if (k.startsWith(n + '|')) { store.delete(k); d = true; } return d; },
};
Object.defineProperty(globalThis, 'caches', { get: () => cachesOn ? cachesApi : undefined, configurable: true });
const blobs = new Set();
const origCreate = URL.createObjectURL, origRevoke = URL.revokeObjectURL;
URL.createObjectURL = b => { const u = origCreate(b); blobs.add(u); return u; };
URL.revokeObjectURL = u => { blobs.delete(u); origRevoke(u); };
globalThis.fetch = async (u, o) => {
  if (u.startsWith('blob:')) { const b = resolveObjectURL(u); if (!b) throw new TypeError('Failed to fetch'); return new Response(b); }
  fetches.push({ url: u, credentials: o && o.credentials });
  const f = FILES[u];
  if (!f) throw new TypeError('Failed to fetch');
  const body = Buffer.from(f.b64, 'base64');
  let i = 0;
  const stream = new ReadableStream({ pull(c) {
    if (i >= body.length) return c.close();
    c.enqueue(new Uint8Array(body.subarray(i, i + 65536))); i += 65536; } });
  const headers = { 'content-type': f.type || 'application/zip' };
  if (f.disp) headers['content-disposition'] = f.disp;
  if (f.length !== null) headers['content-length'] = String(f.length === undefined ? body.length : f.length);
  const r = new Response(stream, { status: f.status || 200, headers });
  Object.defineProperty(r, 'url', { value: f.final || u });
  return r;
};
const rl = readline.createInterface({ input: process.stdin });
rl.on('line', async line => {
  const m = JSON.parse(line);
  let out;
  try {
    if (m.cmd === 'files') { Object.assign(FILES, m.files); out = { ok: true }; }
    else if (m.cmd === 'origin') { globalThis.location = { origin: m.origin }; out = { ok: true }; }
    else if (m.cmd === 'secure') { globalThis.isSecureContext = m.on; cachesOn = m.on; out = { ok: true }; }
    else if (m.cmd === 'state') { out = { store: [...store.keys()], blobs: [...blobs], fetches }; }
    else { const v = await (0, eval)(m.expr); out = { value: v === undefined ? null : v }; }
  } catch (e) { out = { error: String(e) }; }
  process.stdout.write(JSON.stringify(out) + '\n');
});
"""
DRIVER_JS = os.path.join(ROOT, "driver.cjs")
with open(DRIVER_JS, "w") as fh:
    fh.write(DRIVER)
NODE_P = subprocess.Popen([NODE, DRIVER_JS], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=ROOT)
atexit.register(NODE_P.kill)


def node(msg):
    NODE_P.stdin.write(json.dumps(msg) + "\n")
    NODE_P.stdin.flush()
    line = NODE_P.stdout.readline()
    if not line:
        raise RuntimeError("node умер")
    return json.loads(line)


class Daemon:
    """Подделка демона: /health, /open (своя вкладка по session), /eval — в node; пишет вызовы."""

    def __init__(self):
        self.calls, self.tabs, self.redirect, self.hook = [], {}, {}, None

    def transport(self, port, method, path, body=None, token=None, timeout=60):
        self.calls.append((path, body, timeout))
        if path == "/health" and token is None:
            return 200, json.dumps({"browser": "comet", "port": port, "connected": True})
        if token != TOKEN:
            return 401, "нужен заголовок"
        sid = (body or {}).get("session", "")
        if path == "/health":
            return 200, json.dumps({"connected": True, "work": {"url": self.tabs.get("", "about:blank")},
                                    "sessions": [{"session": k, "url": v} for k, v in self.tabs.items() if k]})
        if path == "/open":
            url = self.redirect.get(body["url"], body["url"])
            self.tabs[sid] = url
            u = urlsplit(url)
            node({"cmd": "origin", "origin": f"{u.scheme}://{u.netloc}" if u.netloc else "null"})
            return 200, json.dumps({"url": url, "title": "", "timedOut": False})
        if path == "/eval":
            r = node({"expr": body["expr"]})
            if "error" in r:
                return 200, json.dumps({"error": r["error"]})
            v = r["value"]
            if self.hook:
                v = self.hook(body["expr"], v)
            return 200, v if isinstance(v, str) else json.dumps(v)
        return 404, "нет"

    def paths(self):
        return [c[0] for c in self.calls]


D = Daemon()
B.transport = D.transport
B.time = types.SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic, strftime=time.strftime)
T0 = time.time()
os.environ["PANTHEON_NOW"] = str(T0)
SITE = "rosreestr.gov.ru"
CFG = (B.DEFAULT_DOMAINS + (SITE,), B.DEFAULT_WINDOWS, True)
B.DL_MAX = 6 * 1024 * 1024                    # предел для теста: файлы — единицы МБ, а не сотни
B.DL_CHUNK = 1024 * 1024 + 7                  # не кратно размеру файла: последний кусок короче


def body(n, seed):
    out, h = bytearray(), hashlib.sha256(seed.encode()).digest()
    while len(out) < n:
        h = hashlib.sha256(h).digest()
        out += h
    return bytes(out[:n])


def serve(url, data, **kw):
    node({"cmd": "files", "files": {url: {"b64": base64.b64encode(data).decode(), **kw}}})


def req(url, task="athena-0205", **kw):
    return {"v": 1, "op": "download", "browser": "comet", "id": "x", "t": P.now(), "url": url, "task": task, **kw}


def run(r, win="hq", cfg=CFG):
    D.calls.clear()
    return B.handle(json.dumps(r), win, cfg)


def tree(d):
    out = []
    for base, _dirs, files in os.walk(d):
        out += [os.path.relpath(os.path.join(base, f), d) for f in files]
    return sorted(out)


def stage():
    return tree(B.root("dl")) if os.path.isdir(B.root("dl")) else []


def tidy():
    s = node({"cmd": "state"})
    return not s["store"] and not s["blobs"]


def answer(t, q, a):
    with open(os.path.join(STATE, "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write("\n## %s · окно вопросов\nвопрос: %s\nответ: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)), q, a))


# --- путь удачи ------------------------------------------------------------------------------------------------------
ZIP = f"https://{SITE}/upload/opendata/deals-2026-q3-v2.zip"
DATA = body(3 * 1024 * 1024 + 4321, "zip")
serve(ZIP, DATA, disp="attachment; filename*=UTF-8''%D0%A1%D0%B4%D0%B5%D0%BB%D0%BA%D0%B8%203%20%D0%BA%D0%B2.zip")
res = run(req(ZIP))
want = os.path.join(INBOX, SITE, "Сделки 3 кв.zip")
check("download: файл в inbox/<сайт>/ направления задачи, байт в байт, имя из filename*",
      res["state"] == "done" and os.path.isfile(want) and open(want, "rb").read() == DATA, (res, tree(INBOX)))
mode = os.stat(want).st_mode & 0o7777 if os.path.isfile(want) else None
check("download: права 0644 — без исполняемого бита", mode == 0o644, oct(mode or 0))
if sys.platform == "darwin":
    q = subprocess.run(["/usr/bin/xattr", "-p", "com.apple.quarantine", want], capture_output=True, text=True)
    check("download: метка карантина macOS (com.apple.quarantine «0081;…;pantheon;»)",
          q.returncode == 0 and re.fullmatch(r"0081;[0-9a-f]{8};pantheon;", q.stdout.strip()), (q.returncode, q.stdout, q.stderr))
else:
    print("пропущено: метка карантина — нужен macOS")
check("download: итог — путь, размер, sha256", res.get("text") and "Сделки 3 кв.zip" in res["text"]
      and str(len(DATA)) in res["text"] and hashlib.sha256(DATA).hexdigest() in res["text"], res)
gi = open(os.path.join(INBOX, SITE, ".gitignore"), encoding="utf-8").read() if os.path.isfile(
    os.path.join(INBOX, SITE, ".gitignore")) else ""
check("download: имя файла в .gitignore папки (тик коммитит ~/ai/pantheon)", "/Сделки 3 кв.zip\n" in gi, gi)
opens = [c[1] for c in D.calls if c[0] == "/open"]
evals = [c[1] for c in D.calls if c[0] == "/eval"]
check("download: вкладка окна (session hq) переходит на главную сайта файла, не на сам файл",
      opens and opens[0]["url"] == f"https://{SITE}/" and all(o.get("session") == "hq" for o in opens)
      and all(e.get("session") == "hq" and e.get("target") == "work" for e in evals), opens)
check("download: только /health, /open, /eval — /cmd (setDownloadBehavior) не зовётся",
      set(D.paths()) <= {"/health", "/open", "/eval"}, D.paths())
chunks = [e for e in evals if "readAsDataURL" in e["expr"]]
check("download: тело кусками (по DL_CHUNK), последний короче", len(chunks) == -(-len(DATA) // B.DL_CHUNK), len(chunks))
f0 = node({"cmd": "state"})["fetches"]
check("download: fetch файла — со входами (credentials include)", f0 and f0[-1] == {"url": ZIP, "credentials": "include"}, f0)
check("download: тело в кэше сайта удалено, недокачанного в STATE нет", tidy() and stage() == [], (node({"cmd": "state"}), stage()))
note = open(NOTIFY, encoding="utf-8").read() if os.path.isfile(NOTIFY) else ""
check("download: уведомление владельцу — кто, что, сайт, задача", f"hq): download на {SITE}, задача athena-0205" in note, note)
log = open(os.path.join(STATE, "logs", "browser.jsonl"), encoding="utf-8").read()
check("download: журнал — запись op download, без содержимого файла", '"op": "download"' in log and '"state": "done"' in log)

res = run(req(ZIP))
check("тот же файл ещё раз — «уже был», второго файла нет",
      res["state"] == "done" and "уже был" in res["text"] and tree(os.path.join(INBOX, SITE)) == [".gitignore", "Сделки 3 кв.zip"],
      (res, tree(INBOX)))
serve(ZIP, body(1000, "другой"), disp="attachment; filename*=UTF-8''%D0%A1%D0%B4%D0%B5%D0%BB%D0%BA%D0%B8%203%20%D0%BA%D0%B2.zip")
res = run(req(ZIP))
check("другой файл с тем же именем — «(2)», первый не перезаписан",
      res["state"] == "done" and os.path.isfile(os.path.join(INBOX, SITE, "Сделки 3 кв (2).zip"))
      and open(want, "rb").read() == DATA, tree(INBOX))

PDF = f"https://{SITE}/upload/opendata/opisanie.pdf"
PDF_DATA = b"%PDF-1.7\n" + body(200_000, "pdf")
serve(PDF, PDF_DATA, type="application/pdf")
res = run(req(PDF, to="rosreestr"))
check("--to rosreestr: файл в inbox/rosreestr/, имя из адреса",
      res["state"] == "done" and open(os.path.join(INBOX, "rosreestr", "opisanie.pdf"), "rb").read() == PDF_DATA, (res, tree(INBOX)))

DMG = f"https://{SITE}/upload/Setup.dmg"
serve(DMG, body(5000, "dmg"), type="application/octet-stream")
res = run(req(DMG, to="rosreestr"))
check("файл .dmg (macOS монтирует и запускает) — с хвостом .download",
      res["state"] == "done" and os.path.isfile(os.path.join(INBOX, "rosreestr", "Setup.dmg.download"))
      and not os.path.exists(os.path.join(INBOX, "rosreestr", "Setup.dmg")), (res, tree(INBOX)))

# --- согласие ----------------------------------------------------------------------------------------------------------
OTHER = "https://data.example.org/f.zip"
serve(OTHER, b"x" * 100)
res = run(req(OTHER), cfg=(B.DEFAULT_DOMAINS, B.DEFAULT_WINDOWS, True))
check("сайт не из списка без «да» — отказ, демон не зван, папки нет",
      res["state"] == "refused" and "/open" not in D.paths() and not os.path.exists(os.path.join(INBOX, "data.example.org")), res)
answer(T0 - 600, "[athena-0300] Скачать набор с data.example.org?", "Да")
res = run(req(OTHER, task="athena-0300"), cfg=(B.DEFAULT_DOMAINS, B.DEFAULT_WINDOWS, True))
check("«да» владельца по задаче с хостом в вопросе — скачано",
      res["state"] == "done" and os.path.isfile(os.path.join(INBOX, "data.example.org", "f.zip")), res)
REDIR = f"https://{SITE}/go.zip"
serve(REDIR, b"y" * 100, final="https://evil.example.net/y.zip")
res = run(req(REDIR))
check("файл пришёл с чужого сайта (редирект fetch) — отказ, в inbox ничего, about:blank",
      res["state"] == "refused" and "пришёл с" in res["why"] and "go.zip" not in str(tree(INBOX))
      and D.tabs.get("hq") == "about:blank" and tidy(), res)

# --- отказы и сбои без мусора --------------------------------------------------------------------------------------------
B.DL_MAX = 1024 * 1024
before = tree(INBOX)


def clean_fail(name, res, state, word):
    check(f"{name}: {state} «{word}», в inbox ничего нового, недокачанного нет, вкладка about:blank, кэш сайта пуст",
          res["state"] == state and word in res.get("why", "") and tree(INBOX) == before and stage() == []
          and D.tabs.get("hq") == "about:blank" and tidy(), (res, tree(INBOX), stage(), node({"cmd": "state"})))


BIG = f"https://{SITE}/big.zip"
serve(BIG, body(1024 * 1024 + 1, "big"))
clean_fail("больше предела по content-length", run(req(BIG, to="fresh")), "refused", "больше")
check("больше предела: новая папка --to fresh убрана", not os.path.exists(os.path.join(INBOX, "fresh")), tree(INBOX))
serve(BIG, body(1024 * 1024 + 1, "big"), length=None)
clean_fail("больше предела без content-length (счёт по потоку)", run(req(BIG)), "refused", "больше")
serve(BIG, b"z" * 10, length=1024 * 1024 + 1)
clean_fail("content-length больше предела — обрыв до чтения тела", run(req(BIG)), "refused", "больше")
B.DL_MAX = 6 * 1024 * 1024
HTML = f"https://{SITE}/login.zip"
serve(HTML, b"<html>login</html>", type="text/html; charset=utf-8")
clean_fail("text/html вместо файла", run(req(HTML)), "refused", "страницу")
GONE = f"https://{SITE}/gone.zip"
serve(GONE, b"no", status=404)
clean_fail("404", run(req(GONE)), "failed", "404")
clean_fail("ошибка fetch (сеть, CORS)", run(req(f"https://{SITE}/nofile.zip")), "failed", "Failed to fetch")
D.redirect[f"https://{SITE}/"] = "https://www.rosreestr.gov.ru/"
clean_fail("главная увела на другой адрес", run(req(ZIP)), "failed", "увела")
D.redirect.clear()


def cut(expr, v):
    if "readAsDataURL" in expr and isinstance(v, dict) and v.get("b64"):
        v = dict(v, b64=v["b64"][:-8])
    return v


D.hook = cut
clean_fail("обрезанный кусок", run(req(ZIP)), "failed", "обрыв")


def badsha(expr, v):
    if "getReader" in expr and isinstance(v, dict) and v.get("sha"):
        v = dict(v, sha="0" * 64)
    return v


D.hook = badsha
clean_fail("sha256 браузера не сошлась", run(req(ZIP)), "failed", "sha256")
D.hook = None


def no_quarantine(fd):
    raise OSError(1, "Operation not permitted")


real_quarantine, B.quarantine = B.quarantine, no_quarantine
clean_fail("метка карантина не поставилась", run(req(ZIP)), "failed", "карантина")
B.quarantine = real_quarantine
B.DL_TIME = -1
clean_fail("время вышло", run(req(ZIP)), "failed", "время вышло")
B.DL_TIME = 540

# --- http без Cache Storage: адрес blob: ----------------------------------------------------------------------------------
node({"cmd": "secure", "on": False})
res = run(req(PDF, to="plain"))
node({"cmd": "secure", "on": True})
check("без Cache Storage (http) — тело через blob:, скачано, адрес отозван",
      res["state"] == "done" and open(os.path.join(INBOX, "plain", "opisanie.pdf"), "rb").read() == PDF_DATA and tidy(),
      (res, node({"cmd": "state"})))

# --- недокачанное на другом диске — скрытым в папке, но в .gitignore ------------------------------------------------------
B.same_dev = lambda a, b: False
res = run(req(PDF, to="otherdev"))
B.same_dev = lambda a, b: os.fstat(a).st_dev == os.fstat(b).st_dev
od = os.path.join(INBOX, "otherdev")
gi = open(os.path.join(od, ".gitignore"), encoding="utf-8").read() if os.path.isfile(os.path.join(od, ".gitignore")) else ""
check("другой диск: недокачанное в самой папке скрыто и в .gitignore, после — только файл",
      res["state"] == "done" and tree(od) == [".gitignore", "opisanie.pdf"] and "/.pantheon-dl-*.part" in gi, (res, tree(od), gi))

# --- старое недокачанное убирается ---------------------------------------------------------------------------------------
os.makedirs(B.root("dl"), exist_ok=True)
old = os.path.join(B.root("dl"), ".pantheon-dl-dead.part")
open(old, "wb").write(b"half")
os.utime(old, (T0 - 2 * 3600, T0 - 2 * 3600))
res = run(req(PDF, to="rosreestr"))
check("недокачанное старше часа (обрыв прохода) убирается при следующем скачивании", res["state"] == "done"
      and not os.path.exists(old), stage())

# --- ссылка вместо папки ---------------------------------------------------------------------------------------------------
os.makedirs(os.path.join(ROOT, "elsewhere"))
os.symlink(os.path.join(ROOT, "elsewhere"), os.path.join(INBOX, "linked"))
res = run(req(PDF, to="linked"))
check("папка назначения — ссылка: сбой, наружу ничего не записано", res["state"] == "failed" and "не настоящая" in res["why"]
      and os.listdir(os.path.join(ROOT, "elsewhere")) == [] and "/open" not in D.paths(), res)

# --- задача, --to, разбор вызова ----------------------------------------------------------------------------------------
res = run(req(PDF, task="athena-0999"))
check("задачи нет — отказ без перехода", res["state"] == "refused" and "задачи athena-0999 нет" in res["why"]
      and "/open" not in D.paths(), res)
res = run(req(PDF, task=None))
check("без --task — отказ «нужен --task»", res["state"] == "refused" and "--task" in res["why"], res)
for bad in ("../x", ".hidden", "Rosreestr", "a/b", "", "x" * 64):
    res = run(req(PDF, to=bad))
    check(f"--to {bad[:12]!r} — отказ", res["state"] == "refused", res)
r, w = B.parse(["download", ZIP, "--task", "athena-0205", "--to", "rosreestr"])
check("CLI: download URL --task --to → заявка, ожидание по умолчанию WAIT_MAX",
      r["op"] == "download" and r["url"] == ZIP and r["to"] == "rosreestr" and w == B.WAIT_MAX, (r, w))
r, w = B.parse(["download", ZIP, "--task", "athena-0205", "--wait", "30"])
check("CLI: --wait задаёт ожидание, без --to поля нет", w == 30 and "to" not in r, (r, w))
for argv in (["download", ZIP], ["download", "--task", "athena-0205"], ["download", ZIP, "--task", "athena-0205", "--to", "../x"]):
    try:
        B.parse(argv)
        got = None
    except (ValueError, B.Refuse) as e:
        got = str(e)
    check(f"CLI: {' '.join(argv[1:])[:50]} — неверный вызов", got, got)

# --- имя файла -------------------------------------------------------------------------------------------------------------
for disp, url, want_name in (
        ('attachment; filename="../../.ssh/authorized_keys"', ZIP, "authorized_keys"),
        ('attachment; filename=".bashrc"', ZIP, "bashrc"),
        ("attachment; filename=\"" + "Отчёт.pdf".encode().decode("latin-1") + "\"", ZIP, "Отчёт.pdf"),
        ("", "https://a.ru/dir/%2E%2E%2Fx.zip", "x.zip"),
        ("", "https://a.ru/", "download"),
        ('attachment; filename="a‮gpj.exe"', ZIP, "a_gpj.exe"),
        ('attachment; filename="-rf $HOME;.zip"', ZIP, "rf _HOME_.zip"),
        ("attachment; filename*=UTF-8''%E2%80%AE%00x.zip", ZIP, "__x.zip"),
        ('attachment; filename="run.COMMAND"', ZIP, "run.COMMAND.download"),
        ("", "https://a.ru/install.sh", "install.sh.download"),
        ('attachment; filename="Viewer.app"', ZIP, "Viewer.app.download"),
        ('attachment; filename="data.app.zip"', ZIP, "data.app.zip")):
    got = B.dl_name(disp, url)
    check(f"имя: {disp or url!r:.50} → {want_name!r}", got == want_name, got)
long = B.dl_safe("я" * 300 + ".zip")
check("имя: длинное — до 200 байт UTF-8, расширение сохранено", len(long.encode()) <= 200 and long.endswith(".zip"), long)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
