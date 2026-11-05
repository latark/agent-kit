#!/usr/bin/env python3
"""`pantheon browser` — действия Харона (lib/browser.py, metis-0765): поручение, нажатие, ввод, отправка, удаление.

Запуск: python3.14 -I plugins/pantheon/tests/test_browser_acts.py  (код выхода 0 — все прошли)
Всё во временных папках; демон — подделка на месте transport(), окно Touch ID — поддельный помощник на месте
merge_mod().helper() (код выхода из файла, вызовы в журнал). Настоящий браузер, демон, пароль и окно не трогаются.
Метки — строки модели угроз plugins/pantheon/docs/charon/README.md:
- [M1]–[M3] поручение: без него действия нет; действие вне списка, другой сайт, истёкший срок — отказ; платёжный и
  важный сайт — поручения нет; «да» на вопрос поручения или Touch ID;
- [F1] оплата — отказ всегда, окна Touch ID нет, «да» не действует; [F2] важная форма — так же; [F3] удаление одного —
  «да» или Touch ID, пачки — только «да»;
- [C3]–[C6], [C10]–[C12] согласие на отправку: код вопроса, сайт, путь и запрос адреса, селектор и отпечаток формы;
  одно «да» — одна отправка; ответ раньше выдачи кода не в счёт; форма на другой сайт — отказ;
- [K1]–[K6] нажатие: вид по тегу, предки, точка, ссылка того же сайта, мгновенная прокрутка;
- [T1]–[T3] Touch ID: тот же помощник, что у слияния, кнопка «Отказать»; владельца нет, помощника нет — вопрос для «да»;
- /cmd — только Input.dispatchMouseEvent и Input.insertText; CLI allow/click/type/submit/delete.
"""
import atexit
import copy
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402  CLI pantheon — только на Python 3.11+

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="browser-acts-"))
atexit.register(shutil.rmtree, ROOT, True)
HOME, PAN, STATE = (os.path.join(ROOT, d) for d in ("home", "pantheon", "state"))
for d in (HOME, PAN, STATE, os.path.join(STATE, "owner-log")):
    os.makedirs(d, exist_ok=True)
for k in list(os.environ):
    if k.startswith(("PANTHEON_", "CLAUDE_CODE_", "XDG_")) or k == "CLAUDECODE":
        del os.environ[k]
NOTIFY = os.path.join(ROOT, "notify.log")
os.environ.update({"HOME": HOME, "PANTHEON_HOME": PAN, "PANTHEON_STATE": STATE, "PANTHEON_NOTIFY_LOG": NOTIFY,
                   "PANTHEON_FAKE_IDLE": "5"})
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
sys.path.insert(0, LIB)
import pantheon as P  # noqa: E402

B = P.browser_mod()
M = P.merge_mod()
TOKEN = "cd" * 32
os.makedirs(os.path.join(HOME, ".config", "cdp-daemon"))
with open(os.path.join(HOME, ".config", "cdp-daemon", "token"), "w") as fh:
    fh.write(TOKEN + "\n")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


TASK = "metis-0999"
SITE = "https://www.avito.ru"
DOMAINS = B.DEFAULT_DOMAINS + ("gosuslugi.ru", "yoomoney.ru", "example.com")
CFG = (DOMAINS, B.DEFAULT_WINDOWS, True)


# --- поддельное окно Touch ID ---------------------------------------------------------------------------------------
TOUCH_RC = os.path.join(ROOT, "touch.rc")
TOUCH_LOG = os.path.join(ROOT, "touch.log")
TOUCH = os.path.join(ROOT, "pantheon-touchid")
with open(TOUCH, "w") as fh:
    fh.write("#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + json.dumps(TOUCH_LOG)[1:-1].replace(" ", "\\ ")
             + "\nexit $(cat " + json.dumps(TOUCH_RC)[1:-1].replace(" ", "\\ ") + ")\n")
os.chmod(TOUCH, stat.S_IRWXU)
HELPER = {"path": TOUCH}
M.helper = lambda: HELPER["path"]


def finger(rc):
    with open(TOUCH_RC, "w") as fh:
        fh.write(str(rc))


def clear_touch():
    if os.path.exists(TOUCH_LOG):
        os.remove(TOUCH_LOG)


def touches():
    try:
        return open(TOUCH_LOG, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return []


finger(3)


# --- поддельный демон с фактами страниц ------------------------------------------------------------------------------

def node(tag, type_="", role="", label="", attrs="", href="", onclick=False, target="", download=False, ce=False,
         ctag="", ctype=""):
    return {"tag": tag, "type": type_, "role": role, "href": href, "onclick": onclick, "target": target,
            "download": download, "ce": ce, "ctag": ctag, "ctype": ctype, "label": label, "attrs": attrs}


def field(name, value="", type_="text", tag="input", label="", auto="", checked=False):
    return {"tag": tag, "type": type_, "name": name, "label": label, "auto": auto, "value": value, "checked": checked}


def facts(el, chain=None, fields=(), form=None, buttons=(), heads=(), hit=True, x=100.0, y=200.0):
    """Факты, которые вернул бы FACTS_JS: цель, цепочка от точки нажатия вверх, поля и кнопки формы."""
    return {"x": x, "y": y, "w": 80, "h": 20, "hit": hit, "chain": list(chain) if chain is not None else [el, node("div"),
            node("body"), node("html")], "el": el, "elabel": el.get("label", ""), "focused": False,
            "fields": [dict(f) for f in fields], "buttons": list(buttons), "heads": list(heads), "form": form}


class Daemon:
    def __init__(self):
        self.tab, self.calls, self.els, self.moves = "about:blank", [], {}, {}
        self.point_shift = 0.0          # [K4] сдвиг рамки между замером и нажатием
        self.point_hit = True
        self.focusable = True
        self.after = {}                 # селектор → адрес, куда уводит нажатие
        self.on_facts, self.n_facts = None, 0   # [T2] изменить страницу на n-м замере

    def page(self, url, els):
        self.els[url] = els

    def transport(self, port, method, path, body=None, token=None, timeout=60):
        self.calls.append((path, copy.deepcopy(body)))
        if path == "/health" and token is None:
            return 200, json.dumps({"browser": "comet", "connected": True})
        if token != TOKEN:
            return 401, "нужен заголовок"
        if path == "/health":
            return 200, json.dumps({"connected": True, "work": {"url": self.tab}})
        if path == "/open":
            self.tab = body["url"]
            return 200, json.dumps({"url": self.tab, "title": "", "timedOut": False})
        if path == "/eval":
            expr = body["expr"]
            m = re.search(r"const S = (\"(?:[^\"\\]|\\.)*\");", expr)
            sel = json.loads(m.group(1)) if m else None
            el = (self.els.get(self.tab) or {}).get(sel)
            if expr.startswith("/*charon-facts*/"):
                self.n_facts += 1
                if self.on_facts:
                    self.on_facts(self.n_facts)
                    el = (self.els.get(self.tab) or {}).get(sel)
                if el is None:
                    return 200, json.dumps(None)
                out = copy.deepcopy(el)
                out["url"] = self.tab
                out["focused"] = "e.focus();" in expr and self.focusable
                return 200, json.dumps(out)
            if expr.startswith("/*charon-point*/"):
                if el is None:
                    return 200, json.dumps(None)
                return 200, json.dumps({"url": self.tab, "x": el["x"] + self.point_shift, "y": el["y"],
                                        "hit": self.point_hit})
            return 200, json.dumps({"value": "?"})
        if path == "/cmd":
            if body.get("method") == "Input.dispatchMouseEvent" and body["params"].get("type") == "mouseReleased":
                for sel, el in (self.els.get(self.tab) or {}).items():
                    if (el["x"], el["y"]) == (body["params"]["x"], body["params"]["y"]) and sel in self.after:
                        self.tab = self.after[sel]
                        break
            return 200, json.dumps({"result": {}})
        return 404, "нет"

    def cmds(self):
        return [b for p, b in self.calls if p == "/cmd"]

    def clicked(self):
        return [b["params"] for b in self.cmds() if b["method"] == "Input.dispatchMouseEvent"
                and b["params"]["type"] == "mouseReleased"]


D = Daemon()
B.transport = D.transport
B.time = types.SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic, strftime=time.strftime)
T0 = time.time()
os.environ["PANTHEON_NOW"] = str(T0)


def at(t):
    os.environ["PANTHEON_NOW"] = str(t)


def req(op, **kw):
    r = {"v": 1, "op": op, "browser": "comet", "id": "x", "t": P.now(), "task": TASK}
    r.update(kw)
    return r


def run(r, win=None, cfg=None):
    return B.handle(json.dumps(r), win, cfg or CFG)


def answer(t, q, a="Да — разрешить"):
    """Ответ окном вопросов так, как его пишет хук answer (ctx.py cmd_answer): «→» и ёлочки — пробел, пробелы сжаты."""
    q = re.sub(r"\s+", " ", re.sub(r"[→«»]", " ", q)).strip()
    with open(os.path.join(STATE, "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write("\n## %s · окно вопросов\nвопрос: %s\nответ: %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)), q, a))


def quoted(why):
    """Текст вопроса для Зевса из отказа: «…» после «спросить окном вопросов: »."""
    m = re.search(r"спросить окном вопросов: «(.*)» с вариантами", why or "")
    return m.group(1) if m else None


def act(op, sel, url, **kw):
    D.tab = url
    D.calls.clear()
    D.n_facts = 0
    return run(req(op, selector=sel, **kw))


def mandates():
    d = os.path.join(STATE, "browser", "mandates")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def reset_mandates():
    shutil.rmtree(os.path.join(STATE, "browser", "mandates"), ignore_errors=True)


def give(site="avito.ru", actions="click,type,submit,delete"):
    """Поручение через Touch ID (палец)."""
    finger(0)
    res = run(req("allow", site=site, actions=actions, why="подать объявление"))
    finger(3)
    clear_touch()
    return res


# --- страницы --------------------------------------------------------------------------------------------------------
FORM = {"action": SITE + "/items/new", "label": "new-item"}
TITLE = field("title", "Диван", label="Название")
PRICE = field("price", "5000", type_="number", label="Цена")
SEND = node("button", "submit", label="Опубликовать")
ORD = facts(SEND, fields=[TITLE, PRICE], form=FORM, buttons=["Опубликовать"])
D.page(SITE + "/items/new", {"#send": ORD,
                             "#title": dict(facts(node("input", "text", attrs="title"), fields=[TITLE, PRICE], form=FORM,
                                                  buttons=["Опубликовать"]), x=10.0),
                             "#about": dict(facts(node("textarea", attrs="about"), fields=[TITLE], form=FORM), x=11.0),
                             "#agree": dict(facts(node("input", "checkbox", attrs="agree")), x=12.0)})
D.page(SITE + "/items/new?draft=2", {"#send": ORD})
D.page(SITE + "/items/other", {"#send": ORD})


# --- [M] поручение ----------------------------------------------------------------------------------------------------
res = act("submit", "#send", SITE + "/items/new")
check("[M1] submit без поручения — отказ «поручения … нет», демон не нажимал, окна Touch ID нет",
      res["state"] == "refused" and "поручения" in res["why"] and "allow" in res["why"] and not D.cmds()
      and not touches(), res)
res = run(req("allow", site="avito.ru", actions="click,submit"))
check("[M1] allow без --why — отказ", res["state"] == "refused" and "--why" in res["why"], res)
res = run(req("allow", site="avito.ru", actions="click,pay", why="x"))
check("[M1] allow с неизвестным действием — отказ", res["state"] == "refused" and "pay" in res["why"], res)
res = run({**req("allow", site="avito.ru", actions="click", why="x"), "task": None})
check("[M1] allow без --task — отказ", res["state"] == "refused" and "--task" in res["why"], res)

os.environ["PANTHEON_FAKE_IDLE"] = "900"
res = run(req("allow", site="avito.ru", actions="click,submit", why="подать объявление"))
q = quoted(res.get("why"))
check("[M1][T3] владельца нет у Mac — окна нет, отказ с вопросом «[ID] Поручение Харону на avito.ru: нажатия, "
      "отправка форм.»", res["state"] == "refused" and not touches() and q
      and q.startswith(f"[{TASK}] Поручение Харону на avito.ru: нажатия, отправка форм.") and not mandates(), res)
at(T0 + 10)
for tail, what in ((" Ещё: оплатить продвижение", "тот же вопрос и лишний хвост"),
                   (None, "только начало вопроса (без цели)")):
    answer(T0 + 4, q + tail if tail else q.split(" Цель:")[0])
    res = run(req("allow", site="avito.ru", actions="click,submit", why="подать объявление"))
    check(f"[B3] «да» на другой вопрос с тем же началом ({what}) — не согласие, поручения нет",
          res["state"] == "refused" and not mandates() and not touches(), res)
res = run(req("allow", site="avito.ru", actions="click,submit", why="продать диван"))
q_other = quoted(res.get("why"))
answer(T0 + 4, q_other)
res = run(req("allow", site="avito.ru", actions="click,submit", why="подать объявление"))
check("[B3] «да» на вопрос поручения с другой целью — не согласие на эту", res["state"] == "refused" and not mandates(), res)
answer(T0 + 5, q)
res = run(req("allow", site="avito.ru", actions="click,submit", why="подать объявление"))
check("[M1][B3] «да» окном вопросов на этот вопрос (ёлочки убраны хуком) — поручение есть (по «да»), Touch ID не звали",
      res["state"] == "done" and "«да»" in res["text"] and len(mandates()) == 1 and not touches(), res)
os.environ["PANTHEON_FAKE_IDLE"] = "5"
res = run(req("allow", site="www.avito.ru", actions="click", why="ещё"))
check("[M1] повтор allow с подмножеством действий — «уже есть», без нового окна",
      res["state"] == "done" and "уже есть" in res["text"] and not touches(), res)
reset_mandates()
res = run(req("allow", site="avito.ru", actions="click,submit", why="подать объявление"))
check("[M1] ответ на вопрос поручения действует не дольше суток — до 24 ч ещё да", res["state"] == "done", res)
reset_mandates()
at(T0 + 25 * 3600)
finger(1)
res = run(req("allow", site="avito.ru", actions="click,submit", why="подать объявление"))
check("[M1] «да» старше 24 ч — нет; окно Touch ID, отказ владельца — «не повторяй», поручения нет",
      res["state"] == "refused" and "отказал" in res["why"] and len(touches()) == 1 and not mandates(), res)
args = touches()[0]
check("[T4] окно поручения: текст с задачей, сайтом и действиями, ждёт 120 с, кнопка «Отказать»",
      TASK in args and "avito.ru" in args and "нажатия" in args and args.endswith(" 120 Отказать"), args)
at(T0)
clear_touch()

res = give()
check("[M1] Touch ID (палец) — поручение на сутки", res["state"] == "done" and "Touch ID" in res["text"]
      and len(mandates()) == 1, res)
rec = json.load(open(os.path.join(STATE, "browser", "mandates", mandates()[0])))
check("[M1] запись поручения: задача, сайт без www, действия, срок 24 ч, кто разрешил",
      rec["task"] == TASK and rec["site"] == "avito.ru" and rec["actions"] == list(B.ACTS)
      and rec["until"] - rec["from"] == 24 * 3600 and rec["by"] == "Touch ID", rec)
clear_touch()

for site, word in (("yoomoney.ru", "платёжный"), ("gosuslugi.ru", "госсайт"), ("pay.avito.ru", "платёжный"),
                   ("id.avito.ru", "входа")):
    finger(0)
    res = run(req("allow", site=site, actions="click", why="x"))
    check(f"[M1][F1][F2] поручения на {site} нет даже с пальцем — «{word}», окна нет",
          res["state"] == "refused" and word in res["why"] and not touches(), res)
finger(3)
res = run(req("allow", site="evil.example.org", actions="click", why="x"))
check("[M1] поручение на сайт, которого нельзя читать, — отказ", res["state"] == "refused" and "списке" in res["why"], res)

# [M2] действие вне списка, [M3] другой сайт и срок
reset_mandates()
give(actions="click")
res = act("submit", "#send", SITE + "/items/new")
check("[M3] поручение только на click — submit отказ, нажатия нет", res["state"] == "refused" and "поручения" in res["why"]
      and not D.cmds(), res)
res = act("type", "#title", SITE + "/items/new", text="x")
check("[M3] поручение только на click — type отказ", res["state"] == "refused" and not D.cmds(), res)
reset_mandates()
give(site="example.com")
D.page("https://example.com/f", {"#send": dict(ORD, form={"action": "https://example.com/f", "label": ""})})
res = act("submit", "#send", SITE + "/items/new")
check("[M2] поручение на example.com — на avito.ru отказ", res["state"] == "refused" and "поручения" in res["why"]
      and not D.cmds(), res)
reset_mandates()
give()
at(T0 + 24 * 3600 + 5)
res = act("click", "#agree", SITE + "/items/new")
check("[M3] поручение старше 24 ч — отказ", res["state"] == "refused" and "поручения" in res["why"] and not D.cmds(), res)
at(T0)
res = run({**req("submit", selector="#send"), "task": "metis-0998"})
check("[M2] поручение другой задачи не действует", res["state"] == "refused" and "поручения" in res["why"], res)
clear_touch()

# --- [K] нажатие --------------------------------------------------------------------------------------------------------
K = SITE + "/k"
chk = node("input", "checkbox", attrs="agree")
D.page(K, {
    "#cb": dict(facts(chk), x=1.0),
    "#radio": dict(facts(node("input", "radio")), x=2.0),
    "#label": dict(facts(node("label", ctag="input", ctype="checkbox", label="Согласен")), x=3.0),
    "#link": dict(facts(node("a", href=SITE + "/items/other", label="Ещё")), x=4.0),
    "#span-in-btn": dict(facts(node("span"), chain=[node("span"), node("button", "submit", label="Удалить"),
                                                   node("form"), node("body")]), x=5.0),
    "#btn-role-cb": dict(facts(node("button", role="checkbox", label="Да")), x=6.0),
    "#cb-role-button": dict(facts(node("input", "checkbox", role="button")), x=7.0),
    "#cb-in-a": dict(facts(chk, chain=[chk, node("a", href=SITE + "/buy"), node("body")]), x=8.0),
    "#cb-in-label": dict(facts(chk, chain=[chk, node("label", ctag="input", ctype="checkbox"), node("body")]), x=9.0),
    "#cb-in-onclick": dict(facts(chk, chain=[chk, node("div", onclick=True), node("body")]), x=10.0),
    "#cb-in-role": dict(facts(chk, chain=[chk, node("div", role="button"), node("body")]), x=11.0),
    "#div": dict(facts(node("div", label=""), chain=[node("div"), node("body")]), x=12.0),
    "#div-tab": dict(facts(node("div", role="tab", label="Вкладка")), x=13.0),
    "#ext": dict(facts(node("a", href="https://evil.com/x", label="туда")), x=14.0),
    "#js": dict(facts(node("a", href="javascript:void(0)", label="js")), x=15.0),
    "#blank": dict(facts(node("a", href=SITE + "/y", target="_blank", label="новое окно")), x=16.0),
    "#dl": dict(facts(node("a", href=SITE + "/f.pdf", download=True, label="скачать")), x=17.0),
    "#a-onclick": dict(facts(node("a", href=SITE + "/y", onclick=True, label="y")), x=18.0),
    "#a-role-btn": dict(facts(node("a", href=SITE + "/y", role="button", label="y")), x=19.0),
    "#cover": dict(facts(chk, hit=False), x=20.0),
    "#leave": dict(facts(node("a", href=SITE + "/go", label="go")), x=21.0),
    "#buy": dict(facts(node("a", href=SITE + "/item/1", label="Купить")), x=22.0),
})
D.after["#leave"] = "https://evil.com/landing"
res = act("click", "#cb", K)
clicks = D.clicked()
moves = [b["params"]["type"] for b in D.cmds()]
check("[K2] флажок input checkbox — нажат: mouseMoved, mousePressed, mouseReleased в центр, вкладка окна",
      res["state"] == "done" and "checkbox" in res["text"] and moves == ["mouseMoved", "mousePressed", "mouseReleased"]
      and clicks == [{"type": "mouseReleased", "x": 1.0, "y": 200.0, "button": "left", "clickCount": 1}]
      and all(b.get("target") == "work" for b in D.cmds()), (res, D.cmds()))
for sel, kind in (("#radio", "radio"), ("#label", "checkbox"), ("#link", "link"), ("#cb-in-label", "checkbox")):
    res = act("click", sel, K)
    check(f"[K2] {sel} — нажат ({kind})", res["state"] == "done" and f"({kind})" in res["text"] and D.clicked(), res)
for sel, label, word in (
        ("#span-in-btn", "K1", "submit"), ("#btn-role-cb", "K2", "роль его не расширяет"),
        ("#cb-role-button", "K2", "submit"), ("#cb-in-a", "K3", "вложен"), ("#cb-in-onclick", "K3", "вложен"),
        ("#cb-in-role", "K3", "вложен"), ("#div", "K6", "нет флажка"), ("#div-tab", "K2", "submit"),
        ("#ext", "K5", "не на avito.ru"), ("#js", "K5", "не на"), ("#blank", "K5", "submit"), ("#dl", "K5", "submit"),
        ("#a-onclick", "K2", "submit"), ("#a-role-btn", "K2", "submit"), ("#cover", "K4", "закрыл")):
    res = act("click", sel, K)
    check(f"[{label}] click {sel} — отказ ({word}), нажатия нет",
          res["state"] == "refused" and word in res["why"] and not D.clicked(), res)
D.point_shift = 3.0
res = act("click", "#cb", K)
check("[K4] рамка сдвинулась после замера (плавная прокрутка, анимация) — отказ, нажатия нет",
      res["state"] == "refused" and "сдвинулся" in res["why"] and not D.clicked(), res)
D.point_shift, D.point_hit = 0.0, False
res = act("click", "#cb", K)
check("[K4] точку закрыл другой элемент к моменту нажатия — отказ", res["state"] == "refused" and "закрыл" in res["why"]
      and not D.clicked(), res)
D.point_hit = True
check("[K4] прокрутка в FACTS_JS мгновенная (behavior: 'instant'), без smooth",
      "behavior: 'instant'" in B.facts_js("#a") and "smooth" not in B.facts_js("#a"))
res = act("click", "#leave", K)
check("[A7] нажатие увело на чужой сайт — about:blank и отказ", res["state"] == "refused" and D.tab == "about:blank"
      and len(D.clicked()) == 1, res)
res = act("click", "#buy", K)
check("[F1] ссылка «Купить» — отказ «оплата», нажатия нет", res["state"] == "refused" and "оплата" in res["why"]
      and not D.clicked(), res)
res = act("click", "#nope", K)
check("click: элемента нет — отказ", res["state"] == "refused" and "нет" in res["why"] and not D.cmds(), res)

# --- ввод ----------------------------------------------------------------------------------------------------------------
res = act("type", "#title", SITE + "/items/new", text="Диван угловой")
ins = [b for b in D.cmds() if b["method"] == "Input.insertText"]
check("type в текстовое поле — фокус в FACTS_JS, Input.insertText с текстом", res["state"] == "done"
      and ins == [{"method": "Input.insertText", "params": {"text": "Диван угловой"}, "target": "work"}], (res, D.cmds()))
res = act("type", "#title", SITE + "/items/new", text="a\nb")
check("type: перевод строки в input (отправил бы форму) — отказ", res["state"] == "refused" and not D.cmds(), res)
res = act("type", "#about", SITE + "/items/new", text="a\nb")
check("type: перевод строки в textarea — можно", res["state"] == "done" and D.cmds(), res)
res = act("type", "#agree", SITE + "/items/new", text="x")
check("type в флажок — отказ «не текстовое поле»", res["state"] == "refused" and "не текстовое" in res["why"]
      and not D.cmds(), res)
D.focusable = False
res = act("type", "#title", SITE + "/items/new", text="x")
check("type: поле не приняло фокус — отказ", res["state"] == "refused" and "фокус" in res["why"] and not D.cmds(), res)
D.focusable = True

# --- [F1] оплата, [F2] важная форма -------------------------------------------------------------------------------
PAY = SITE + "/p"
IMP = SITE + "/i"
D.page(PAY, {
    "#card": facts(SEND, fields=[field("cardnumber", "4111", label="Номер карты")], form=FORM, buttons=["Далее"]),
    "#cc": facts(SEND, fields=[field("x", "4111", auto="cc-number")], form=FORM),
    "#pay": facts(node("button", "submit", label="Оплатить 500 ₽"), fields=[TITLE], form=FORM),
    "#promo": facts(node("button", "submit", label="Продвинуть объявление"), fields=[TITLE], form=FORM),
    "#checkout": facts(SEND, fields=[TITLE], form={"action": SITE + "/checkout/confirm", "label": ""}),
    "#yoo": facts(SEND, fields=[TITLE], form={"action": "https://yoomoney.ru/quickpay", "label": ""}),
    "#t-card": facts(node("input", "text"), fields=[field("cvc", "")], form=FORM),
})
D.page(SITE + "/payment/1", {"#send": ORD})
D.page(IMP, {
    "#pw": facts(node("button", "submit", label="Далее"), fields=[field("login", "a"), field("p", "", type_="password")],
                 form=FORM),
    "#otp": facts(SEND, fields=[field("code", "", auto="one-time-code")], form=FORM),
    "#sms": facts(SEND, fields=[field("c", "", label="Код из СМС")], form=FORM),
    "#login": facts(node("button", "submit", label="Войти"), fields=[TITLE], form=FORM),
    "#mail": facts(node("button", "submit", label="Сменить почту"), fields=[TITLE], form=FORM),
    "#contract": facts(node("button", "submit", label="Подписать договор"), fields=[TITLE], form=FORM),
    "#bid": facts(node("button", "submit", label="Подать заявку на участие"), fields=[TITLE], form=FORM),
    "#rate": facts(node("button", "submit", label="Сделать ставку"), fields=[TITLE], form=FORM),
    "#transfer": facts(node("button", "submit", label="Перевести"), fields=[TITLE], form=FORM,
                       heads=["Перевод денег на карту"]),
    "#acc": facts(node("button", "submit", label="Удалить аккаунт"), fields=[TITLE], form=FORM),
    "#esia": facts(SEND, fields=[TITLE], form={"action": "https://esia.gosuslugi.ru/login", "label": ""}),
    "#signin": facts(SEND, fields=[TITLE], form={"action": SITE + "/signin", "label": ""}),
    "#t-pw": facts(node("input", "text"), fields=[field("p", "", type_="password")], form=FORM),
})
D.page(SITE + "/login", {"#send": ORD})
for page, sels, word in ((PAY, ("#card", "#cc", "#pay", "#promo", "#checkout", "#yoo"), "оплата"),
                         (SITE + "/payment/1", ("#send",), "оплата"),
                         (IMP, ("#pw", "#otp", "#sms", "#login", "#mail", "#contract", "#bid", "#rate", "#transfer",
                                "#acc", "#esia", "#signin"), "важная форма"),
                         (SITE + "/login", ("#send",), "важная форма")):
    for sel in sels:
        finger(0)
        res = act("submit", sel, page)
        f = ("F1" if word == "оплата" else "F2") + "][T1"
        check(f"[{f}] submit {page[len(SITE):]} {sel} — отказ «{word}», окна Touch ID нет, нажатия нет (даже с пальцем)",
              res["state"] == "refused" and word in res["why"] and "только владелец" in res["why"] and not touches()
              and not D.cmds(), res)
finger(3)
res = act("type", "#t-card", PAY, text="4111")
check("[F1] type в форму с полем карты — отказ «оплата»", res["state"] == "refused" and "оплата" in res["why"]
      and not D.cmds(), res)
res = act("type", "#t-pw", IMP, text="x")
check("[F2] type в форму с паролем — отказ «важная форма»", res["state"] == "refused" and "важная" in res["why"]
      and not D.cmds(), res)
for sel in ("#pay", "#card"):
    head = f"[{TASK}] Отправить форму на avito.ru/p? Код"
    answer(T0 + 1, f"{head} 000000. Кнопка «Оплатить». Поля: «»")
    res = act("submit", sel, PAY)
    check(f"[F1] «да» на вопрос с этим адресом не снимает отказ оплаты ({sel})", res["state"] == "refused"
          and "оплата" in res["why"] and not D.cmds(), res)
for text, want in (("Опубликовать", "ordinary"), ("Сохранить черновик", "ordinary"), ("Найти", "ordinary"),
                   ("Торговый центр", "important"), ("Стереть", "delete"), ("Удалить 3 объявления", "delete-batch"),
                   ("Удалить объявление", "delete"), ("Удалить выбранные", "delete-batch"),
                   ("Удалить все", "delete-batch"), ("Удалить", "delete")):
    got = B.classify(facts(node("button", "submit", label=text), fields=[TITLE], form=FORM), "submit")[0]
    check(f"classify: «{text}» — {want}", got == want, got)
got = B.classify(facts(node("button", "submit", label="Удалить", attrs="btn item2"), fields=[TITLE], form=FORM),
                 "submit")[0]
check("classify: цифра в имени класса (item2) — не пачка", got == "delete", got)

# --- [C3] [T1]–[T3] обычная форма ----------------------------------------------------------------------------------
NEW = SITE + "/items/new"
finger(0)
res = act("submit", "#send", NEW)
args = touches()[-1] if touches() else ""
check("[C3][T1] обычная форма: палец в окне Touch ID — отправлено, одно нажатие, итог «по Touch ID»",
      res["state"] == "done" and "Touch ID" in res["text"] and len(D.clicked()) == 1, res)
check("[T4] окно отправки: задача, сайт и путь, кнопка, поля формы, кнопка отказа «Отказать»",
      TASK in args and "avito.ru/items/new" in args and "Опубликовать" in args and "Название=Диван" in args
      and "Цена=5000" in args and args.endswith(" 120 Отказать"), args)
finger(1)
res = act("submit", "#send", NEW)
check("[C3] отказ в окне Touch ID — не отправлено, «не повторяй», вопроса не выдано",
      res["state"] == "refused" and "отказал" in res["why"] and not D.clicked() and quoted(res["why"]) is None, res)
finger(2)
res = act("submit", "#send", NEW)
q1 = quoted(res.get("why"))
check("[T3] окно не показать (код 2) — отказ с вопросом «[ID] Отправить форму на avito.ru/items/new? Код …» и полями",
      res["state"] == "refused" and not D.clicked() and q1 and re.match(
          rf"\[{TASK}\] Отправить форму на avito\.ru/items/new\? Код [0-9a-f]{{6}}\. Кнопка «Опубликовать»\. Поля: "
          r"«Название=Диван; Цена=5000»$", q1), res)
res = act("submit", "#send", NEW)
check("[C3] повтор без ответа — тот же код (новый вопрос не плодится)", quoted(res.get("why")) == q1, res)
HELPER["path"] = None
os.environ["PANTHEON_FAKE_IDLE"] = "5"
res = act("submit", "#send", NEW)
check("[T3] помощник не собран — отказ «не собран» и тот же вопрос", res["state"] == "refused" and "не собран" in res["why"]
      and quoted(res["why"]) == q1, res)
HELPER["path"] = TOUCH
os.environ["PANTHEON_FAKE_IDLE"] = "900"
n_touch = len(touches())
for wrong, what in ((q1 + " Ещё: продвинуть", "лишний хвост"), (q1.split(" Кнопка")[0], "только начало с кодом"),
                    (q1.replace("Цена=5000", "Цена=500"), "другие поля")):
    answer(T0 + 2, wrong, "Да — отправить")
    res = act("submit", "#send", NEW)
    check(f"[B3] «да» на вопрос с тем же кодом, но другим текстом ({what}) — не согласие, нажатия нет",
          res["state"] == "refused" and not D.clicked() and quoted(res["why"]) == q1, res)
answer(T0 + 2, q1, "Да — отправить")
res = act("submit", "#send", NEW)
check("[C3][B3] «да» на вопрос с кодом целиком — отправлено по «да», окна Touch ID нет", res["state"] == "done"
      and "«да» владельца" in res["text"] and len(D.clicked()) == 1 and len(touches()) == n_touch, res)
res = act("submit", "#send", NEW)
q2 = quoted(res.get("why"))
check("[C6] одно «да» — одна отправка: повтор — новый код и новый вопрос, нажатия нет",
      res["state"] == "refused" and not D.clicked() and q2 and q2 != q1, res)

# [T2] [C12] форма изменилась, пока окно Touch ID ждало пальца
os.environ["PANTHEON_FAKE_IDLE"] = "5"
finger(0)
D.on_facts = lambda n: D.els[NEW]["#send"]["fields"][0].update(value="Диван-кровать") if n == 2 else None
res = act("submit", "#send", NEW)
D.on_facts = None
check("[T2][C12] палец, но форма изменилась, пока окно ждало, — отказ без нажатия",
      res["state"] == "refused" and "Touch ID" in res["why"] and not D.clicked(), res)
D.els[NEW]["#send"]["fields"][0]["value"] = "Диван"
finger(3)
os.environ["PANTHEON_FAKE_IDLE"] = "900"

# [C4] код одной задачи не действует для другой; [C1] галочка доски — не «да»
C4 = SITE + "/items/c4"
D.page(C4, {"#send": ORD})
os.environ["PANTHEON_FAKE_IDLE"] = "5"
finger(0)
res = run({**req("allow", site="avito.ru", actions="submit", why="x"), "task": "metis-0998"})
check("[C4] поручение задачи metis-0998 — своё", res["state"] == "done", res)
finger(3)
clear_touch()
os.environ["PANTHEON_FAKE_IDLE"] = "900"
res = act("submit", "#send", C4)
qc = quoted(res.get("why"))
answer(T0 + 2, qc, "Да — отправить")
D.calls.clear()
res = run({**req("submit", selector="#send"), "task": "metis-0998"})
check("[C4] «да» на код задачи metis-0999 не действует для metis-0998 — свой вопрос с [metis-0998]",
      res["state"] == "refused" and not D.clicked() and (quoted(res["why"]) or "").startswith("[metis-0998] "), res)
qb1 = quoted(res["why"])
with open(os.path.join(STATE, "owner-log", "board.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"kind": "answer", "id": "metis-0998", "time": time.strftime("%Y-%m-%dT%H:%M:%S",
                         time.localtime(T0 + 3)), "question": qb1, "answer": "Да — отправить"}, ensure_ascii=False) + "\n")
D.calls.clear()
res = run({**req("submit", selector="#send"), "task": "metis-0998"})
check("[C1] галочка на доске на этот вопрос — не согласие", res["state"] == "refused" and not D.clicked(), res)
res = act("submit", "#send", C4)
check("[C4] своя задача — по «да» отправлено", res["state"] == "done" and len(D.clicked()) == 1, res)

# [C5] форма изменилась после вопроса
answer(T0 + 3, q2, "Да — отправить")
D.els[NEW]["#send"]["fields"][1]["value"] = "50000"
res = act("submit", "#send", NEW)
q3 = quoted(res.get("why"))
check("[C5] форма изменилась после вопроса (цена 5000 → 50000: ввод, скрипт, stepUp) — «форма изменилась», новый "
      "вопрос с новыми полями", res["state"] == "refused" and "изменилась" in res["why"] and not D.clicked()
      and q3 and q3 != q2 and "Цена=50000" in q3, res)
D.els[NEW]["#send"]["fields"][1]["value"] = "5000"
res = act("submit", "#send", NEW)
check("[C5] форма вернулась к виду вопроса — «да» на прежний вопрос снова подходит", res["state"] == "done", res)
D.els[NEW]["#send"]["fields"].append(field("vip", "", type_="checkbox", label="VIP", checked=True))
answer(T0 + 4, q3, "Да — отправить")
res = act("submit", "#send", NEW)
check("[C5] отмечен флажок (reset, нажатие) — отпечаток другой, «да» не подходит", res["state"] == "refused"
      and not D.clicked(), res)
D.els[NEW]["#send"]["fields"].pop()

# [C4] [C10] адрес: путь и запрос
res = act("submit", "#send", NEW)
qx = quoted(res.get("why"))
answer(T0 + 5, qx, "Да — отправить")
for other in (SITE + "/items/other", SITE + "/items/new?draft=2"):
    res = act("submit", "#send", other)
    check(f"[C10] «да» на вопрос по /items/new не действует на {other[len(SITE):]} — новый вопрос с этим адресом",
          res["state"] == "refused" and not D.clicked() and quoted(res["why"]) and
          other[len("https://www."):] + "?" in quoted(res["why"]), res)
res = act("submit", "#send", NEW)
check("[C10] на прежнем адресе тот же ответ действует", res["state"] == "done", res)

# [C11] время «да» — время вопроса: ответ раньше выдачи кода не засчитан
at(T0 + 100)
res = act("submit", "#send", NEW)
qe = quoted(res.get("why"))
answer(T0 + 50, qe, "Да — отправить")
res = act("submit", "#send", NEW)
check("[C11] ответ записан раньше выдачи кода — не засчитан", res["state"] == "refused" and not D.clicked(), res)
answer(T0 + 101, qe, "Нет")
res = act("submit", "#send", NEW)
check("[C11] последний ответ «Нет» — не согласие", res["state"] == "refused" and not D.clicked(), res)
at(T0)

# [C13] форма уходит на другой сайт
D.page(SITE + "/x", {"#send": facts(SEND, fields=[TITLE], form={"action": "https://evil.com/collect", "label": ""}),
                     "#js": facts(SEND, fields=[TITLE], form={"action": "javascript:void(0)", "label": ""})})
finger(0)
for sel, word in (("#send", "evil.com"), ("#js", "не проверить")):
    res = act("submit", sel, SITE + "/x")
    check(f"[C13] форма уходит на другой сайт ({sel}) — отказ, окна нет", res["state"] == "refused" and word in res["why"]
          and not D.cmds(), res)
finger(3)

# [B2] действующие адрес и окно отправки: formaction и formtarget нажимаемой кнопки, target формы, <base target>
def tform(action=SITE + "/items/new", own=SITE + "/items/new", method="post", target=""):
    return {"action": action, "own": own, "method": method, "target": target, "label": ""}


D.page(SITE + "/y", {"#fa": facts(SEND, fields=[TITLE], form=tform(action="https://evil.com/collect")),
                     "#blank": facts(SEND, fields=[TITLE], form=tform(target="_blank")),
                     "#named": facts(SEND, fields=[TITLE], form=tform(target="result")),
                     "#self": facts(SEND, fields=[TITLE], form=tform(target="_self"))})
os.environ["PANTHEON_FAKE_IDLE"] = "5"
finger(0)
clear_touch()
for sel, word in (("#fa", "evil.com"), ("#blank", "_blank"), ("#named", "result")):
    res = act("submit", sel, SITE + "/y")
    check(f"[B2] {sel}: форма уходит не туда («{word}») — отказ даже с пальцем, окна Touch ID нет, нажатия нет",
          res["state"] == "refused" and word in res["why"] and not touches() and not D.clicked(), res)
res = act("submit", "#self", SITE + "/y")
check("[B2] formtarget _self — отправка как обычно (палец)", res["state"] == "done" and len(D.clicked()) == 1, res)
finger(3)
clear_touch()
base = facts(SEND, fields=[TITLE], form=tform())
for k, v in (("action", SITE + "/items/other"), ("own", SITE + "/items/other"), ("method", "get"),
             ("target", "_blank")):
    f2 = copy.deepcopy(base)
    f2["form"][k] = v
    check(f"[B2] form_digest: другое {k} формы — другой отпечаток (прежнее «да» не подходит)",
          B.form_digest(f2) != B.form_digest(base))
for form, what in ((tform(own=SITE + "/checkout"), "собственный action формы — /checkout"),
                   (tform(action="https://yoomoney.ru/quickpay"), "formaction кнопки — yoomoney.ru")):
    got = B.classify(facts(SEND, fields=[TITLE], form=form), "submit")[0]
    check(f"[B2] classify: {what} — оплата", got == "pay", got)
js = B.facts_js("#a")
check("[B2] FACTS_JS: адрес, метод и окно отправки — formaction, formmethod, formtarget кнопки, target формы, <base target>",
      all(x in js for x in ("at(sub, 'formaction')", "at(sub, 'formmethod')", "at(sub, 'formtarget')",
                            "at(f, 'target')", "base[target]", "own: abs(at(f, 'action'))")))

# --- [F3] удаление ------------------------------------------------------------------------------------------------
DEL = SITE + "/items"
ITEM_CB = [field("i1", "", type_="checkbox", checked=True), field("i2", "", type_="checkbox", checked=False)]
TWO_CB = [field("i1", "", type_="checkbox", checked=True), field("i2", "", type_="checkbox", checked=True)]
D.page(DEL, {"#del": facts(node("button", "submit", label="Удалить"), fields=ITEM_CB, form=FORM),
             "#del2": facts(node("button", "submit", label="Удалить"), fields=TWO_CB, form=FORM),
             "#delall": facts(node("button", "submit", label="Удалить все"), fields=ITEM_CB, form=FORM),
             "#trash": facts(node("button", "button", label="", attrs="trash-icon"), fields=ITEM_CB, form=FORM)})
reset_mandates()
give(actions="click,submit")
res = act("submit", "#del", DEL)
check("[F3] «Удалить» по поручению без delete — отказ «удаление … в поручении нет», окна нет",
      res["state"] == "refused" and "удаление" in res["why"] and not touches() and not D.cmds(), res)
reset_mandates()
give()
finger(0)
res = act("delete", "#del", DEL)
check("[F3] удаление одного элемента — палец в окне Touch ID, удалено", res["state"] == "done" and "удалено" in res["text"]
      and len(touches()) == 1 and "удалить элемент" in touches()[0] and len(D.clicked()) == 1, res)
res = act("submit", "#trash", DEL)
check("[F3] кнопка-корзина (trash в классе) через submit — удаление одного, палец", res["state"] == "done"
      and "удалено" in res["text"] and len(touches()) == 2, res)
for sel, n in (("#del2", "(2)"), ("#delall", "")):
    res = act("delete", sel, DEL)
    qb = quoted(res.get("why"))
    check(f"[F3][T1] удаление пачки {sel} — окна Touch ID нет даже с пальцем, отказ с вопросом «Удалить пачку{' ' + n if n else ''}»",
          res["state"] == "refused" and len(touches()) == 2 and not D.clicked() and "только «да»" in res["why"]
          and qb and qb.startswith(f"[{TASK}] Удалить пачку{' ' + n if n else ''} на avito.ru/items?"), res)
    answer(T0 + 6, qb, "Да — удалить")
    res = act("delete", sel, DEL)
    check(f"[F3] пачка {sel} — «да» на вопрос с кодом: удалено", res["state"] == "done" and len(D.clicked()) == 1
          and len(touches()) == 2, res)
finger(2)
res = act("delete", "#del", DEL)
qd = quoted(res.get("why"))
check("[F3] удаление одного без окна — вопрос «Удалить на …» для «да»", res["state"] == "refused"
      and qd and qd.startswith(f"[{TASK}] Удалить на avito.ru/items?"), res)
answer(T0 + 7, qd, "Да — удалить")
res = act("delete", "#del", DEL)
check("[F3] удаление одного — по «да»", res["state"] == "done" and len(D.clicked()) == 1, res)
finger(3)

# [B1] click: без согласия — только обычный класс; адрес ссылки — оплата, вход, удаление
L = SITE + "/l"
D.page(L, {"#pay-link": dict(facts(node("a", href=SITE + "/payment/42", label="Далее")), x=31.0),
           "#login-link": dict(facts(node("a", href=SITE + "/login?next=%2F", label="Далее")), x=32.0),
           "#del-link": dict(facts(node("a", href=SITE + "/item/7/delete", label="x")), x=33.0),
           "#rm-link": dict(facts(node("a", href=SITE + "/items?action=remove&id=3", label="ок")), x=34.0),
           "#destroy-link": dict(facts(node("a", href=SITE + "/item/9/destroy", label="ок")), x=35.0),
           "#cb-del": dict(facts(node("input", "checkbox", label="", attrs="удалить фото")), x=36.0),
           "#ok-link": dict(facts(node("a", href=SITE + "/item/7", label="x")), x=37.0)})
finger(0)
for sel, word in (("#pay-link", "оплата"), ("#login-link", "важная")):
    res = act("click", sel, L)
    check(f"[B1][F1][F2] click по ссылке {sel}: адрес href — отказ «{word}» даже с пальцем, окна нет, нажатия нет",
          res["state"] == "refused" and word in res["why"] and not touches() and not D.clicked(), res)
reset_mandates()
give(actions="click")
finger(0)
res = act("click", "#del-link", L)
check("[B1][F3] click по удаляющей ссылке (/delete) по поручению без delete — отказ, окна и нажатия нет",
      res["state"] == "refused" and "удаление" in res["why"] and not touches() and not D.clicked(), res)
reset_mandates()
give()
finger(0)
res = act("click", "#del-link", L)
check("[B1][F3][T1] click по удаляющей ссылке — как delete: окно Touch ID «удалить элемент», палец — удалено",
      res["state"] == "done" and "удалено" in res["text"] and len(touches()) == 1 and "удалить элемент" in touches()[0]
      and len(D.clicked()) == 1, res)
res = act("click", "#cb-del", L)
check("[B1][F3] click по флажку «удалить фото» — удаление: окно Touch ID", res["state"] == "done"
      and "удалено" in res["text"] and len(touches()) == 2, res)
finger(2)
for sel, path in (("#rm-link", "remove в запросе"), ("#destroy-link", "destroy в пути")):
    res = act("click", sel, L)
    qr = quoted(res.get("why"))
    check(f"[B1][F3] click по ссылке ({path}) без окна — вопрос «Удалить на avito.ru/l?», нажатия нет",
          res["state"] == "refused" and not D.clicked() and qr and qr.startswith(f"[{TASK}] Удалить на avito.ru/l?"), res)
n_touch = len(touches())
res = act("click", "#ok-link", L)
check("[B1] click по обычной ссылке того же сайта — без согласия и окна", res["state"] == "done"
      and "(link)" in res["text"] and len(D.clicked()) == 1 and len(touches()) == n_touch, res)
finger(3)
clear_touch()

# --- /cmd только из списка ------------------------------------------------------------------------------------------
try:
    B.cmd("comet", "Runtime.evaluate", {"expression": "1"})
    check("cmd(): метод вне CMD_ALLOWED — Fail", False)
except B.Fail:
    check("cmd(): метод вне CMD_ALLOWED — Fail", True)
src = open(os.path.join(LIB, "browser.py"), encoding="utf-8").read()
check("сырые команды: /cmd в browser.py — только внутри cmd(), список CMD_ALLOWED — две команды Input",
      src.count('"/cmd"') == 1 and B.CMD_ALLOWED == ("Input.dispatchMouseEvent", "Input.insertText")
      and not re.search(r'"/(?:close|events|console|close-tab)"', src))
used = set(re.findall(r'\bcmd\(\s*b,\s*"([\w.]+)"', src))
check("сырые команды: cmd(…) в коде зовут только методы CMD_ALLOWED", used and used <= set(B.CMD_ALLOWED), used)

# --- JS: синтаксис и маркеры -------------------------------------------------------------------------------------
node_bin = shutil.which("node")
if node_bin:
    for name, js in (("facts", B.facts_js("a[name=\"x\"]", True)), ("point", B.point_js("#a", 1.5, 2))):
        p = os.path.join(ROOT, f"{name}.js")
        with open(p, "w") as fh:
            fh.write(js + ";\n")
        r = subprocess.run([node_bin, "--check", p], capture_output=True, text=True, timeout=60)
        check(f"JS {name}: синтаксис (node --check)", r.returncode == 0, r.stderr[-300:])
else:
    print("пропущено: нет node — синтаксис JS не проверен")
check("селектор в JS — строкой JSON (кавычки и </script> не ломают выражение)",
      'const S = "a[x=\\"1\\"]";' in B.facts_js('a[x="1"]'))

# --- CLI ------------------------------------------------------------------------------------------------------------
base_env = {"HOME": HOME, "PANTHEON_HOME": PAN, "PANTHEON_STATE": STATE, "PANTHEON_NO_NOTIFY": "1",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
CACHES = os.path.join(HOME, "Library", "Caches", "pantheon-sandbox")
HQ_TMP = os.path.join(CACHES, "hq", "tmp")
os.makedirs(HQ_TMP)
win_env = dict(base_env, PANTHEON_TMP=HQ_TMP, PANTHEON_ROLE="charon")
qd = os.path.join(CACHES, "hq", "browser")
for argv, why in ((["click", "#a"], "--task"), (["allow", "avito.ru", "click", "--task", TASK], "--why"),
                  (["allow", "avito.ru", "pay", "--task", TASK, "--why", "x"], "pay"),
                  (["type", "#a", "--task", TASK], "ждём"), (["submit", "--task", TASK], "ждём")):
    r = subprocess.run([PY311, "-I", RUN_PY, "browser", *argv], env=win_env, capture_output=True, text=True, timeout=60)
    last = (r.stdout + r.stderr).strip().splitlines()[-1:]
    check(f"CLI {' '.join(argv)}: код 2, причина «{why}» последней строкой, заявки нет",
          r.returncode == 2 and last and why in last[0] and not (os.path.isdir(qd) and os.listdir(qd)), (r.returncode, last))
for argv, op, wait in ((["allow", "avito.ru", "click,submit", "--task", TASK, "--why", "объявление"], "allow", None),
                       (["click", "#agree", "--task", TASK], "click", None),
                       (["type", "#q", "диван", "--task", TASK], "type", None),
                       (["delete", "#d", "--task", TASK], "delete", None)):
    req_, w = B.parse(argv)
    check(f"parse {op}: поля заявки и ожидание {'300' if op in ('allow', 'delete') else '120'} с",
          req_["op"] == op and req_["task"] == TASK and w == (300 if op in ("allow", "delete") else 120)
          and (op != "allow" or (req_["site"], req_["actions"], req_["why"]) == ("avito.ru", "click,submit", "объявление"))
          and (op != "type" or req_["text"] == "диван"), (req_, w))
r = subprocess.run([PY311, "-I", RUN_PY, "browser", "submit", "#send", "--task", TASK, "--wait", "0"], env=win_env,
                   capture_output=True, text=True, timeout=60)
check("CLI submit из окна: заявка в ящике окна, код 0", r.returncode == 0 and os.path.isdir(qd)
      and len(os.listdir(qd)) == 1, (r.returncode, r.stdout, r.stderr))

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
