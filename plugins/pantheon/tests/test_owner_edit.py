#!/usr/bin/env python3
"""Правка файла владельца по «да» в окне вопросов Зевса или по Touch ID — без окна роли (metis-0910, lib/owner_edit.py).

Запуск: python3 -I plugins/pantheon/tests/test_owner_edit.py  (код выхода 0 — все прошли)
Временный HOME и STATE; окно Touch ID (owner_edit.ask), простой владельца и тревоги подменены, окружение прохода —
merge.TEST (clean_env). Проверяет по пунктам «Готово, когда»:
  [consent]  заявка → «да» в окне вопросов с sha диффа в вопросе → проход применил, хеши до и после в журнале;
  [отказ]    sha диффа в вопросе не тот, файл изменён после заявки, путь вне списка, ответ «нет», галочка на доске,
             ответ до заявки, заявка подменена, старая — не применено;
  [Touch ID] палец → применено и строка owner-edit-approve; отказ, время вышло, владелец не у Mac, правка не влезает в
             окно, заявка или файл сменились, пока окно открыто, — не применено;
  [проход]   из окна Claude Code — отказ; тик зовёт проход только при заявке.
"""
import atexit
import contextlib
import io
import json
import os
import shutil
import re
import stat
import string
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402

_ROOT = os.path.realpath(mkroot("owner-edit-"))
atexit.register(shutil.rmtree, _ROOT, True)
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE", "XDG_"))]:
    os.environ.pop(k)
BASE_ENV = {"PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"), "PANTHEON_NO_NOTIFY": "1",
            "PANTHEON_TEST": "1"}
os.environ.update(dict(BASE_ENV, HOME=HOME))
sys.path.insert(0, os.path.join(PLUGIN, "lib"))
import pantheon as P  # noqa: E402

OE = P.owner_edit_mod()
M = P.merge_mod()
M.TEST = {"env": BASE_ENV}
POLICY = os.path.join(HOME, ".claude", "pantheon", "policy.toml")
PARTS = os.path.join(HOME, ".claude", "agents", "_parts")
NAMES = os.path.join(PARTS, "names.part")
CACHES = os.path.join(HOME, "Library", "Caches", "pantheon-sandbox")
WORK = os.path.join(_ROOT, "work")
os.makedirs(WORK)
OLD = '[merge_repos]\nmetis-pantheon = ["latark/agent-kit"]\n'
NEW = '[merge_repos]\nmetis-pantheon = ["latark/agent-kit", "latark/other"]\n'

FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-800:]}]"))
    if not cond:
        FAILS.append(name)


ASKED, ALERTS = [], []
ANSWER = {"code": 0, "during": None}
IDLE = [0.0]


def fake_ask(text):
    ASKED.append(text)
    if ANSWER["during"]:
        ANSWER["during"]()
    return ANSWER["code"]


OE.ask = fake_ask
P.idle_sec = lambda: IDLE[0]
P.alert_once = lambda key, value, text, *a, **kw: ALERTS.append((key, value, text))


def quiet(fn, *a):
    out, errb = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errb):
        rc = fn(*a)
    return rc, out.getvalue(), errb.getvalue()


def write(p, text, mode=0o644):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(p, mode)


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def fresh(policy=OLD, code=0, during=None):
    """Чистое состояние: policy.toml и names.part как были, очереди, журналы и ответы пусты."""
    os.environ.clear()
    os.environ.update(dict(BASE_ENV, HOME=HOME))
    P.HOME, P.STATE = HOME, STATE
    for d in (os.path.join(STATE, "owner-edit"), os.path.join(STATE, "owner-log"), os.path.join(STATE, "logs"), CACHES):
        shutil.rmtree(d, ignore_errors=True)
    write(POLICY, policy)
    write(NAMES, "Зевс — он\n")
    ASKED.clear()
    ALERTS.clear()
    ANSWER.update(code=code, during=during)
    IDLE[0] = 0.0


def propose(target, text, task="metis-0910", window=None, why="добавить репозиторий"):
    src = os.path.join(WORK, "new.txt")
    write(src, text)
    if window:
        os.makedirs(os.path.join(CACHES, window, "tmp"), exist_ok=True)
        os.environ["PANTHEON_TMP"] = os.path.join(CACHES, window, "tmp")
        os.environ["PANTHEON_ROLE"] = "dev-opus"
    try:
        return quiet(OE.main, ["propose", target, "--from", src, "--task", task, "--why", why])
    finally:
        os.environ.pop("PANTHEON_TMP", None)
        os.environ.pop("PANTHEON_ROLE", None)


def reqs():
    out = []
    for d, win in OE.queue_dirs():
        with contextlib.suppress(OSError):
            for n in sorted(os.listdir(d)):
                if n.endswith(".req.json"):
                    out.append((os.path.join(d, n), json.loads(read(os.path.join(d, n))), win))
    return out


def answer(q, a, t=None, head="окно вопросов"):
    os.makedirs(os.path.join(STATE, "owner-log"), exist_ok=True)
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t if t is not None else time.time()))
    with open(os.path.join(STATE, "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write(f"\n## {when} · {head}\nвопрос: {q}\nответ: {a}\n")


def run():
    rc = quiet(OE.main, ["run"])
    os.environ.clear()                 # clean_env прохода сняла окружение теста — вернуть
    os.environ.update(dict(BASE_ENV, HOME=HOME))
    return rc


def journal():
    p = os.path.join(STATE, "logs", "owner-edit.jsonl")
    return [json.loads(ln) for ln in read(p).splitlines()] if os.path.exists(p) else []


def result(req, win=None):
    d = os.path.join(CACHES, win, "owner-edit") if win else os.path.join(STATE, "owner-edit", "queue")
    p = os.path.join(d, f"{req['id']}.result.json")
    return json.loads(read(p)) if os.path.exists(p) else {}


def approve_log():
    p = os.path.join(STATE, "owner-log", "owner-edit-approve.log")
    return read(p) if os.path.exists(p) else ""


def short(req):
    return req["diff_sha"][:OE.SHORT]


def raises(fn, *a):
    try:
        fn(*a)
    except OE.Refuse:
        return True
    return False


def yes_question(req):
    return OE.question(req)


MD_ACTIVE = frozenset("\\`*_~[]<>&!|")   # знаки, которые разметка CommonMark и GFM может съесть или переделать


def seen(s):
    """Эталон отрисовки вопроса в чате (CommonMark, худший случай): «\\» перед знаком ASCII-пунктуации — сам знак;
    неэкранированный знак разметки (`код`, *курсив*, ~зачёркнутое~, [ссылка], <тег>, &сущность;, «\\») пропадает;
    прочее — как есть. «[id] » в начале вопроса — как есть."""
    m = re.match(r"\[" + OE.ID_RE.pattern + r"\] ", s)
    head, s = (m[0], s[m.end():]) if m else ("", s)
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in string.punctuation:
            out.append(s[i + 1])
            i += 2
            continue
        if s[i] not in MD_ACTIVE:
            out.append(s[i])
        i += 1
    return head + "".join(out)


def sha_file(p):
    return OE.sha(open(p, "rb").read())


# --- [consent] заявка → «да» с sha диффа в вопросе → применено, хеши в журнале -----------------------------------
fresh()
os.chmod(POLICY, 0o640)
before = sha_file(POLICY)
rc, out, errs = propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
q = reqs()
check("propose: заявка в кэше окна роли", rc == 0 and len(q) == 1 and q[0][2] == "metis-pantheon", (rc, out, errs, q))
path0, req, _ = q[0]
check("propose: в выводе вопрос Зевсу с [id] и sha диффа", f"[{req['id']}]" in out and short(req) in out, out)
check("propose: заявка с sha до, sha после и диффом", req["before"] == before and req["after"] == OE.sha(NEW)
      and '+metis-pantheon = ["latark/agent-kit", "latark/other"]' in req["diff"], req)
check("propose: файл роль не трогала", read(POLICY) == OLD)
rc, out, _ = run()
check("без ответа и без пальца (окно Touch ID — отказ 1 не задан) — проход спросил Touch ID", len(ASKED) == 1, ASKED)
fresh()
os.chmod(POLICY, 0o640)
rc, out, _ = propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
path0, req, _ = reqs()[0]
IDLE[0] = 10 ** 6   # владельца нет у Mac — только «да»
run()
check("нет ответа и владельца нет у Mac — не применено, заявка ждёт", read(POLICY) == OLD and os.path.exists(path0)
      and not ASKED)
answer(yes_question(req), "А — Да, применить")
rc, out, errs = run()
check("«да» с sha диффа в вопросе — применено", read(POLICY) == NEW, (out, errs, result(req, "metis-pantheon")))
j = journal()
check("журнал: хеши до и после, как согласовано", len(j) == 1 and j[0]["before"] == before
      and j[0]["after"] == OE.sha(NEW) and j[0]["how"] == "consent" and j[0]["state"] == "done"
      and j[0]["window"] == "metis-pantheon" and "у Зевса" in j[0]["evidence"], j)
check("итог роли — done", result(req, "metis-pantheon").get("state") == "done", result(req, "metis-pantheon"))
check("права файла прежние", stat.S_IMODE(os.stat(POLICY).st_mode) == 0o640, oct(os.stat(POLICY).st_mode))
check("заявка снята — второй раз не применится", not os.path.exists(path0) and not reqs())
check("Touch ID не спрашивали и строки owner-edit-approve нет (одно из двух)", not ASKED and approve_log() == "")
write(POLICY, OLD)
run()
check("повторный проход файл не трогает", read(POLICY) == OLD and len(journal()) == 1)

# names.part вне окна — очередь STATE
fresh()
rc, out, errs = propose("~/.claude/agents/_parts/names.part", "Зевс — он\nМетида — она\n")
_, req, win = reqs()[0]
check("names.part вне окна: заявка в STATE", rc == 0 and win is None, (rc, errs))
answer(yes_question(req), "Да")
IDLE[0] = 10 ** 6
run()
check("names.part: применено по «да»", read(NAMES) == "Зевс — он\nМетида — она\n", journal())

# --- [отказ] -------------------------------------------------------------------------------------------------------
fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
IDLE[0] = 10 ** 6
answer(yes_question(req).replace(short(req), "0" * OE.SHORT), "А — Да, применить")
run()
check("sha диффа в вопросе не тот — не применено", read(POLICY) == OLD, journal())
check("sha не тот: заявка снята с отказом", not os.path.exists(path0) and result(req).get("state") == "refused",
      result(req))

fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
IDLE[0] = 10 ** 6
answer(yes_question(req), "Б — Нет")
run()
check("ответ «нет» — не применено, отклонено", read(POLICY) == OLD and result(req).get("state") == "declined",
      result(req))

fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
write(POLICY, OLD + "# правка владельца\n")
answer(yes_question(req), "А — Да, применить")
run()
check("файл изменён после заявки — не применено", read(POLICY) == OLD + "# правка владельца\n" and not ASKED,
      (read(POLICY), journal()))
check("файл изменён: отказ с причиной", result(req).get("state") == "refused" and "изменился" in result(req)["note"],
      result(req))

fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
write(POLICY, OLD + "# правка владельца\n")
run()
check("файл изменён, ответа нет — отказ без окна Touch ID", not ASKED and result(req).get("state") == "refused"
      and read(POLICY) == OLD + "# правка владельца\n", (ASKED, result(req)))

# новый текст подменён целиком, sha после, дифф и sha диффа пересчитаны под него: проверка текста — и в проходе
for target_, bad_new, what in (("~/.claude/pantheon/policy.toml", "[merge_repos\n", "не TOML"),
                               ("~/.claude/agents/_parts/names.part", "x" * (OE.NEW_MAX + 1), "больше предела")):
    fresh()
    propose(target_, NEW)
    path0, req, _ = reqs()[0]
    IDLE[0] = 10 ** 6
    p_ = OE.target(req["file"])
    d_ = OE.make_diff(req["file"], read(p_), bad_new)
    bad = dict(req, new=bad_new, after=OE.sha(bad_new), diff=d_,
               diff_sha=OE.diff_sha(req["file"], req["before"], OE.sha(bad_new), d_))
    write(path0, json.dumps(bad))
    answer(OE.question(bad), "А — Да, применить")
    run()
    check(f"заявка с новым текстом {what} (согласованная) — не применено", read(p_) != bad_new
          and result(req).get("state") == "refused", result(req))

fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
IDLE[0] = 10 ** 6
answer(yes_question(req), "А — Да, применить", t=time.time() - 3600)
run()
check("ответ раньше заявки — не в счёт", read(POLICY) == OLD and os.path.exists(path0))

fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
IDLE[0] = 10 ** 6
os.makedirs(os.path.join(STATE, "owner-log"), exist_ok=True)
with open(os.path.join(STATE, "owner-log", "board.jsonl"), "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"kind": "answer", "id": req["id"], "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                         "question": yes_question(req), "answer": "А — Да, применить"}) + "\n")
run()
check("галочка на доске — не согласие на правку", read(POLICY) == OLD and os.path.exists(path0))
answer(yes_question(req), "А — Да, применить", head="ответ в чате")
run()
check("ответ в чате Зевсу — согласие", read(POLICY) == NEW)

fresh()
for bad in ("~/.claude/settings.json", "~/.claude/agents/_parts/names.md", "~/.claude/agents/names.part",
            "~/.claude/agents/_parts/../names.part", "/etc/hosts"):
    write(os.path.join(HOME, ".claude", "settings.json"), "{}\n")
    rc, _, errs = propose(bad, NEW)
    check(f"путь вне списка ({bad}) — отказ, заявки нет", rc == 2 and not reqs() and "не из списка" in errs, (rc, errs))
check("settings.json не тронут", read(os.path.join(HOME, ".claude", "settings.json")) == "{}\n")

fresh()
real = os.path.join(_ROOT, "elsewhere")
os.makedirs(real, exist_ok=True)
write(os.path.join(real, "names.part"), "x\n")
shutil.rmtree(PARTS)
os.symlink(real, PARTS)
rc, _, errs = propose("~/.claude/agents/_parts/names.part", "y\n")
check("папка _parts — ссылка: отказ", rc == 2 and not reqs() and "ссылка" in errs, errs)
os.unlink(PARTS)
fresh()
os.unlink(POLICY)
os.symlink(os.path.join(real, "names.part"), POLICY)
rc, _, errs = propose("~/.claude/pantheon/policy.toml", NEW)
check("policy.toml — ссылка: отказ", rc == 2 and not reqs(), errs)
os.unlink(POLICY)

fresh()
rc, _, errs = propose("~/.claude/pantheon/policy.toml", "[merge_repos\n")
check("новый policy.toml — не TOML: отказ", rc == 2 and not reqs() and "TOML" in errs, errs)
rc, _, errs = propose("~/.claude/pantheon/policy.toml", OLD)
check("новый текст тот же — отказ", rc == 2 and not reqs(), errs)
rc, _, errs = propose("~/.claude/pantheon/policy.toml", NEW, task="не-задача")
check("без задачи вида id — отказ", rc == 2 and not reqs(), errs)

# заявку подменили: файл назначения или новый текст при прежнем sha диффа
fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
IDLE[0] = 10 ** 6
write(path0, json.dumps(dict(req, new=NEW + "evil = 1\n")))
answer(yes_question(req), "А — Да, применить")
run()
check("новый текст подменён при том же sha диффа — не применено", read(POLICY) == OLD
      and result(req).get("state") == "refused", result(req))
fresh()
settings = os.path.join(HOME, ".claude", "settings.json")
write(settings, OLD)
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
IDLE[0] = 10 ** 6
diff = OE.make_diff(".claude/settings.json", OLD, NEW)
evil = dict(req, file=".claude/settings.json", diff=diff,
            diff_sha=OE.diff_sha(".claude/settings.json", req["before"], req["after"], diff))
write(path0, json.dumps(evil))
answer(OE.question(evil), "А — Да, применить")
run()
check("заявка на файл вне списка — снята как негодная, файл не тронут", read(settings) == OLD
      and not os.path.exists(path0) and result(evil) == {} and not journal(), (result(evil), journal()))

# каждое поле сверки отдельно: sha после, дифф, sha диффа (остальное в заявке — как было)
for field, value in (("after", "0" * 64), ("diff", None), ("diff_sha", "1" * 64)):
    fresh()
    propose("~/.claude/pantheon/policy.toml", NEW)
    path0, req, _ = reqs()[0]
    IDLE[0] = 10 ** 6
    bad = dict(req, **{field: value if value else req["diff"].replace("latark/other", "latark/evil")})
    write(path0, json.dumps(bad))
    answer(OE.question(bad), "А — Да, применить")
    run()
    check(f"заявка: {field} не сходится с файлом и новым текстом — не применено", read(POLICY) == OLD
          and result(req).get("state") == "refused", result(req))

fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
IDLE[0] = 10 ** 6
answer(yes_question(req).replace(short(req), "ab" + short(req)), "А — Да, применить")
run()
check("sha диффа внутри другого числа — не тот sha", read(POLICY) == OLD and result(req).get("state") == "refused")

fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
IDLE[0] = 10 ** 6
answer(yes_question(req), "А — Да, применить")
answer(yes_question(req), "Б — Нет", t=time.time() + 1)
run()
check("решает последний ответ: «да», потом «нет» — отклонено", read(POLICY) == OLD
      and result(req).get("state") == "declined", result(req))

check("путь вне списка: rel_of и target отказывают сами", OE.rel_of("~/.claude/settings.json") is None
      and OE.rel_of(os.path.join(HOME, ".claude", "pantheon", "policy.toml")) == ".claude/pantheon/policy.toml"
      and raises(OE.target, ".claude/settings.json") and raises(OE.target, "../.claude/pantheon/policy.toml"))
fresh()
os.link(POLICY, os.path.join(WORK, "hard"))
rc, _, errs = propose("~/.claude/pantheon/policy.toml", NEW)
os.unlink(os.path.join(WORK, "hard"))
check("policy.toml с жёсткой ссылкой — отказ", rc == 2 and not reqs() and "не обычный" in errs, errs)
os.unlink(POLICY)
os.mkfifo(POLICY)
rc, _, errs = propose("~/.claude/pantheon/policy.toml", NEW)
os.unlink(POLICY)
check("policy.toml — не обычный файл — отказ", rc == 2 and not reqs() and "не обычный" in errs, errs)
fresh(policy=OLD + "#" * OE.NEW_MAX)
rc, _, errs = propose("~/.claude/pantheon/policy.toml", NEW)
check("policy.toml больше предела — отказ", rc == 2 and not reqs() and "КБ" in errs, errs)
fresh()
rc, _, errs = propose("~/.claude/agents/_parts/names.part", "Зевс\x00\n")
check("новый текст с NUL — отказ", rc == 2 and not reqs() and "NUL" in errs, errs)
rc, _, errs = propose("~/.claude/agents/_parts/names.part", "x" * (OE.NEW_MAX + 1))
check("новый текст больше предела — отказ", rc == 2 and not reqs(), errs)

fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
write(path0, json.dumps(dict(req, created=time.time() - OE.REQ_TTL - 60)))
answer(yes_question(req), "А — Да, применить")
run()
check("заявка старше суток — снята, не применено", read(POLICY) == OLD and result(req).get("state") == "dropped",
      result(req))

# --- [Touch ID] ------------------------------------------------------------------------------------------------------
fresh()
propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
path0, req, _ = reqs()[0]
run()
check("Touch ID: окно с правкой целиком и sha диффа", len(ASKED) == 1 and short(req) in ASKED[0]
      and '+metis-pantheon = ["latark/agent-kit", "latark/other"]' in ASKED[0] and "metis-pantheon" in ASKED[0], ASKED)
check("Touch ID: палец — применено", read(POLICY) == NEW, (journal(), result(req, "metis-pantheon")))
check("Touch ID: строка owner-edit-approve с sha диффа", f"owner-edit-approve {req['id']} {req['diff_sha']}"
      in approve_log(), approve_log())
check("Touch ID: журнал how=touchid, хеши до и после", journal() and journal()[-1]["how"] == "touchid"
      and journal()[-1]["before"] == req["before"] and journal()[-1]["after"] == OE.sha(NEW), journal())

fresh(code=1)
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
run()
check("Touch ID: отказ — не применено, отклонено", read(POLICY) == OLD and result(req).get("state") == "declined"
      and approve_log() == "", result(req))

fresh(code=3)
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
run()
run()
check("Touch ID: время вышло — не применено, повтор не раньше RETRY_SEC", read(POLICY) == OLD and len(ASKED) == 1
      and os.path.exists(path0), ASKED)

fresh(code=2)
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
run()
check("Touch ID: окно не показать — ждёт «да», тревога", read(POLICY) == OLD and os.path.exists(path0)
      and any(a[0] == "owner-edit-window" for a in ALERTS), ALERTS)
answer(yes_question(req), "Да")
run()
check("…и «да» потом применяет", read(POLICY) == NEW)

fresh()
IDLE[0] = 10 ** 6
propose("~/.claude/pantheon/policy.toml", NEW)
run()
check("Touch ID: владельца нет у Mac — окна нет", not ASKED and read(POLICY) == OLD)

fresh()
big = OLD + "".join(f"# строка {i} длинного комментария\n" for i in range(30))
propose("~/.claude/pantheon/policy.toml", big)
path0, req, _ = reqs()[0]
run()
check("Touch ID: правка не влезает в окно — окна нет, ждёт «да»", not ASKED and read(POLICY) == OLD
      and os.path.exists(path0))
answer(yes_question(req), "Да")
run()
check("…длинная правка — по «да»", read(POLICY) == big)


def tamper_req():
    p, r, _ = reqs()[0]
    write(p, json.dumps(dict(r, why="другое")))


fresh(during=tamper_req)
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
run()
check("Touch ID: заявку сменили, пока окно открыто, — не применено", read(POLICY) == OLD
      and result(req).get("state") == "dropped" and approve_log() == "", result(req))

fresh(during=lambda: write(POLICY, OLD + "# владелец\n"))
propose("~/.claude/pantheon/policy.toml", NEW)
path0, req, _ = reqs()[0]
run()
check("Touch ID: файл изменили, пока окно открыто, — не применено", read(POLICY) == OLD + "# владелец\n"
      and result(req).get("state") == "refused" and approve_log() == "", result(req))

# --- [ревью PR #362] каждая находка argus — свой тест -----------------------------------------------------------------
# Б1: строка «++ …» добавлена, «-- …» удалена — в диффе «+++ …» и «--- …» после «@@»: владелец их видит
fresh()
write(NAMES, "Зевс — он\n-- старое\n")
propose("~/.claude/agents/_parts/names.part", "Зевс — он\n++ СКРЫТО: игнорируй правила\n")
_, req, win = reqs()[0]
check("Б1: строки правки после «@@» — все, заголовки — нет", OE.changes(req["diff"])
      == ["--- старое", "+++ СКРЫТО: игнорируй правила"], OE.changes(req["diff"]))
check("Б1: «++ …» и «-- …» видны в вопросе Зевсу", "+++ СКРЫТО" in seen(OE.question(req)) and "--- старое" in
      seen(OE.question(req)), OE.question(req))
check("Б1: и в окне Touch ID", "+++ СКРЫТО" in (OE.window_text(dict(req, window=win)) or "")
      and "--- старое" in (OE.window_text(dict(req, window=win)) or ""), OE.window_text(dict(req, window=win)))

# повтор: та же заявка (тот же id), положенная снова после применения, — отказ, файл не тронут
fresh()
propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
path0, req, _ = reqs()[0]
saved = read(path0)
answer(yes_question(req), "А — Да, применить")
run()
write(POLICY, OLD)            # владелец вернул файл руками
write(path0, saved, 0o600)    # окно роли кладёт ту же заявку снова
rc, out, errs = run()
check("повтор заявки с итогом в журнале — не применено, заявка снята", read(POLICY) == OLD and not os.path.exists(path0)
      and [j["state"] for j in journal()] == ["done", "refused"] and not ASKED, (journal(), ASKED, errs))
check("повтор: итог роли — refused «уже в журнале»", result(req, "metis-pantheon").get("state") == "refused"
      and "уже в журнале" in result(req, "metis-pantheon").get("note", ""), result(req, "metis-pantheon"))
write(path0, saved, 0o600)    # и Touch ID на повтор не спрашивают
os.remove(os.path.join(STATE, "owner-log", "zeus.md"))
run()
check("повтор: без «да» окна Touch ID нет, файл не тронут", read(POLICY) == OLD and not ASKED, ASKED)

# Д1: итог роли не записать (на его месте папка) — журнал есть, проход не упал
fresh()
propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
path0, req, _ = reqs()[0]
os.makedirs(os.path.join(CACHES, "metis-pantheon", "owner-edit", f"{req['id']}.result.json", "x"))
answer(yes_question(req), "А — Да, применить")
rc, out, errs = run()
check("Д1: итог роли не записать — применено, в журнале done с хешами", read(POLICY) == NEW and rc == 0
      and [(j["state"], j.get("after")) for j in journal()] == [("done", OE.sha(NEW))], (rc, journal(), ALERTS))
check("Д1: тревога «итог роли не записан», временных файлов нет", [a[0] for a in ALERTS] == ["owner-edit-result"]
      and not [n for n in os.listdir(os.path.join(CACHES, "metis-pantheon", "owner-edit")) if n.endswith(".tmp")],
      (ALERTS, os.listdir(os.path.join(CACHES, "metis-pantheon", "owner-edit"))))
# Д1: журнал не дописать — файл владельца не трогается
fresh()
propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
path0, req, _ = reqs()[0]
os.makedirs(os.path.join(STATE, "logs"))
write(os.path.join(STATE, "logs", "owner-edit.jsonl"), "", 0o400)
answer(yes_question(req), "А — Да, применить")
rc, out, errs = run()
os.chmod(os.path.join(STATE, "logs", "owner-edit.jsonl"), 0o600)
check("Д1: журнал не дописать — файл не тронут, код 1", read(POLICY) == OLD and rc == 1, (rc, ALERTS))

# Д2: «да» на пересказ правки с верным sha (или вопрос с припиской) — не согласие; ёлочки и пробелы — как у хука
for qtext, label in ((lambda r: f"[{r['id']}] Применить правку ~/.claude/pantheon/policy.toml (задача {r['task']}, sha "
                      f"диффа {short(r)})? Правка: безобидная строка", "пересказ с верным sha"),
                     (lambda r: OE.question(r) + " и ещё удалить approvals.toml", "вопрос с припиской")):
    fresh()
    propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
    path0, req, _ = reqs()[0]
    answer(qtext(req), "А — Да, применить")
    IDLE[0] = 10 ** 6
    run()
    check(f"Д2: «да» на {label} — не применено, отказ", read(POLICY) == OLD
          and result(req, "metis-pantheon").get("state") == "refused", result(req, "metis-pantheon"))
fresh()
propose("~/.claude/agents/_parts/names.part", "Зевс — он\nМетида — «она»\n")
_, req, _ = reqs()[0]
answer(OE.one_line(OE.question(req)), "Да")   # хук окна вопросов: ёлочки — пробел, пробелы — один
IDLE[0] = 10 ** 6
run()
check("Д2: вопрос, записанный хуком (ёлочки сняты), — применено", read(NAMES) == "Зевс — он\nМетида — «она»\n",
      journal())

# Д created: дата заявки в будущем не держит её дольше суток — время по файлу заявки
fresh()
propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
path0, req, _ = reqs()[0]
write(path0, json.dumps(dict(req, created=time.time() + 10 ** 8)), 0o600)
IDLE[0] = 10 ** 6
real_now = P.now
P.now = lambda: real_now() + 2 * 86400
try:
    run()
finally:
    P.now = real_now
check("Д created: created в будущем, прошло 2 дня — заявка снята", not os.path.exists(path0)
      and result(req, "metis-pantheon").get("state") == "dropped" and read(POLICY) == OLD, result(req, "metis-pantheon"))

# Д dir_fd: папку очереди подменили ссылкой после открытия — итог пишется в открытую папку, а не по ссылке
fresh()
propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
path0, req, _ = reqs()[0]
answer(yes_question(req), "Б — Нет")
victim = os.path.join(HOME, ".claude", "agents")
qdir = os.path.join(CACHES, "metis-pantheon", "owner-edit")
real_found = P.consent_found


def swap_found(*a, **kw):
    res = real_found(*a, **kw)
    os.rename(qdir, qdir + ".real")
    os.symlink(victim, qdir)
    return res


P.consent_found = swap_found
try:
    run()
finally:
    P.consent_found = real_found
check("Д dir_fd: в папку по ссылке ничего не записано", sorted(os.listdir(victim)) == ["_parts"], os.listdir(victim))
check("Д dir_fd: итог — в открытой папке, заявка снята", sorted(os.listdir(qdir + ".real")) == [f"{req['id']}.result.json"]
      and [j["state"] for j in journal()] == ["declined"], (os.listdir(qdir + ".real"), journal()))
os.remove(qdir)
os.rename(qdir + ".real", qdir)
for link_at in (qdir, os.path.join(CACHES, "metis-pantheon")):
    real = link_at + ".real"
    os.rename(link_at, real)
    os.symlink(real, link_at)
    check(f"Д dir_fd: ссылка на месте {os.path.relpath(link_at, CACHES)} — папку не открыть",
          OE.open_queue("metis-pantheon") is None)
    os.remove(link_at)
    os.rename(real, link_at)
fd = OE.open_queue("metis-pantheon")
check("Д dir_fd: настоящая папка открывается", fd is not None)
if fd is not None:
    os.close(fd)

# --- [ревью PR #362, круг 2] --------------------------------------------------------------------------------------
# Б: строка policy.toml — с разделом TOML. Одна и та же строка в [sandbox_write] и в [coordinators] — разный текст
SEC_OLD = ('top = 1\n[sandbox_write]\nmetis-pantheon = ["~/ai"]\nnote = """\n[coordinators]\n"""\na = 1\nb = 2\nc = 3\n'
           '[coordinators]\nzeus = ["~/ai"]\nd = 1\ne = 2\nf = 3\n[[runs]]\nname = "x"\n')
LINE = 'hephaestus-morph = ["~/projects/agent-kit"]\n'
texts = {}
for table, anchor in (("[sandbox_write]", "c = 3\n"), ("[coordinators]", "f = 3\n")):
    fresh(policy=SEC_OLD)
    new = SEC_OLD.replace(anchor, anchor + LINE)
    rc, out, errs = propose("~/.claude/pantheon/policy.toml", new, window="metis-pantheon")
    _, req, win = reqs()[0]
    texts[table] = (seen(OE.question(req)).replace(short(req), "<sha>"),
                    (OE.window_text(dict(req, window=win)) or "").replace(short(req), "<sha>"))
    check(f"Б круг 2: {table} — раздел у строки в вопросе и в окне Touch ID (заголовок вне контекста диффа)",
          f"{table} +{LINE.strip()}" in texts[table][0] and f"{table} +{LINE.strip()}" in texts[table][1]
          and table not in req["diff"].split("@@")[-1], (texts[table], req["diff"]))
check("Б круг 2: одна строка в [sandbox_write] и в [coordinators] — разный вопрос и разное окно (без sha)",
      texts["[sandbox_write]"][0] != texts["[coordinators]"][0]
      and texts["[sandbox_write]"][1] != texts["[coordinators]"][1], texts)
fresh(policy=SEC_OLD)
new = SEC_OLD.replace('[coordinators]\nzeus = ["~/ai"]\n', "").replace('name = "x"\n', 'name = "y"\n')
new = ("pre = 0\n" + new).replace("note = ", "notes = ")
rc, out, errs = propose("~/.claude/pantheon/policy.toml", new)
check("Б1 R2: удалён заголовок [coordinators] — d, e, f ушли в [sandbox_write]: propose отказал",
      rc != 0 and not reqs() and "sandbox_write.d" in errs, errs)
req = {"file": ".claude/pantheon/policy.toml", "new": new, "diff": OE.make_diff(".claude/pantheon/policy.toml",
                                                                               SEC_OLD, new)}
rows = OE.shown(req)
check("Б круг 2: «-» — раздел старого текста, «+» — нового; [x] в многострочной строке — не заголовок; [[таблица]]",
      rows == ["(вне таблиц) +pre = 0", '[sandbox_write] -note = """', '[sandbox_write] +notes = """',
               "[coordinators] -[coordinators]", '[coordinators] -zeus = ["~/ai"]', '[[runs]] -name = "x"',
               '[[runs]] +name = "y"'], rows)
for old_t, new_t in ((SEC_OLD, new), ("a\nb", "a\nc"), ("a\nb\n", "a\nb"), ("x\n", "y\nx\n"), ("x\ny\n", "x\n"),
                     ("".join(f"{i}\n" for i in range(30)), "".join(f"{i}\n" for i in range(30) if i not in (3, 20)))):
    d = OE.make_diff("f.toml", old_t, new_t)
    check(f"Б круг 2: старый текст из нового и диффа — тот же ({old_t[:12]!r} → {new_t[:12]!r})",
          OE.old_text("f.toml", new_t, d) == old_t, OE.old_text("f.toml", new_t, d))
check("Б круг 2: дифф не от этого нового текста — старый не восстановить, раздел «[?]»",
      OE.old_text("f.toml", "q\n", OE.make_diff("f.toml", "a\n", "b\n")) is None
      and OE.shown({"file": ".claude/pantheon/policy.toml", "diff": OE.make_diff("f.toml", "[t]\na = 1\n", "[t]\n"),
                    "new": "zzz = 2\n"}) == ["[?] -a = 1"])
check("Б круг 2 / R3-2 Д1: .part без заголовков — раздел «(вне разделов)»",
      OE.shown({"file": ".claude/agents/_parts/names.part", "new": "b\n",
                "diff": OE.make_diff(".claude/agents/_parts/names.part", "a\n", "b\n")})
      == ["(вне разделов) -a", "(вне разделов) +b"])

# Д: невидимые и bidi-знаки в новом тексте и в --why — отказ в propose; \t и \n — можно
check("Д круг 2: HIDDEN — те же категории, что handoff.BAD_CHARS (окно Touch ID)",
      tuple(OE.HIDDEN) == tuple(P.handoff_mod().BAD_CHARS))
for ch in ("\u200b", "\u202e", "\U000e0000", "\U000e0070", "\r", "\u2028"):
    fresh()
    rc, out, errs = propose("~/.claude/agents/_parts/names.part", f"Зевс — он\nok{ch}push\n")
    check(f"Д круг 2: знак U+{ord(ch):04X} в новом тексте — отказ, заявки нет", rc != 0 and not reqs()
          and f"U+{ord(ch):04X}" in errs and "строка 2" in errs, (rc, errs))
fresh()
rc, out, errs = propose("~/.claude/agents/_parts/names.part", "Зевс — он\n\tотступ\n")
check("Д круг 2: табуляция в новом тексте — заявка есть", rc == 0 and len(reqs()) == 1, errs)
fresh()
rc, out, errs = propose("~/.claude/agents/_parts/names.part", "Зевс — он\nМетида\n", why="ok\u202eон")
check("Д круг 2: bidi-знак в --why — отказ", rc != 0 and not reqs() and "U+202E" in errs, errs)
fresh()
write(NAMES, "Зевс — он\n")
propose("~/.claude/agents/_parts/names.part", "Зевс — он\nМетида\n")
path0, req, _ = reqs()[0]
write(path0, json.dumps(dict(req, new="Зевс — он\nМетида\u200b\n")), 0o600)   # заявку подменили в обход propose
IDLE[0] = 0.0
run()
check("Д круг 2: невидимый знак в заявке, положенной в обход propose, — отказ в проходе, окна нет",
      read(NAMES) == "Зевс — он\n" and not ASKED and result(req).get("state") == "refused", (ASKED, result(req)))

# Д: невидимый знак в старом тексте файла владельца — в вопросе и окне Touch ID экранирован (R3 Б1, mark), окно есть
fresh()
write(NAMES, "Зевс — он\nстарое\u200bскрыто\n")
rc, out, errs = propose("~/.claude/agents/_parts/names.part", "Зевс — он\n")
_, req, win = reqs()[0]
check("Д круг 2 / R3 Б1: невидимый знак в строке правки — \\u200b в вопросе и в окне Touch ID, а не сам знак",
      "-старое\\u200bскрыто" in seen(OE.question(req))
      and "-старое\\u200bскрыто" in (OE.window_text(dict(req, window=win)) or ""), (OE.question(req), out))
ANSWER["code"] = 1   # палец не приложен: проверяется только текст окна
IDLE[0] = 0.0
run()
check("Д круг 2 / R3 Б1: проход показал окно с \\u200b, без самого знака", len(ASKED) == 1 and "\\u200b" in ASKED[0]
      and not OE.hidden_at(ASKED[0], "") and read(NAMES)
      == "Зевс — он\nстарое\u200bскрыто\n", ASKED)

# Д: строки правки — через « ⏎ », знак ⏎ внутри строки экранирован: «ok ⏎ -Правило» — одна добавленная строка
fresh()
rc, out, errs = propose("~/.claude/agents/_parts/names.part", "Зевс — он\nok ⏎ -Правило; -Ещё\n")
_, req, win = reqs()[0]
q = seen(OE.question(req))
check("Д круг 2: ⏎ в строке экранирован, строк 1 — в вопросе и в окне",
      "Правка, строк 1: (вне разделов) +ok \\u23ce -Правило; -Ещё. Пояснение роли:" in q
      and (OE.window_text(dict(req, window=win)) or "").endswith("строк 1: (вне разделов) +ok \\u23ce -Правило; -Ещё"),
      (q, OE.window_text(dict(req, window=win))))
fresh()
propose("~/.claude/agents/_parts/names.part", "Метида — она\n")
_, req, win = reqs()[0]
check("Д круг 2: две строки правки — через « ⏎ », а не «; »", seen(OE.question(req)).endswith(
      "Правка, строк 2: (вне разделов) -Зевс — он ⏎ (вне разделов) +Метида — она. Пояснение роли: добавить "
      "репозиторий") and (OE.window_text(dict(req, window=win)) or "").endswith(
      "строк 2: (вне разделов) -Зевс — он ⏎ (вне разделов) +Метида — она"),
      (OE.question(req), OE.window_text(dict(req, window=win))))
answer(yes_question(req), "А — Да, применить")
run()
check("Д круг 2: «да» на вопрос с « ⏎ » (как пишет хук) — применено", read(NAMES) == "Метида — она\n", journal())

# --- [ревью PR #362, круг R2, второй argus] --------------------------------------------------------------------------
# Б1: добавленные строки молча меняют смысл строк контекста policy.toml (пробы argus probe_swallow.py)
SW_OLD = ('always = ["~/.claude/agent-memory"]\n\n[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n\n'
          '[private]\nroles = ["hq", "chiron"]\ncoordinators = ["mnemo-brain"]\n# Self, Areas, People\n'
          'paths = ["~/ai/knowledge/me", "~/ai/knowledge/Self", "~/ai/knowledge/People"]\n\n'
          '[sandbox_write]\nthemis-repos = ["~/.cache/repo-corp"]\n')
Q3 = "'" * 3
SWALLOW = {
    "строка в многострочную строку (private.paths пропадает)":
        (SW_OLD.replace("# Self, Areas, People\n", f"note = {Q3}\n# Self, Areas, People\n")
         .replace('People"]\n\n[sandbox_write]', f'People"]\n{Q3}\n\n[sandbox_write]'), "private.paths"),
    "то же и комментарий под [private] (не правит всю таблицу)":
        (SW_OLD.replace("[private]\n", "[private]\n# новый комментарий\n")
         .replace("# Self, Areas, People\n", f"note = {Q3}\n# Self, Areas, People\n")
         .replace('People"]\n\n[sandbox_write]', f'People"]\n{Q3}\n\n[sandbox_write]'), "private.paths"),
    "удалён заголовок [sandbox_write] (ключи уходят в [private])":
        (SW_OLD.replace("\n[sandbox_write]\n", "\n"), "private.themis-repos"),
}


def queue_req(old, new, why="добавить репозиторий", rel=".claude/pantheon/policy.toml"):
    """Заявка, записанная прямо в очередь STATE мимо propose: поля сверки честные (sha до, дифф, sha диффа)."""
    diff = OE.make_diff(rel, old, new)
    before, after = OE.sha(old), OE.sha(new)
    rid = "oe-20261108-000000-abcdef"
    req = {"id": rid, "file": rel, "before": before, "after": after, "diff": diff,
           "diff_sha": OE.diff_sha(rel, before, after, diff), "new": new, "task": "metis-0910", "why": why,
           "role": None, "created": time.time()}
    p = os.path.join(STATE, "owner-edit", "queue", f"{rid}.req.json")
    write(p, json.dumps(req, ensure_ascii=False), 0o600)
    return p, req


for what, (sw_new, lost) in SWALLOW.items():
    fresh(policy=SW_OLD)
    rc, out, errs = propose("~/.claude/pantheon/policy.toml", sw_new)
    check(f"Б1 R2: {what} — propose отказал, заявки нет, ключ назван", rc != 0 and not reqs() and lost in errs,
          (rc, out, errs))
    fresh(policy=SW_OLD)
    path0, req = queue_req(SW_OLD, sw_new)
    answer(OE.question(req), "А — Да, применить")
    run()
    check(f"Б1 R2: {what} — заявка мимо propose с «да»: проход отказал, файл не тронут, окна нет",
          read(POLICY) == SW_OLD and not ASKED and result(req).get("state") == "refused"
          and lost in result(req).get("note", ""), (ASKED, result(req), journal()))
    check(f"Б1 R2: {what} — в вопросе изменённый ключ со значениями", f"{lost}: " in seen(OE.question(req))
          and "→" in seen(OE.question(req)).split("Ключи")[-1], OE.question(req))
fresh(policy=SW_OLD)
check("Б1 R2: старый текст не TOML — отказ", hasattr(OE, "toml_keys") and raises(OE.toml_keys, ".claude/pantheon/policy.toml", "[x\n", SW_OLD))
# честные правки: ключ добавлен, элемент многострочного массива, ключ удалён — заявка есть, ключи с «старое → новое»
ML_OLD = '[merge_repos]\nmetis-pantheon = [\n  "latark/agent-kit",\n]\nzeus = ["a"]\n'
for what, old_t, new_t, key_row in (
        ("ключ добавлен", SW_OLD, SW_OLD.replace('roles = ["hq", "chiron"]\n', 'roles = ["hq", "chiron"]\nx = 1\n'),
         "private.x: нет → 1"),
        ("элемент многострочного массива", ML_OLD, ML_OLD.replace('  "latark/agent-kit",\n',
                                                                 '  "latark/agent-kit",\n  "latark/other",\n'),
         'merge_repos.metis-pantheon: ["latark/agent-kit"] → ["latark/agent-kit", "latark/other"]'),
        ("ключ удалён", ML_OLD, ML_OLD.replace('zeus = ["a"]\n', ""), 'merge_repos.zeus: ["a"] → нет')):
    fresh(policy=old_t)
    rc, out, errs = propose("~/.claude/pantheon/policy.toml", new_t)
    q = OE.question(reqs()[0][1]) if reqs() else ""
    check(f"Б1 R2: {what} — заявка есть, в вопросе «{key_row}»", rc == 0 and key_row in seen(q), (rc, errs, q))
    answer(q, "А — Да, применить")
    IDLE[0] = 10 ** 6
    run()
    check(f"Б1 R2: {what} — «да» на вопрос с ключами применено", read(POLICY) == new_t, journal())

# Б2: заявка, записанная прямо в очередь, с --why из bidi-знака, переводов строк, длиннее WHY_MAX (probe_why.py)
for what, bad_why in (("bidi U+202E", "ok\u202eон"), ("перевод строки", "строка\nвторая"),
                      (f"длиннее {OE.WHY_MAX}", "x" * (OE.WHY_MAX + 1)), ("пробел по краю", " зачем"),
                      ("двойной пробел", "за  чем"), ("неразрывный пробел", "за" + chr(0xA0) + "чем"),
                      ("пробы argus", "\u202eлюбой текст\n" * 3 + "x" * 500)):
    fresh()
    path0, req = queue_req(OLD, NEW, why=bad_why)
    check(f"Б2 R2: why {what} — valid() отказ", not OE.valid(req, os.path.basename(path0)))
    answer(OE.question(req), "А — Да, применить")
    run()
    check(f"Б2 R2: why {what} — заявка мимо propose не применена, окна нет", read(POLICY) == OLD and not ASKED
          and not os.path.exists(path0), (ASKED, journal()))
fresh()
path0, req = queue_req(OLD, NEW, why="x" * OE.WHY_MAX)
check("Б2 R2: why ровно WHY_MAX знаков и пустой — valid()", OE.valid(req, os.path.basename(path0))
      and OE.valid(dict(req, why=""), os.path.basename(path0)))

# --- [ревью PR #362, круг R3] ---------------------------------------------------------------------------------------
# R3-2 Б1 (проба argus P1): «е» кириллицей в латинском пути [private] — в вопросе и окне Touch ID е, а не «е»
HG_OLD = '[private]\ndirs = ["~/ai/knowledge/me"]\n'
HG_NEW = '[private]\ndirs = ["~/ai/knowledge/mе"]\n'
fresh(policy=HG_OLD)
rc, out, errs = propose("~/.claude/pantheon/policy.toml", HG_NEW, window="metis-pantheon")
_, req, win = reqs()[0] if reqs() else (None, {}, None)
q, wt = (seen(OE.question(req)), OE.window_text(dict(req, window=win)) or "") if req else ("", "")
check("R3-2 Б1: вопрос содержит \\u0435 — и в строке «+», и в ключах; самой «е» в вопросе нет",
      rc == 0 and '[private] +dirs = ["~/ai/knowledge/m\\u0435"]' in q
      and 'private.dirs: ["~/ai/knowledge/me"] → ["~/ai/knowledge/m\\u0435"]' in q and "mе" not in q, (rc, errs, q))
check("R3-2 Б1: окно Touch ID — тоже \\u0435", "m\\u0435" in wt and "mе" not in wt, wt)
check("R3 Б1: esc — всё вне печатного ASCII, \\U для знаков за U+FFFF; печатный ASCII как есть",
      OE.esc("a~ е\t😀") == "a~ \\u0435\\u0009\\U0001f600" and OE.key_row(("x",), OE.MISSING, "п")
      == 'x: нет → "\\u043f"' and OE.key_row(("t", "kе"), 1, 2) == 't."k\\u0435": 1 → 2', OE.esc("a~ е\t😀"))
# R3-2 Д1 (проба argus P2): .part — у строк «-»/«+» заголовок раздела; перенос «## Нельзя» → «## Можно» виден
PT_OLD = "## Можно\n- читать\n\n## Нельзя\n- пушить в main\n"
PT_NEW = "## Можно\n- читать\n- пушить в main\n\n## Нельзя\n"
fresh()
write(NAMES, PT_OLD)
rc, out, errs = propose("~/.claude/agents/_parts/names.part", PT_NEW, window="metis-pantheon")
_, req, win = reqs()[0] if reqs() else (None, {}, None)
q, wt = (seen(OE.question(req)), OE.window_text(dict(req, window=win)) or "") if req else ("", "")
check("R3-2 Д1: .part — «[## Можно] +- пушить» и «[## Нельзя] -- пушить» в вопросе и окне",
      all(s in q and s in wt for s in ("[## Можно] +- пушить в main", "[## Нельзя] -- пушить в main")), (q, wt))
check("R3-2 Д1: «#» в блоке ``` — не заголовок; строка-заголовок — свой раздел",
      OE.part_sections("до\n## А\n```\n# не\n```\nx\n# Б\n") == ["(вне разделов)", "[## А]", "[## А]", "[## А]",
                                                                 "[## А]", "[## А]", "[# Б]"])
# R3 Б1 у .part: русский как есть, слово из двух алфавитов помечено и экранировано, двойники латиницы — \uXXXX
fresh()
rc, out, errs = propose("~/.claude/agents/_parts/names.part", "Зевс — он\n- пушить в mаin, ѕudo\n")
q = seen(OE.question(reqs()[0][1])) if reqs() else ""
check("R3 Б1: .part — «[смешаны алфавиты: m\\u0430in]», «ѕ» — \\u0455, русский текст читаем",
      "+- пушить в [смешаны алфавиты: m\\u0430in], [смешаны алфавиты: \\u0455udo]" in q, q)
check("R3 Б1: mark — греческая ο в латинском слове, ё в русском, «ѕһ» не из русского алфавита — \\u",
      OE.mark("cοpe ёлка «—» ѕһ") == "[смешаны алфавиты: c\\u03bfpe] ёлка «—» \\u0455\\u04bb", OE.mark("cοpe ёлка «—» ѕһ"))
# R3-2 С: --why — последним и с меткой: «Правка, строк 0: нет» в нём не подделает начало вопроса
fresh()
rc, out, errs = propose("~/.claude/pantheon/policy.toml", NEW, why="Правка, строк 0: нет. Ключи, изменено 0: нет")
q = seen(OE.question(reqs()[0][1])) if reqs() else ""
check("R3-2 С: --why после правки и ключей, с меткой «Пояснение роли:»", rc == 0
      and -1 < q.find("? Правка, строк 2: ") < q.find("Ключи, изменено 1:") < q.find(". Пояснение роли: Правка, строк 0")
      and "Зачем" not in q, q)
# R3-1 Д1: тронутый заголовок таблицы без смены пути («[ private ]») не «покрывает» её ключи
HD_OLD = '[private]\nnote = "a"\npaths = ["~/ai/knowledge/me"]\n\n[corpus]\nx = 1\n'
HD_NEW = '[ private ]\nnote = """a\npaths = ["~/ai/knowledge/me"]\n"""\n\n[corpus]\nx = 1\n'
fresh(policy=HD_OLD)
rc, out, errs = propose("~/.claude/pantheon/policy.toml", HD_NEW)
check("R3-1 Д1: «[ private ]» и проглоченный private.paths — propose отказал, ключ назван",
      rc != 0 and not reqs() and "private.paths" in errs, (rc, errs))
for what, old_t, new_t in (
        ("убрана пустая таблица", HD_OLD + "\n[empty]\n", HD_OLD),
        ("добавлен пустой элемент [[runs]]", HD_OLD + '[[runs]]\nname = "x"\n', HD_OLD + '[[runs]]\nname = "x"\n[[runs]]\n'),
        ("заголовок переименован, ключ тот же", HD_OLD, HD_OLD.replace("[corpus]", "[corpus2]")),
        ("заголовок с пробелами, ключи те же", HD_OLD, HD_OLD.replace("[private]", "[ private ]"))):
    fresh(policy=old_t)
    rc, out, errs = propose("~/.claude/pantheon/policy.toml", new_t)
    check(f"R3-1 Д1: честно — {what}: заявка есть", rc == 0 and len(reqs()) == 1, (rc, errs))
# R3-1 Д2: окно Touch ID у policy.toml — со строками ключей
fresh()
rc, out, errs = propose("~/.claude/pantheon/policy.toml", NEW, window="metis-pantheon")
_, req, win = reqs()[0]
check("R3-1 Д2: окно Touch ID — «Ключи, изменено 1: merge_repos.metis-pantheon: … → …»",
      'Ключи, изменено 1: merge_repos.metis-pantheon: ["latark/agent-kit"] → ["latark/agent-kit", "latark/other"]'
      in (OE.window_text(dict(req, window=win)) or ""), OE.window_text(dict(req, window=win)))
# R3-1 Д3: честная правка в [[ ]] — ключ элемента массива таблиц правит свою строку (путь до None — сам массив)
AT_OLD = '[[runs]]\nname = "x"\nn = 1\n\n[[runs]]\nname = "y"\nn = 2\n'
for what, old_t, new_t, row in (
        ("значение во втором элементе", AT_OLD, AT_OLD.replace("n = 2", "n = 3"), "runs: "),
        # [t.s] стал подтаблицей элемента: старый ключ t.s.k правит только «+[[t]]» — путь до None, сам массив t
        ("[t.s] ушёл в новый элемент [[t]]", "[t.s]\nk = 1\n", "[[t]]\n[t.s]\nk = 1\n", "t.s.k: 1 → нет")):
    fresh(policy=old_t)
    rc, out, errs = propose("~/.claude/pantheon/policy.toml", new_t)
    check(f"R3-1 Д3: [[ ]] — {what}: заявка есть, ключ в вопросе",
          rc == 0 and row in (seen(OE.question(reqs()[0][1])) if reqs() else ""), (rc, errs))

# --- [ревью PR #362, круг R4] ---------------------------------------------------------------------------------------
# R4-2 Б1 (проба argus probe2.py): разметка Markdown в чате не прячет и не меняет ни одного знака из файла и от роли
import answers as A  # noqa: E402

TOML_REL, PART_REL = ".claude/pantheon/policy.toml", ".claude/agents/_parts/names.part"


def mkreq(rel, old_t, new_t, why=""):
    return {"id": "oe-20261108-010101-abcdef", "file": rel, "diff": OE.make_diff(rel, old_t, new_t), "new": new_t,
            "task": "metis-0910", "why": why, "diff_sha": "0" * 64}


def visible(req):
    """Всё, что владелец должен увидеть в вопросе, — строки правки (как в окне Touch ID), ключи, путь и --why — есть в
    отрисовке вопроса seen(); сверка ответа в чате (answers.scan_question) берёт ровно этот вопрос."""
    q, v = OE.question(req), seen(OE.question(req))
    sc = A.scan_question(q + "\n\nА — Да, применить\nБ — Нет\n")
    want = OE.shown(req) + (OE.key_rows(req) or []) + ["~/" + req["file"]] + \
        ([f"Пояснение роли: {OE.mark(req['why'])}"] if req["why"] else [])
    return all(w in v for w in want) and sc is not None and sc[0] == "ok" and OE.one_line(sc[2]) == OE.one_line(q)


bad_toml, bad_part = [], []
for c in string.punctuation:
    val = f"'a{c}{c}b'" if c in "'\"\\" and c != "'" else f'"a{c}{c}b"'
    if not visible(mkreq(TOML_REL, '[t]\nk = "a"\n', f"[t]\nk = {val}\n# к{c}{c}м\n", why=f"w{c}{c}x")):
        bad_toml.append(c)
    if not visible(mkreq(PART_REL, "## A\n- x\n", f"## H{c}{c}\n- a{c}{c}b\n", why=f"w{c}{c}x")):
        bad_part.append(c)
check("R4-2 Б1: каждый знак ASCII-пунктуации в значении TOML, ключах, комментарии и --why — в отрисовке вопроса тот же, "
      "сверка в чате — дословно", not bad_toml, bad_toml)
check("R4-2 Б1: каждый знак ASCII-пунктуации в строке и заголовке .part — в отрисовке вопроса тот же", not bad_part,
      bad_part)
check("R4-2 Б1: эталон seen() — неэкранированная разметка пропадает, «\\» перед пунктуацией снят",
      seen('k = "`x`" *y* [z](u)') == 'k = "x" y z(u)' and seen(OE.md('k = "`x`" *y* [z](u) \\u0435'))
      == 'k = "`x`" *y* [z](u) \\u0435' and OE.md("a-b") == "a\\-b")
PB_OLD = '[private]\npaths = ["~/ai/knowledge/Self"]\n'
PB_NEW = '[private]\npaths = ["`~/ai/knowledge/Self`"]\n'
pb = mkreq(TOML_REL, PB_OLD, PB_NEW)
pv = seen(OE.question(pb)).split("Правка, ")[1].split(f" {OE.SEP} ")
check("R4-2 Б1 (probe2): путь в обратных кавычках — строки «-» и «+» в отрисовке разные, кавычки видны",
      len(pv) == 2 and pv[0].replace("-paths", "+paths") != pv[1].split(". Ключи")[0]
      and '+paths = ["`~/ai/knowledge/Self`"]' in pv[1] and '→ ["`~/ai/knowledge/Self`"]' in pv[1], pv)
fresh(policy=PB_OLD)
rc, out, errs = propose("~/.claude/pantheon/policy.toml", PB_NEW)
_, req, _ = reqs()[0] if reqs() else (None, {}, None)
answer(seen(OE.question(req)) if req else "", "А — Да, применить")   # «да» на то, что видно, без «\» — не дословно
IDLE[0] = 10 ** 6
run()
check("R4-2 Б1: «да» на вопрос без экранирования — отказ, файл не тронут",
      rc == 0 and read(POLICY) == PB_OLD and result(req).get("state") == "refused", (rc, errs, result(req)))
fresh(policy=PB_OLD)
rc, out, errs = propose("~/.claude/pantheon/policy.toml", PB_NEW)
_, req, _ = reqs()[0] if reqs() else (None, {}, None)
answer(OE.question(req) if req else "", "А — Да, применить")
IDLE[0] = 10 ** 6
run()
check("R4-2 Б1: «да» на вопрос дословно (с «\\») — применено", read(POLICY) == PB_NEW, (errs, journal()))
wt = OE.window_text(mkreq(TOML_REL, PB_OLD, PB_NEW) | {"window": None}) or ""
check("R4-2 Б1: окно Touch ID — строки как есть, без «\\» Markdown (окно разметку не рисует)",
      '[private] +paths = ["`~/ai/knowledge/Self`"]' in wt and "\\`" not in wt, wt)
# R4-2 Д1: заголовки .part по правилам CommonMark — setext, отступ до 3 пробелов; черта, код, ~~~ — не заголовки
R = OE.PART_ROOT
for what, text, want in (
        ("setext «---» и «===», абзац из двух строк — весь заголовок",
         "до\n\nМожно\n-----\n- a\n\nНельзя\nсовсем\n=====\nx\n",
         [R, R, "[## Можно]", "[## Можно]", "[## Можно]", "[## Можно]", "[# Нельзя совсем]", "[# Нельзя совсем]",
          "[# Нельзя совсем]", "[# Нельзя совсем]"]),
        ("«## » с отступом 1–3 пробела; 4 пробела — код", " # А\n   ## Можно\nx\n    ## код\n",
         ["[# А]", "[## Можно]", "[## Можно]", "[## Можно]"]),
        ("«---» после пустой строки, под пунктом списка, цитатой и чертой «***» — черта",
         "x\n\n---\ny\n- a\n---\n> q\n---\n\n***\n---\n", [R] * 11),
        ("~~~ и забор длиннее: закрывает тот же знак не короче", "~~~\n# не\n```\n# не\n~~~\n````\n```\n# не\n````\n# да\n",
         [R] * 9 + ["[# да]"])):
    check(f"R4-2 Д1: part_sections — {what}", OE.part_sections(text) == want, OE.part_sections(text))
sx = OE.shown(mkreq(PART_REL, "## Можно\n- a\n## Нельзя\n- b\n",
                    "## Можно\n- a\n## Нельзя\nМожно\n-----\n- пушить в main\n"))
check("R4-2 Д1 (проба argus): setext «Можно» под «## Нельзя» — строки подписаны [## Можно]",
      sx[1:] == ["[## Можно] +Можно", "[## Можно] +-----", "[## Можно] +- пушить в main"], sx)
# R4-1 Д1: русский комментарий policy.toml в вопросе читаем (mark); «#» внутри многострочной строки — значение, esc
cm = OE.shown(mkreq(TOML_REL, "[t]\nk = 1\n", '[t]\n# путь к mе\nk = 1\ns = """\n# Секрет\n"""\n'))
check("R4-1 Д1: комментарий TOML — русский как есть, смешанное слово помечено; «#» в строке TOML — \\u",
      cm == ["[t] +# путь к [смешаны алфавиты: m\\u0435]", '[t] +s = """', "[t] +# \\u0421\\u0435\\u043a\\u0440\\u0435\\u0442",
             '[t] +"""'], cm)

# --- [проход] -------------------------------------------------------------------------------------------------------
fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
os.environ["CLAUDECODE"] = "1"
rc, _, errs = quiet(OE.main, ["run"])
os.environ.pop("CLAUDECODE", None)   # проход (если пошёл) снял окружение теста — вернуть
os.environ.update(dict(BASE_ENV, HOME=HOME))
check("run из окна Claude Code — отказ, код 2", rc == 2 and read(POLICY) == OLD and not ASKED, errs)
os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"
rc, _, errs = quiet(OE.main, ["run"])
os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)
os.environ.update(dict(BASE_ENV, HOME=HOME))
check("run с CLAUDE_CODE_ENTRYPOINT — отказ, код 2", rc == 2 and read(POLICY) == OLD and not ASKED, errs)
M.TEST = None   # настоящая сверка: HOME теста — не домашняя папка учётной записи
rc, _, errs = quiet(OE.main, ["run"])
M.TEST = {"env": BASE_ENV}
check("run: HOME окружения не домашняя папка — отказ, код 2", rc == 2 and read(POLICY) == OLD and not ASKED
      and "окружение прохода подменено" in errs, errs)
rc, out, _ = quiet(P.main, ["owner-edit", "status"])
check("pantheon owner-edit status: заявка видна", "ждёт" in out and "policy.toml" in out, out)
dry = os.path.join(STATE, "dryrun.log")
with contextlib.suppress(FileNotFoundError):
    os.remove(dry)
os.environ["PANTHEON_DRYRUN"] = "1"
P.owner_edit_kick()
check("тик: есть заявка — проход запускается", os.path.exists(dry) and "owner-edit-run" in read(dry))
os.remove(dry)
with P.lock("owner-edit-run") as held:   # Д2 R2: проход уже идёт — второй не запускается
    P.owner_edit_kick()
check("тик: замок прохода занят — проход не запускается (Д2 R2)", held and reqs() and not os.path.exists(dry))
import inspect  # noqa: E402
check("tick() зовёт owner_edit_kick после handoff_kick (Д1 R2)",
      "handoff_kick()\n        owner_edit_kick()" in inspect.getsource(P.tick))
_, r0, _ = reqs()[0]
rc, out, _ = quiet(OE.main, ["cancel", r0["id"]])
with contextlib.suppress(FileNotFoundError):
    os.remove(dry)
P.owner_edit_kick()
os.environ.pop("PANTHEON_DRYRUN")
check("тик: заявок нет — прохода нет", rc == 0 and not reqs() and not os.path.exists(dry))

# --- [policy set] metis-1122: правка policy.toml командой, а не Edit/Write роли --------------------------------------
fresh(OLD + "\n[coordinators]\nzeus = [\"hq\"]  # штаб\n\n[other]\nx = 1\n")
os.chmod(POLICY, 0o640)
start = read(POLICY)
rc, out, errs = quiet(P.main, ["policy", "set", "merge_repos", "metis-pantheon", "latark/agent-kit", "latark/other",
                               "--task", "metis-1122", "--why", "добавить репозиторий"])
q = reqs()
check("policy set: заявка owner-edit, файл не тронут", rc == 0 and len(q) == 1 and read(POLICY) == start,
      (rc, out, errs, q))
_, req, _ = q[0] if q else (None, {}, None)
want = start.replace('metis-pantheon = ["latark/agent-kit"]', 'metis-pantheon = ["latark/agent-kit", "latark/other"]')
check("policy set: новый текст — только строка ключа заменена", req.get("new") == want, req.get("new"))
check("policy set: вопрос Зевсу с [id] в выводе", f"[{req.get('id')}]" in out, out)
IDLE[0] = 10 ** 6
run()
check("policy set: без «да» не применено", read(POLICY) == start)
answer(yes_question(req), "А — Да, применить")
run()
check("policy set: «да» на вопрос с [id] — применено", read(POLICY) == want, (read(POLICY), journal()))
check("policy set: права прежние", stat.S_IMODE(os.stat(POLICY).st_mode) == 0o640)
# новый ключ — в конец своего раздела, новый раздел — в конец файла; скаляры и --list
fresh(OLD + "\n[other]\nx = 1\n")
for args, frag in ((["other", "y", "true"], "[other]\nx = 1\ny = true\n"),
                   (["other", "x", "5"], "[other]\nx = 5\n"),
                   (["fresh", "name", "zeus"], "\n[fresh]\nname = \"zeus\"\n"),
                   (["fresh", "names", "zeus", "--list"], "\n[fresh]\nnames = [\"zeus\"]\n"),
                   (["merge_repos", "demo-dir", "a/b"], "metis-pantheon = [\"latark/agent-kit\"]\ndemo-dir = \"a/b\"\n")):
    for p_, _, _ in reqs():
        os.remove(p_)
    rc, out, errs = quiet(P.main, ["policy", "set", *args, "--task", "metis-1122"])
    new = (reqs() or [(None, {}, None)])[0][1].get("new", "")
    check(f"policy set {' '.join(args)}: правка на месте", rc == 0 and frag in new and new.count("[other]") <= 1,
          (rc, errs, new))
# отказы: многострочное значение, нет значения, не по образцу, без задачи; файл не тронут, заявки нет
fresh('[merge_repos]\nmetis-pantheon = [\n  "latark/agent-kit",\n]\n')
for args, why in ((["merge_repos", "metis-pantheon", "x", "--task", "metis-1122"], "нескольких строках"),
                  (["merge_repos", "k", "--task", "metis-1122"], "вызов"),
                  (["merge repos", "k", "v", "--task", "metis-1122"], "не по образцу"),
                  (["merge_repos", "k", "v"], "вызов")):
    rc, out, errs = quiet(P.main, ["policy", "set", *args])
    check(f"policy set отказ ({why}): код не 0, причина последней строкой, заявки нет",
          rc != 0 and why in errs.strip().splitlines()[-1] and not reqs(), (rc, errs))
# ревью PR #437, Б1: «число» с переводом строки дописало бы чужие ключи и разделы — отказ, заявки нет
fresh(OLD + "\n[other]\nx = 1\n")
for val in ("1\nx = 2", "true\n[[evil]]\nrun = \"rm\"", "1\ry = 2", "on\x1b[2Kok", "5\u202e"):
    rc, out, errs = quiet(P.main, ["policy", "set", "other", "y", val, "--task", "metis-1122"])
    check(f"policy set {val!r}: отказ, код 2, причина последней строкой, заявки нет",
          rc == 2 and "невидимый знак" in errs.strip().splitlines()[-1] and not reqs(), (rc, errs, reqs()))
# сверка целиком: даже если значение прошло в текст, правка вне [section][key] — отказ
real_lit = OE.toml_literal
OE.toml_literal = lambda v: v
for val, sec in (("1\nz = 2", "other"), ("1\n[[evil]]\nrun = 1", "other"), ("1\n[more]\nq = 3", "fresh")):
    try:
        OE.policy_text(OLD + "\n[other]\nx = 1\n", sec, "y", [val])
        msg = ""
    except OE.Refuse as e:
        msg = str(e)
    check(f"policy_text сверка {val!r}: причина — чужие ключи", "не только этим ключом" in msg, msg)
OE.toml_literal = real_lit
check("policy_text: обычная правка проходит сверку",
      OE.policy_text(OLD + "\n[other]\nx = 1\n", "other", "x", ["7"]).endswith("[other]\nx = 7\n"))
rc, out, errs = quiet(P.main, ["policy", "get"])
check("policy без set — вызов, код 2", rc == 2 and "policy set" in errs, (rc, errs))

# --- [grant] pantheon grant request: право окну заявкой (metis-0680) ------------------------------------------------
GRANTS = os.path.join(HOME, ".claude", "pantheon", "grants.toml")


def grant(*args, window="metis-pantheon"):
    if window:
        os.makedirs(os.path.join(CACHES, window, "tmp"), exist_ok=True)
        os.environ["PANTHEON_TMP"] = os.path.join(CACHES, window, "tmp")
        os.environ["PANTHEON_ROLE"] = "metis-pantheon"
    try:
        return quiet(P.main, ["grant", "request", *args])
    finally:
        os.environ.pop("PANTHEON_TMP", None)
        os.environ.pop("PANTHEON_ROLE", None)


fresh()
with contextlib.suppress(FileNotFoundError):
    os.unlink(GRANTS)
SPOT = os.path.join(WORK, "spot")
rc, out, errs = grant("--write", SPOT, "--task", "metis-0680", "--why", "кэш сборки", window=None)
check("grant вне окна роли — отказ, заявки нет", rc == 2 and "окна роли" in errs.strip().splitlines()[-1]
      and not reqs(), (rc, errs))
for bad, why in ((["--write", "~/.ssh"], "ключи"), (["--write", SPOT, "--days", "99"], "--days"),
                 (["--write", SPOT, "--why", ""], "--why"), (["--days", "3"], "--write"),
                 (["--write", SPOT, "--bogus", "1"], "неизвестный")):
    args = bad + ([] if "--why" in bad else ["--why", "кэш сборки"]) + ["--task", "metis-0680"]
    rc, out, errs = grant(*args)
    check(f"grant {bad}: отказ, причина последней строкой, заявки нет",
          rc == 2 and why in errs.strip().splitlines()[-1] and not reqs(), (rc, errs))
rc, out, errs = grant("--write", SPOT, "--domain", "example.com", "--days", "3", "--task", "metis-0680",
                      "--why", "кэш сборки")
q = reqs()
check("grant из окна: заявка owner-edit на grants.toml, вопрос Зевсу в выводе", rc == 0 and len(q) == 1
      and q[0][1]["file"] == ".claude/pantheon/grants.toml" and f"[{q[0][1]['id']}]" in out, (rc, out, errs, q))
check("grant: файла ещё нет — роль его не писала", not os.path.exists(GRANTS))
_, req, _ = q[0]
answer(yes_question(req), "А — Да, применить")
IDLE[0] = 10 ** 6
rc, out, errs = run()
live, _, gerr, _ = P.grants_load()
check("grant: «да» — grants.toml заведён, право окну в силе до срока", os.path.exists(GRANTS) and not gerr
      and len(live) == 1 and live[0]["window"] == "metis-pantheon" and live[0]["write"] == [SPOT]
      and live[0]["domains"] == ["example.com"], (out, errs, live, gerr, journal()))
rc, out, errs = grant("--allow", "Bash(make:*)", "--task", "metis-0680", "--why", "сборка")
_, req, _ = reqs()[0]
answer(yes_question(req), "Б — Нет")
run()
check("grant: «нет» — файл прежний, итог роли не done", len(P.grants_load()[0]) == 1
      and result(req, "metis-pantheon").get("state") != "done", result(req, "metis-pantheon"))
H = P.handoff_mod()
check("отказ песочницы без маршрута — подсказка pantheon grant request",
      "pantheon grant request" in H.hint("touch /opt/x: Operation not permitted", "sandbox"))
check("тот же текст от роли (не песочница) — прежний вопрос через Зевса",
      "pantheon grant request" not in H.hint("touch /opt/x: Operation not permitted", "role"))

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
