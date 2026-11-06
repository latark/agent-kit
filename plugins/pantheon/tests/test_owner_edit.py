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
import stat
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


def yes_question(req):
    return OE.question(req)


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
check("заявка на файл вне списка — снята, файл не тронут", read(settings) == OLD and not os.path.exists(path0))

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

# --- [проход] -------------------------------------------------------------------------------------------------------
fresh()
propose("~/.claude/pantheon/policy.toml", NEW)
os.environ["CLAUDECODE"] = "1"
rc, _, errs = quiet(OE.main, ["run"])
os.environ.pop("CLAUDECODE")
check("run из окна Claude Code — отказ, код 2", rc == 2 and read(POLICY) == OLD and not ASKED, errs)
rc, out, _ = quiet(OE.main, ["status"])
check("status: заявка видна", "ждёт" in out and "policy.toml" in out, out)
dry = os.path.join(STATE, "dryrun.log")
with contextlib.suppress(FileNotFoundError):
    os.remove(dry)
os.environ["PANTHEON_DRYRUN"] = "1"
P.owner_edit_kick()
check("тик: есть заявка — проход запускается", os.path.exists(dry) and "owner-edit-run" in read(dry))
_, r0, _ = reqs()[0]
rc, out, _ = quiet(OE.main, ["cancel", r0["id"]])
os.remove(dry)
P.owner_edit_kick()
os.environ.pop("PANTHEON_DRYRUN")
check("тик: заявок нет — прохода нет", rc == 0 and not reqs() and not os.path.exists(dry))

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
