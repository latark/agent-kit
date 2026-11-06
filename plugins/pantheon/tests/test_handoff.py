#!/usr/bin/env python3
"""Отказ роли → тот, кто умеет; Touch ID на одно показанное действие (metis-0832, 0775; lib/handoff.py, hooks/refusal.py).

Запуск: python3 -I plugins/pantheon/tests/test_handoff.py  (код выхода 0 — все прошли)
Временный HOME, PANTHEON_STATE; окно Touch ID (handoff.ask), исполнитель демона CDP и простой владельца подменены —
настоящих окон, пальца и демонов тест не трогает. Проверяет по пунктам «Готово, когда»:
  [маршрут]  подсказка на отказ: браузер → Харон, окна и процессы → Гестия, порт и сокет → outside, Telegram → read,
             белый список → Touch ID, прочее → «да» через Зевса; в каждой подсказке — запрет давать владельцу команду;
  [N1–N6]    где Touch ID не действует (перечень — README guard): оплата, важная форма, удаление пачки, правка защит,
             то, что окно не покажет целиком, вид вне белого списка;
  [окно]     текст окна — из живых фактов; палец разрешает одно действие один раз; любая правка заявки или фактов
             после пальца — снято без действия; отказ, время вышло, окно не показать, владелец не у Mac;
  [0775]     белый список вживую на временном git: удалить worktree без своего (грязная, неотправленная, основная копия
             — отказ), deploy.sh (правка скрипта после заявки — снято);
  [хук]      PostToolUseFailure, PermissionDenied → отметка → PostToolBatch (своя сессия и агент, один раз), оболочка
             hooks.json не запускает python без отметки;
  [журнал]   три типовых отказа → строка «Отказы за сутки» доски (boardtext);
  [только да] шаблоны ролей и hq не велят владельцу «выполнить в терминале» и включают раздел handoff.
"""
import atexit
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PLUGIN))
sys.path.insert(0, HERE)
from _py311 import PY311, mkroot  # noqa: E402

_ROOT = os.path.realpath(mkroot("handoff-"))
atexit.register(shutil.rmtree, _ROOT, True)
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
os.makedirs(os.path.join(HOME, "projects"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE", "XDG_"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1"})
sys.path.insert(0, os.path.join(PLUGIN, "lib"))
import pantheon as P  # noqa: E402
import boardtext  # noqa: E402

H = P.handoff_mod()
HOOK = os.path.join(PLUGIN, "hooks", "refusal.py")
CACHES = os.path.join(HOME, "Library", "Caches", "pantheon-sandbox")

FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-800:]}]"))
    if not cond:
        FAILS.append(name)


# --- подмены: окно Touch ID, исполнитель демона, простой, тревоги --------------------------------------------------
ASKED, ALERTS, CDP_RUNS = [], [], []
ANSWER = {"code": 0, "during": None}


def fake_ask(text):
    ASKED.append(text)
    if ANSWER["during"]:
        ANSWER["during"]()
    return ANSWER["code"]


def fake_cdp(req, facts):
    CDP_RUNS.append((req["id"], facts["browser"]))
    return f"демон {facts['browser']} перезапущен (тест)"


H.ask = fake_ask
H.EXEC["cdp-restart"] = fake_cdp
IDLE = [0.0]
P.idle_sec = lambda: IDLE[0]
P.alert_once = lambda key, value, text, *a, **kw: ALERTS.append((key, value, text))


def reset(code=0, during=None):
    ASKED.clear()
    CDP_RUNS.clear()
    ALERTS.clear()
    ANSWER.update(code=code, during=during)
    IDLE[0] = 0.0


def quiet(fn, *a):
    out, errb = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errb):
        rc = fn(*a)
    return rc, out.getvalue(), errb.getvalue()


@contextlib.contextmanager
def env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def window(name):
    """Окно роли name: PANTHEON_TMP в кэше песочницы, заявки — в его handoff/."""
    tmp = os.path.join(CACHES, name, "tmp")
    os.makedirs(tmp, exist_ok=True)
    return env(PANTHEON_TMP=tmp, PANTHEON_ROLE="dev-opus")


def qdir(name=None):
    return os.path.join(CACHES, name, "handoff") if name else os.path.join(STATE, "handoff", "queue")


def reqs(d):
    return sorted(n for n in os.listdir(d) if n.endswith(".req.json")) if os.path.isdir(d) else []


def result(d, rid):
    with open(os.path.join(d, f"{rid}.result.json"), encoding="utf-8") as fh:
        return json.load(fh)


def touch(*args, win=None):
    """pantheon handoff touch … → (код, id заявки или None, stdout+stderr)."""
    ctx = window(win) if win else env(PANTHEON_TMP=None, PANTHEON_ROLE=None)
    with ctx:
        rc, out, er = quiet(H.main, ["touch", *args])
    m = re.search(r"заявка (\d{8}-\d{6}-[0-9a-f]{6})", out)
    return rc, (m.group(1) if m else None), out + er


def run():
    with env(CLAUDECODE=None, CLAUDE_CODE_ENTRYPOINT=None, PANTHEON_TMP=None):
        return quiet(H.cmd_run)[0]


def log_lines():
    return H.read_log()


def clear_log():
    with contextlib.suppress(OSError):
        os.unlink(H.log_path())


# ===================================================================================================================
# [маршрут] подсказка на отказ: кто умеет
# ===================================================================================================================
ROUTE_CASES = [
    ("Bash curl -s 127.0.0.1:9333/health Operation not permitted", "browser", "Харон"),
    ("Bash curl 127.0.0.1:9334/open — открыть avito в Chrome", "browser", "Харон"),
    ("Bash launchctl kickstart gui/501/com.pantheon.tick — denied", "hestia", "Гестия"),
    ("Bash osascript -e 'tell application \"iTerm\"'", "hestia", "Гестия"),
    ("Bash pnpm dev listen EPERM: operation not permitted 127.0.0.1:3000", "outside", "outside"),
    ("Bash pytest tests/ — Error: listen EADDRINUSE", "outside", "outside"),
    ("Bash python3 ~/projects/other/tg-read/tg_read.py chats — command not found", "telegram", "read"),
    ("Bash git worktree remove ../agent-x", "touch", "Touch ID"),
    ("Bash ./deploy.sh", "touch", "Touch ID"),
    ("перезапуск демона CDP comet", "touch", "Touch ID"),
    ("Bash brew install jq — classifier: Software installation", "ask", "«да»"),
    ("открыть страницу оплаты и ввести номер карты", "payment", "владелец руками"),
    ("заполнить форму входа и ввести код из СМС", "important-form", "владелец руками"),
    ("Edit ~/.claude/settings.json — protect-config", "guard", "шлюз"),
    ("Edit plugins/guard/lib/guard_rules.py", "guard", "шлюз"),
    ("Bash rm -rf ~/projects/a ~/projects/b", "batch-delete", "«да»"),
    ("Bash rm ~/projects/old/*.log", "batch-delete", "«да»"),
    ("Bash find . -name '*.tmp' -delete", "batch-delete", "«да»"),
]
for text, key, who in ROUTE_CASES:
    got = H.route(text)
    hint = H.hint(text, "sandbox")
    check(f"маршрут: «{text[:50]}» → {key}", got[0] == key and who in got[1], got)
    check(f"подсказка «{key}»: кому и запрет команды владельцу", who.strip("«»") in hint and H.NO_TERMINAL in hint
          and "песочница" in hint, hint)
check("маршрут: одиночный rm с перенаправлением — не пачка", H.route("Bash rm -f out.txt 2>/dev/null")[0] != "batch-delete",
      H.route("Bash rm -f out.txt 2>/dev/null"))
check("маршрут: один rm одного файла — не пачка", H.route("Bash rm build/out.txt")[0] != "batch-delete",
      H.route("Bash rm build/out.txt"))
check("маршрут: ключи маршрутов = ROUTE_KEYS, «ask» — последний", list(H.ROUTE_KEYS)[-1] == "ask"
      and len(set(H.ROUTE_KEYS)) == len(H.ROUTE_KEYS), H.ROUTE_KEYS)
check("маршрут: Харон и Гестия — карточкой Зевсу, а не напрямую",
      "--owner zeus" in H.route("comet")[3] and "--owner zeus" in H.route("launchctl")[3]
      and "pantheon wake hestia" in H.route("launchctl")[3], H.route("launchctl"))

for text, src in [("sandbox-exec: Operation not permitted", "sandbox"), ("listen EPERM 127.0.0.1", "sandbox"),
                  ("touch: /Users/x/.ssh/a: Read-only file system", "sandbox"),
                  ("zsh: command not found: tg-read", "nocmd"),
                  ("pantheon: неизвестная команда «zap»", "nocmd"),
                  ("AssertionError: 1 != 2", None), ("SyntaxError: invalid syntax", None), ("", None),
                  ("exit code 1\nFAIL test_x", None)]:
    check(f"источник отказа: {text[:40]!r} → {src}", H.refusal_source(text) == src, H.refusal_source(text))

# ===================================================================================================================
# [N1–N6] где Touch ID не действует
# ===================================================================================================================
WT_OK = "~/projects/x/.claude/worktrees/agent-1"
NO_TOUCH_CASES = [
    ("[N1] оплата: вид payment", ("payment", "https://shop/pay", ""), "owner", "payment"),
    ("[N1] оплата: признак в «зачем» белого вида", ("deploy", "~/projects/shop", "оплата заказа"), "owner",
     "payment"),
    ("[N1] оплата: checkout в цели", ("cdp-restart", "comet", "открыть checkout"), "owner", "payment"),
    ("[N2] важная форма: вид", ("important-form", "https://gosuslugi.ru", ""), "owner", "important-form"),
    ("[N2] важная форма: код из СМС в «зачем»", ("cdp-restart", "chrome", "ввести код из СМС"), "owner",
     "important-form"),
    ("[N2] важная форма: смена пароля", ("deploy", "~/projects/site", "смена пароля"), "owner", "important-form"),
    ("[N3] удаление пачки: вид", ("batch-delete", "~/projects/old", ""), "yes", "batch-delete"),
    ("[N3] удаление пачки: шаблон в цели worktree-remove", ("worktree-remove", "~/projects/x/.claude/worktrees/*", ""),
     "yes", "batch-delete"),
    ("[N3] удаление пачки: «удалить все» в «зачем»", ("worktree-remove", WT_OK, "удалить все старые"), "yes",
     "batch-delete"),
    ("[N4] защиты: вид guard", ("guard", "plugins/guard/lib/guard_rules.py", ""), "merge", "guard"),
    ("[N4] защиты: deploy в plugins/guard", ("deploy", "~/projects/agent-kit/plugins/guard", ""), "merge", "guard"),
    ("[N4] защиты: настройки в «зачем»", ("cdp-restart", "comet", "после правки ~/.claude/settings.json"), "merge",
     "guard"),
    ("[N4] защиты: hooks.json", ("worktree-remove", WT_OK, "сбросить hooks.json"), "merge", "guard"),
    ("[N5] не показать: bidi-знак в цели", ("worktree-remove", WT_OK + "‮gnp.exe", ""), "yes", "touch"),
    ("[N5] не показать: невидимый пробел нулевой ширины", ("worktree-remove", WT_OK + "​", ""), "yes", "touch"),
    ("[N5] не показать: перенос строки в «зачем»", ("cdp-restart", "comet", "a\nb"), "yes", "touch"),
    ("[N5] не показать: две цели через пробел", ("worktree-remove", WT_OK + " ~/projects/y", ""), "yes", "touch"),
    ("[N5] не показать: цель длиннее окна", ("worktree-remove", "~/projects/" + "a" * 400, ""), "yes", "touch"),
    ("[N6] вне белого списка: git push", ("git-push", "origin", ""), "route", None),
    ("[N6] вне белого списка: brew install", ("brew-install", "jq", ""), "route", None),
]
for name, args, channel, key in NO_TOUCH_CASES:
    r = H.touch_refusal(*args)
    check(f"{name} → {channel}", r is not None and r.channel == channel and (key is None or r.key == key),
          (r and (r.channel, r.key, str(r))))
r = H.touch_refusal("git-push", "origin", "")
check("[N6] вне белого списка: подсказка, кто умеет, и запрет команды владельцу", r and H.NO_TERMINAL in str(r)
      and "белого списка" in str(r), r)
for args in [("worktree-remove", WT_OK, "убрать после слияния"), ("deploy", "~/projects/site", ""),
             ("cdp-restart", "comet", "демон завис"), ("cdp-restart", "chrome", "")]:
    check(f"белый список: {args[0]} {args[1]} — Touch ID может разрешить", H.touch_refusal(*args) is None,
          H.touch_refusal(*args))
check("showable: обычный текст", H.showable("Удалить worktree ~/projects/x. Просит win."))
for bad in ["", "a" * (H.WINDOW_MAX + 1), "a\tb", "a‍b", "a⁦b", "a b", "a\x1b[31mb", "ab"]:
    check(f"showable: {bad[:12]!r} — нет", not H.showable(bad))

# README guard: перечень есть, у каждого пункта — метка теста
with open(os.path.join(REPO, "plugins", "guard", "README.md"), encoding="utf-8") as fh:
    greadme = fh.read()
sec = greadme.split("## Touch ID: где не действует", 1)[1].split("\n## ", 1)[0] if \
    "## Touch ID: где не действует" in greadme else ""
for lab in ("[N1]", "[N2]", "[N3]", "[N4]", "[N5]", "[N6]"):
    check(f"README guard: {lab} в перечне «где не действует», и тест на него есть", lab in sec
          and any(c[0].startswith(lab) for c in NO_TOUCH_CASES), sec[:200])
for word in ("оплат", "важн", "пачк", "защит", "целиком"):
    check(f"README guard: перечень называет «{word}»", word in sec.lower(), sec[:300])

# ===================================================================================================================
# [окно] заявка → окно Touch ID → одно действие, один раз
# ===================================================================================================================
reset()
clear_log()
rc, rid, out = touch("cdp-restart", "comet", "--task", "metis-0832", "--why", "демон завис", win="win-a")
check("заявка из окна: код 0 и id", rc == 0 and rid, out)
check("заявка из окна: лежит в кэше окна (handoff/ рядом с PANTHEON_TMP)", reqs(qdir("win-a")) == [f"{rid}.req.json"],
      reqs(qdir("win-a")))
with open(os.path.join(qdir("win-a"), f"{rid}.req.json"), encoding="utf-8") as fh:
    REQ = json.load(fh)
check("текст окна: действие, кто просит (окно по месту), роль, задача, зачем, «только это, один раз»",
      REQ["text"].startswith("Перезапустить демон CDP comet (порт 9333)") and "Просит win-a (dev-opus со слов заявки)"
      in REQ["text"] and "задача metis-0832" in REQ["text"] and "Зачем: демон завис." in REQ["text"]
      and "только это действие, один раз" in REQ["text"] and REQ["sha"] == H.sha(REQ["text"]), REQ)
check("журнал: заявка из окна — в кэш окна (STATE окну закрыт), «ждёт Touch ID»",
      any(e["outcome"] == "waiting" and e.get("id") == rid
          for e in H.read_log(os.path.join(qdir("win-a"), "log.jsonl"))), H.read_log(os.path.join(qdir("win-a"),
                                                                                                 "log.jsonl")))
check("pending: есть заявка", H.pending())
IDLE[0] = H.PRESENT_SEC + 1
run()
check("владелец не у Mac → окна нет, заявка ждёт", not ASKED and reqs(qdir("win-a")), ASKED)
check("журнал окна перенесён проходом в STATE, окно — по месту папки",
      any(e.get("id") == rid and e.get("window") == "win-a" for e in log_lines())
      and not os.path.exists(os.path.join(qdir("win-a"), "log.jsonl")), log_lines())
IDLE[0] = 0
run()
check("палец → окно показано ровно с текстом заявки, один раз", ASKED == [REQ["text"]], ASKED)
check("палец → действие исполнено один раз", CDP_RUNS == [(rid, "comet")], CDP_RUNS)
res = result(qdir("win-a"), rid)
check("палец → итог done рядом с заявкой, заявки больше нет", res["state"] == "done" and not reqs(qdir("win-a")), res)
with open(os.path.join(STATE, "owner-log", "handoff-approve.log"), encoding="utf-8") as fh:
    approve = fh.read()
check("палец → строка handoff-approve <id> <sha256 показанного текста>", f"handoff-approve {rid} {REQ['sha']}" in approve,
      approve)
reset()
run()
check("второй проход: окна нет, действие не повторено", not ASKED and not CDP_RUNS, (ASKED, CDP_RUNS))
with window("win-a"):
    rc, out, _ = quiet(H.main, ["status", rid])
check("status: итог done", rc == 0 and "done" in out, out)

# подмена после пальца: байты заявки (текст тот же) → снято без действия
reset()
rc, rid, _ = touch("cdp-restart", "comet", "--task", "metis-0832", win="win-a")
RP = os.path.join(qdir("win-a"), f"{rid}.req.json")


def rewrite_bytes():
    with open(RP, encoding="utf-8") as fh:
        d = json.load(fh)
    d["created"] = d["created"] + 1
    os.unlink(RP)
    with open(RP, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)


ANSWER["during"] = rewrite_bytes
run()
res = result(qdir("win-a"), rid)
check("после пальца заявку переписали (текст тот же) → снято, действия нет", res["state"] == "dropped"
      and not CDP_RUNS and len(ASKED) == 1 and not reqs(qdir("win-a")), (res, CDP_RUNS))

# подмена после пальца: факты (порт демона) → текст другой → новый вопрос
reset()
rc, rid, _ = touch("cdp-restart", "comet", "--task", "metis-0832", win="win-a")


def move_port():
    H.CDP_PORTS["comet"] = 9399


ANSWER["during"] = move_port
run()
H.CDP_PORTS["comet"] = 9333
res = result(qdir("win-a"), rid)
check("после пальца факты сменились → снято «новый вопрос», действия нет", res["state"] == "dropped"
      and "новый вопрос" in res["note"] and not CDP_RUNS, (res, CDP_RUNS))
check("после смены фактов заявка снята", not reqs(qdir("win-a")), reqs(qdir("win-a")))

# правка текста заявки до прохода → снята без окна
reset()
rc, rid, _ = touch("cdp-restart", "chrome", "--task", "metis-0832", win="win-a")
RP = os.path.join(qdir("win-a"), f"{rid}.req.json")
with open(RP, encoding="utf-8") as fh:
    d = json.load(fh)
d["why"] = "другое"
os.unlink(RP)
with open(RP, "w", encoding="utf-8") as fh:
    json.dump(d, fh, ensure_ascii=False)
run()
check("«зачем» заявки переправили → текст не тот → снято без окна", not ASKED and
      result(qdir("win-a"), rid)["state"] == "dropped", ASKED)

# заявка переложена в чужое окно → «кто просит» по месту другой → снято
reset()
rc, rid, _ = touch("cdp-restart", "chrome", "--task", "metis-0832", win="win-a")
os.makedirs(qdir("win-b"), exist_ok=True)
os.rename(os.path.join(qdir("win-a"), f"{rid}.req.json"), os.path.join(qdir("win-b"), f"{rid}.req.json"))
run()
check("заявку переложили в кэш другого окна → снята без окна (кто просит — по месту)", not ASKED
      and result(qdir("win-b"), rid)["state"] == "dropped", ASKED)

# отказ в окне, время вышло, окно не показать, старая заявка
reset(code=1)
rc, rid, _ = touch("cdp-restart", "comet", "--task", "metis-0832", win="win-a")
run()
check("отказ в окне → declined, действия нет, заявка снята", result(qdir("win-a"), rid)["state"] == "declined"
      and not CDP_RUNS and not reqs(qdir("win-a")))
reset(code=3)
rc, rid, _ = touch("cdp-restart", "comet", "--task", "metis-0832", win="win-a")
run()
check("время вышло → заявка ждёт, отметка повтора", reqs(qdir("win-a")) == [f"{rid}.req.json"] and
      os.path.exists(os.path.join(STATE, "handoff", "retry", rid)) and not CDP_RUNS)
reset(code=0)
run()
check("повтор раньше RETRY_SEC → окна нет", not ASKED, ASKED)
os.utime(os.path.join(STATE, "handoff", "retry", rid), (time.time() - H.RETRY_SEC - 5,) * 2)
run()
check("после RETRY_SEC → окно снова, палец → сделано", len(ASKED) == 1 and CDP_RUNS, (ASKED, CDP_RUNS))
reset(code=2)
rc, rid, _ = touch("cdp-restart", "comet", "--task", "metis-0832", win="win-a")
run()
check("окно не показать → заявка ждёт, тревога один раз, действия нет", reqs(qdir("win-a")) and
      [a[0] for a in ALERTS] == ["handoff-window"] and not CDP_RUNS, ALERTS)
reset(code=None)
run()
check("помощника нет → тоже ждёт с тревогой", reqs(qdir("win-a")) and ALERTS and not CDP_RUNS, ALERTS)
with window("win-a"):
    rc, out, _ = quiet(H.main, ["cancel", rid])
check("cancel своей заявки → снята", rc == 0 and not reqs(qdir("win-a")), out)
reset()
rc, rid, _ = touch("cdp-restart", "comet", "--task", "metis-0832", win="win-a")
RP = os.path.join(qdir("win-a"), f"{rid}.req.json")
with open(RP, encoding="utf-8") as fh:
    d = json.load(fh)
d["created"] = time.time() - H.REQ_TTL - 10
os.unlink(RP)
with open(RP, "w", encoding="utf-8") as fh:
    json.dump(d, fh, ensure_ascii=False)
run()
check("заявка старше REQ_TTL → снята без окна", not ASKED and result(qdir("win-a"), rid)["state"] == "dropped")

# заявка-ссылка и мусор в очереди
reset()
os.makedirs(qdir(), exist_ok=True)
with open(os.path.join(_ROOT, "real.json"), "w") as fh:
    fh.write("{}")
os.symlink(os.path.join(_ROOT, "real.json"), os.path.join(qdir(), "20260101-000000-aaaaaa.req.json"))
with open(os.path.join(qdir(), "20260101-000000-bbbbbb.req.json"), "w") as fh:
    fh.write("not json")
run()
check("ссылка и мусор в очереди → убраны без окна", not ASKED and not reqs(qdir()), reqs(qdir()))

# исполнитель упал → итог failed
reset()
rc, rid, _ = touch("cdp-restart", "comet", "--task", "metis-0832")


def boom(req, facts):
    raise RuntimeError("порт занят")


H.EXEC["cdp-restart"] = boom
run()
H.EXEC["cdp-restart"] = fake_cdp
check("заявка вне окна → очередь STATE; исполнитель упал → failed с причиной",
      result(qdir(), rid)["state"] == "failed" and "порт занят" in result(qdir(), rid)["note"], result(qdir(), rid))

# Claude Code не запускает проход сам
with env(CLAUDECODE="1"):
    rc, _, er = quiet(H.cmd_run)
check("run из окна Claude Code → код 2", rc == 2 and "плановый проход" in er, er)
with env(CLAUDE_CODE_ENTRYPOINT="cli"):
    rc, _, _ = quiet(H.cmd_run)
check("run при CLAUDE_CODE_ENTRYPOINT → код 2", rc == 2)

# CLI: плохие входы
for args, code in [([], 2), (["zap"], 2), (["run", "x"], 2), (["route"], 2), (["route", "--source", "x", "a"], 2),
                   (["route", "--task"], 2), (["touch", "cdp-restart", "comet"], 2),
                   (["touch", "cdp-restart", "comet", "--task", "Bad Task"], 2),
                   (["touch", "cdp-restart", "--task", "metis-1"], 2),
                   (["touch", "cdp-restart", "comet", "--task", "metis-1", "--wait", "x"], 2),
                   (["touch", "cdp-restart", "comet", "--task", "metis-1", "--wait", "-5"], 2),
                   (["touch", "cdp-restart", "comet", "--task", "metis-1", "--bogus", "1"], 2),
                   (["touch", "cdp-restart", "comet", "--task", "metis-1", "--why", "x" * (H.WHY_MAX + 1)], 2),
                   (["touch", "payment", "https://shop", "--task", "metis-1"], 2),
                   (["touch", "cdp-restart", "opera", "--task", "metis-1"], 2),
                   (["cancel"], 2), (["cancel", "../x"], 2), (["cancel", "20260101-000000-cccccc"], 1)]:
    with env(PANTHEON_TMP=None):
        rc, out, er = quiet(H.main, args)
    check(f"CLI {args[:3]} → код {code}, причина в stderr", rc == code and er.strip(), (rc, out, er))
clear_log()
with env(PANTHEON_TMP=None):
    rc, out, er = quiet(H.main, ["touch", "payment", "https://shop", "--task", "metis-1"])
check("отказ Touch ID пишется в журнал: оплата → «только владелец»", any(e["kind"] == "payment" and
      e["outcome"] == "owner" for e in log_lines()) and H.NO_TERMINAL in er, (log_lines(), er))
with env(PANTHEON_TMP=None):
    rc, out, er = quiet(H.main, ["route", "--source", "guard", "--task", "metis-1", "--", "Bash", "launchctl", "list"])
check("route: подсказка Гестии, строка журнала источник guard", rc == 0 and "Гестия" in out and
      any(e["source"] == "guard" and e["kind"] == "hestia" and e.get("task") == "metis-1" for e in log_lines()), out)
with env(PANTHEON_TMP=None):
    quiet(H.main, ["route", "--task", "x; rm -rf /", "Bash", "comet"])
check("журнал: задача не по образцу не пишется", all(e.get("task") != "x; rm -rf /" for e in log_lines()))

# ===================================================================================================================
# [0775] белый список вживую: worktree без своего, deploy.sh
# ===================================================================================================================


def g(cwd, *a):
    return subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                           "-c", "init.defaultBranch=main", *a], capture_output=True, text=True, check=True).stdout


ORIGIN = os.path.join(_ROOT, "origin.git")
MAIN = os.path.join(HOME, "projects", "repo")
WT = os.path.join(HOME, "projects", "repo-wt")
subprocess.run(["git", "init", "-q", "--bare", "-b", "main", ORIGIN], check=True)
subprocess.run(["git", "init", "-q", "-b", "main", MAIN], check=True)
with open(os.path.join(MAIN, "deploy.sh"), "w") as fh:
    fh.write('echo deployed > "$PWD/.deployed-marker"\n')
with open(os.path.join(MAIN, ".gitignore"), "w") as fh:
    fh.write(".deployed-marker\n")
g(MAIN, "add", "-A")
g(MAIN, "commit", "-qm", "init")
g(MAIN, "remote", "add", "origin", ORIGIN)
g(MAIN, "push", "-q", "origin", "main")
g(MAIN, "worktree", "add", "-q", "-b", "feat", WT, "origin/main")

def refused(fn, *a):
    try:
        fn(*a)
        return None
    except H.Refuse as e:
        return e.channel, str(e)


GD = os.path.join(MAIN, ".git", "worktrees", "repo-wt")
f = H.facts_worktree("~/projects/repo-wt")
check("worktree отправленная → факты: путь, ветка, HEAD, где есть",
      f["path"] == WT and "ветка feat" in f["desc"] and "origin/main" in f["desc"] and f["gd"] == GD, f)
for name, target, prep, channel in [
        ("основная копия", "~/projects/repo", None, "bad"),
        ("подпапка worktree", "~/projects/repo-wt/sub", "mkdir", "bad"),
        ("вне ~/projects", _ROOT, None, "bad"),
        ("относительный путь", "projects/repo-wt", None, "bad"),
        ("ссылка на worktree", "~/projects/link-wt", "link", "bad"),
        ("незакоммиченный файл: до вопроса status не идёт", "~/projects/repo-wt", "dirty", None),
        ("коммит только в ней", "~/projects/repo-wt", "commit", "yes")]:
    if prep == "mkdir":
        os.makedirs(os.path.join(WT, "sub"), exist_ok=True)
        with open(os.path.join(WT, "sub", "k"), "w") as fh:
            fh.write("x")
        g(WT, "add", "-A")
        g(WT, "commit", "-qm", "sub")
    elif prep == "link":
        os.symlink(WT, os.path.join(HOME, "projects", "link-wt"))
    elif prep == "dirty":
        with open(os.path.join(WT, "new.txt"), "w") as fh:
            fh.write("x")
    elif prep == "commit":
        os.unlink(os.path.join(WT, "new.txt"))
        with open(os.path.join(WT, "own.txt"), "w") as fh:
            fh.write("x")
        g(WT, "add", "-A")
        g(WT, "commit", "-qm", "own")
    r = refused(H.facts_worktree, target)
    check(f"worktree-remove: {name} → {('отказ ' + channel) if channel else 'факты'}",
          (r and r[0]) == channel if channel else r is None, r)
    if prep == "mkdir":
        g(WT, "reset", "-q", "--hard", "origin/main")
g(WT, "reset", "-q", "--hard", "origin/main")
r = refused(H.facts_worktree, "~/projects/repo")
check("worktree-remove: основная копия → отказ с причиной «основная копия»", r and "основная копия" in r[1], r)

# собственный gitdir worktree: заперта, обратная ссылка, commondir, место gitdir (находка безопасности, круг 2, п. 4)
with open(os.path.join(GD, "locked"), "w") as fh:
    fh.write("x")
r = refused(H.facts_worktree, "~/projects/repo-wt")
check("worktree заперта (git worktree lock) → только «да»", r and r[0] == "yes" and "заперта" in r[1], r)
os.unlink(os.path.join(GD, "locked"))
with open(os.path.join(GD, "gitdir"), encoding="utf-8") as fh:
    backlink = fh.read()
with open(os.path.join(GD, "gitdir"), "w") as fh:
    fh.write(os.path.join(MAIN, ".git") + "\n")
r = refused(H.facts_worktree, "~/projects/repo-wt")
check("gitdir worktree указывает не на неё → отказ", r and r[0] == "bad" and "обратно" in r[1], r)
with open(os.path.join(GD, "gitdir"), "w") as fh:
    fh.write(backlink)
with open(os.path.join(GD, "commondir"), encoding="utf-8") as fh:
    commondir = fh.read()
with open(os.path.join(GD, "commondir"), "w") as fh:
    fh.write(ORIGIN + "\n")
r = refused(H.facts_worktree, "~/projects/repo-wt")
check("commondir worktree ведёт в чужой репозиторий → отказ", r and r[0] == "bad", r)
with open(os.path.join(GD, "commondir"), "w") as fh:
    fh.write(commondir)
DOTGIT = os.path.join(WT, ".git")
with open(DOTGIT, encoding="utf-8") as fh:
    dotgit = fh.read()
EVIL = os.path.join(HOME, "projects", "evil-gitdir")
shutil.copytree(GD, EVIL)
with open(os.path.join(EVIL, "commondir"), "w") as fh:
    fh.write(os.path.join(MAIN, ".git") + "\n")
with open(os.path.join(EVIL, "gitdir"), "w") as fh:
    fh.write(DOTGIT + "\n")
with open(DOTGIT, "w") as fh:
    fh.write(f"gitdir: {EVIL}\n")
r = refused(H.facts_worktree, "~/projects/repo-wt")
check(".git worktree указывает на gitdir вне .git/worktrees → отказ", r and r[0] == "bad" and "не в" in r[1], r)
PWN = os.path.join(_ROOT, "pwned")
with open(os.path.join(EVIL, "config.worktree"), "w") as fh:
    fh.write(f'[diff "x"]\n\ttextconv = touch {PWN}\n')
r = refused(H.facts_worktree, "~/projects/repo-wt")
check("чужой gitdir с diff-драйвером в config.worktree → отказ по белому списку", r and r[0] == "bad" and
      "diff.x.textconv" in r[1], r)
with open(DOTGIT, "w") as fh:
    fh.write(dotgit)
shutil.rmtree(EVIL)
CW = os.path.join(GD, "config.worktree")
with open(CW, "w") as fh:
    fh.write(f"[core]\n\tpager = touch {PWN}\n")
r = refused(H.facts_worktree, "~/projects/repo-wt")
check("config.worktree самой worktree с core.pager → отказ", r and r[0] == "bad" and "core.pager" in r[1], r)
os.unlink(CW)

reset()
clear_log()
rc, rid, out = touch("worktree-remove", "~/projects/repo-wt", "--task", "metis-0775", "--why", "ветка слита")
check("заявка worktree-remove: код 0, текст окна с путём, веткой и HEAD", rc == 0 and rid and
      "Удалить worktree ~/projects/repo-wt (ветка feat" in out, out)
run()
check("[0775] палец → worktree и её gitdir удалены, git её не видит, без сообщения в окне роли",
      not os.path.exists(WT) and not os.path.exists(GD) and result(qdir(), rid)["state"] == "done"
      and "repo-wt" not in g(MAIN, "worktree", "list"), result(qdir(), rid))

# грязная после заявки → status после пальца, до удаления: worktree цела
g(MAIN, "worktree", "prune")
g(MAIN, "worktree", "add", "-q", "-B", "feat", WT, "origin/main")
reset()
rc, rid, _ = touch("worktree-remove", "~/projects/repo-wt", "--task", "metis-0775")


def dirty_wt():
    with open(os.path.join(WT, "late.txt"), "w") as fh:
        fh.write("x")


ANSWER["during"] = dirty_wt
run()
check("worktree стала грязной, пока окно было открыто → не удалена, итог «своё»", os.path.isdir(WT) and
      os.path.exists(os.path.join(WT, "late.txt")) and result(qdir(), rid)["state"] == "failed"
      and "своё" in result(qdir(), rid)["note"], result(qdir(), rid))
os.unlink(os.path.join(WT, "late.txt"))
facts_wt = H.facts_worktree("~/projects/repo-wt")
with open(os.path.join(GD, "locked"), "w") as fh:
    fh.write("x")
r = refused(H.exec_worktree, {"id": "20261105-000000-cccccc"}, facts_wt)
check("заперли после фактов → исполнитель перепроверяет gitdir и не удаляет", r and r[0] == "yes" and
      os.path.isdir(WT), r)
os.unlink(os.path.join(GD, "locked"))
with open(CW, "w") as fh:
    fh.write(f"[core]\n\tpager = touch {PWN}\n")
r = refused(H.exec_worktree, {"id": "20261105-000000-dddddd"}, facts_wt)
check("config.worktree появился после фактов → исполнитель отказывает, worktree цела", r and r[0] == "bad" and
      os.path.isdir(WT) and not os.path.exists(PWN), r)
os.unlink(CW)

# --- git у владельца вне песочницы: config роли не исполняется (круг 2: частный GIT_DIR и белый список) -------------
with open(os.path.join(HOME, ".gitconfig"), "w") as fh:
    fh.write("[user]\n\tname = Global\n")
g(MAIN, "config", "user.name", "Role")
with H.private_git(MAIN) as pg:
    r_glob = refused(H.run_git, ["config", "--get", "user.name"], pg["env"], pg["dir"])
    hooks = H.run_git(["config", "--get", "core.hooksPath"], pg["env"], pg["dir"]).strip()
    fsm = H.run_git(["config", "--get", "core.fsmonitor"], pg["env"], pg["dir"]).strip()
    tmpd = pg["dir"]
check("git у владельца не читает ни ~/.gitconfig, ни config роли (частный GIT_DIR)", r_glob is not None, r_glob)
check("защитные ключи заданы через GIT_CONFIG_COUNT: hooksPath=/dev/null, fsmonitor=false",
      hooks == b"/dev/null" and fsm == b"false", (hooks, fsm))
check("частный GIT_DIR убран после работы", not os.path.exists(tmpd), tmpd)
os.unlink(os.path.join(HOME, ".gitconfig"))
g(MAIN, "config", "--unset", "user.name")

CONF = os.path.join(MAIN, ".git", "config")
with open(CONF, "rb") as fh:
    conf0 = fh.read()
with open(os.path.join(MAIN, ".gitattributes"), "w") as fh:
    fh.write("* filter=evil diff=evil\n")
for name, extra, want in [
        ("filter", f'[filter "evil"]\n\tclean = touch {PWN}\n', "filter.evil.clean"),
        ("BOM и filter", f'﻿[filter "evil"]\n\tsmudge = touch {PWN}\n', "filter.evil.smudge"),
        ("include", f"[include]\n\tpath = {PWN}.inc\n", "include.path"),
        ("includeIf", f'[includeIf "gitdir:/"]\n\tpath = {PWN}.inc\n', "includeif.gitdir:/.path"),
        ("core.sshCommand", f"[core]\n\tsshCommand = touch {PWN}\n", "core.sshcommand"),
        ("строка не по формату", "[core\n\tpager = x\n", "git config"),
        ("ключ в старом виде [a.b]", f"[diff.evil]\n\ttextconv = touch {PWN}\n", "diff.evil.textconv")]:
    with open(PWN + ".inc", "w") as fh:   # с --includes git прочёл бы его и упал на строке не по формату
        fh.write(f'[filter "evil"\n\tclean = touch {PWN}\n')
    with open(CONF, "wb") as fh:
        fh.write((extra.encode("utf-8") + conf0) if name.startswith("BOM") else (conf0 + extra.encode("utf-8")))
    r = refused(H.facts_deploy, "~/projects/repo")
    check(f"config роли: {name} → отказ до любого git с config роли, ничего не исполнено",
          r and r[0] == "bad" and want in r[1] and not os.path.exists(PWN), (r, os.path.exists(PWN)))
with open(CONF, "wb") as fh:
    fh.write(conf0)
os.unlink(os.path.join(MAIN, ".gitattributes"))
os.unlink(PWN + ".inc")
os.symlink(CONF, os.path.join(MAIN, ".git", "config.worktree"))
r = refused(H.facts_deploy, "~/projects/repo")
check("config.worktree — ссылка → отказ", r and r[0] == "bad", r)
os.unlink(os.path.join(MAIN, ".git", "config.worktree"))

# --- deploy.sh: байты из коммита, bash -s, дерево до и после ------------------------------------------------------
marker = os.path.join(MAIN, ".deployed-marker")
reset()
rc, rid, out = touch("deploy", "~/projects/repo", "--task", "metis-0775")
check("заявка deploy: текст с хешем deploy.sh из коммита и HEAD", rc == 0 and "deploy.sh " in out and "из коммита" in out
      and "HEAD " in out, out)
run()
check("[0775] палец → deploy.sh исполнен один раз, журнал в STATE/handoff/runs", os.path.exists(marker) and
      result(qdir(), rid)["state"] == "done" and os.path.exists(os.path.join(STATE, "handoff", "runs", f"{rid}.log"))
      and "изменилось" not in result(qdir(), rid)["note"], result(qdir(), rid))
os.unlink(marker)
reset()
rc, rid, _ = touch("deploy", "~/projects/repo", "--task", "metis-0775")
with open(os.path.join(MAIN, "deploy.sh"), "a") as fh:
    fh.write("echo extra\n")
g(MAIN, "commit", "-qam", "deploy changed")
run()
check("deploy.sh сменился после заявки → снято без окна и без запуска", not ASKED and not os.path.exists(marker)
      and result(qdir(), rid)["state"] == "dropped", result(qdir(), rid))

r = refused(H.facts_deploy, "~/projects/repo-wt")
check("deploy из worktree → отказ", r and r[0] == "bad" and "worktree" in r[1], r)
COMMITTED = H.facts_deploy("~/projects/repo")
EVILM = os.path.join(_ROOT, "evil-ran")
with open(os.path.join(MAIN, "deploy.sh"), "w") as fh:
    fh.write(f'touch "{EVILM}"\n')
facts = H.facts_deploy("~/projects/repo")
check("факты deploy: байты из коммита HEAD, а не файл с диска", facts["script"] == COMMITTED["script"] and
      b"evil-ran" not in facts["bytes"], facts["desc"])
r = refused(H.exec_deploy, {"id": "20261105-000000-eeeeee"}, facts)
check("deploy: правка в дереве после пальца → отказ без запуска", r and r[0] == "yes" and not os.path.exists(marker)
      and not os.path.exists(EVILM), r)
real_dirty = H.dirty
H.dirty = lambda g_, work: None   # гонка: дерево сменилось между проверкой и запуском
try:
    H.exec_deploy({"id": "20261105-000000-aaaaaa"}, facts)
finally:
    H.dirty = real_dirty
check("deploy.sh подменён на диске → исполнены байты из коммита (bash -s), а не файл",
      os.path.exists(marker) and not os.path.exists(EVILM), (os.path.exists(marker), os.path.exists(EVILM)))
g(MAIN, "checkout", "-q", "--", "deploy.sh")
os.unlink(marker)
r = refused(H.exec_deploy, {"id": "20261105-000000-bbbbbb"}, dict(facts, bytes=b"touch x\n"))
check("deploy: байты не того хеша → отказ без запуска", r and "не те" in r[1], r)
with open(os.path.join(MAIN, "untracked.txt"), "w") as fh:
    fh.write("x")
r = refused(H.exec_deploy, {"id": "20261105-000000-ffffff"}, facts)
check("deploy: неотслеживаемый файл → отказ без запуска", r and r[0] == "yes" and not os.path.exists(marker), r)
os.unlink(os.path.join(MAIN, "untracked.txt"))
with open(os.path.join(MAIN, "dirty.txt"), "w") as fh:
    fh.write("x")
g(MAIN, "add", "dirty.txt")
reset()
rc, rid, _ = touch("deploy", "~/projects/repo", "--task", "metis-0775")
run()
check("deploy с незакоммиченными правками → после пальца отказ, deploy.sh не исполнен", not os.path.exists(marker)
      and result(qdir(), rid)["state"] == "failed", result(qdir(), rid))
g(MAIN, "reset", "-q", "--hard")
with open(os.path.join(MAIN, ".gitmodules"), "w") as fh:
    fh.write('[submodule "s"]\n\tpath = s\n\turl = x\n')
g(MAIN, "add", ".gitmodules")
g(MAIN, "commit", "-qm", "modules")
r = refused(H.exec_deploy, {"id": "20261105-000000-111111"}, H.facts_deploy("~/projects/repo"))
check("deploy: в репозитории .gitmodules → отказ без запуска", r and r[0] == "yes" and not os.path.exists(marker), r)
g(MAIN, "rm", "-q", ".gitmodules")
g(MAIN, "commit", "-qm", "no modules")
with open(os.path.join(MAIN, "deploy.sh"), "w") as fh:
    fh.write('echo x > "$PWD/after.txt"\n')
g(MAIN, "commit", "-qam", "deploy leaves a file")
note = H.exec_deploy({"id": "20261105-000000-222222"}, H.facts_deploy("~/projects/repo"))
check("deploy оставил файл в дереве → итог говорит об этом", "дерево изменилось" in note and "after.txt" in note, note)
os.unlink(os.path.join(MAIN, "after.txt"))
os.symlink("deploy.sh", os.path.join(MAIN, "deploy-link.sh"))
g(MAIN, "rm", "-q", "deploy.sh")
os.rename(os.path.join(MAIN, "deploy-link.sh"), os.path.join(MAIN, "deploy.sh"))
g(MAIN, "add", "deploy.sh")
g(MAIN, "commit", "-qm", "deploy is a link")
r = refused(H.facts_deploy, "~/projects/repo")
check("deploy.sh в коммите — ссылка → отказ", r and r[0] == "bad" and "обычным файлом" in r[1], r)
check("за весь раздел ни один драйвер, фильтр или pager роли не исполнен", not os.path.exists(PWN))
check("CDP_PORTS = browser.BROWSERS", H.CDP_PORTS == P.browser_mod().BROWSERS, (H.CDP_PORTS,
                                                                                  P.browser_mod().BROWSERS))

# ===================================================================================================================
# [хук] PostToolUseFailure, PermissionDenied → PostToolBatch
# ===================================================================================================================
HENV = {"HOME": HOME, "PANTHEON_STATE": STATE, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "CLAUDE_PID": "4242"}


def hook(cmd, ev, **extra):
    e = dict(HENV, **extra)
    r = subprocess.run([PY311, "-I", HOOK, cmd], input=json.dumps(ev) if not isinstance(ev, str) else ev, env=e,
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout.strip(), r.stderr


def ctx_of(out):
    try:
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        return ""


clear_log()
rc, out, er = hook("fail", {"tool_name": "Bash", "tool_input": {"command": "curl -s 127.0.0.1:9333/health"},
                            "error": "curl: (7) Failed to connect: Operation not permitted", "is_interrupt": False})
check("хук fail: отказ песочницы на порт демона → подсказка Харон, запрет команды владельцу",
      rc == 0 and "Харон" in ctx_of(out) and H.NO_TERMINAL in ctx_of(out)
      and json.loads(out)["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure", (out, er))
rc, out, _ = hook("fail", {"tool_name": "Bash", "tool_input": {"command": "pytest"}, "error": "AssertionError: 1 != 2"})
check("хук fail: красный тест → без вывода", rc == 0 and out == "", out)
rc, out, _ = hook("fail", {"tool_name": "Bash", "tool_input": {"command": "x"}, "error": "Operation not permitted",
                           "is_interrupt": True})
check("хук fail: прерывание владельцем → без вывода", rc == 0 and out == "", out)
rc, out, _ = hook("fail", {"tool_name": "Bash", "tool_input": {"command": "tg-read chats"},
                           "error": "zsh: command not found: tg-read"})
check("хук fail: команды нет → подсказка read", "read request" in ctx_of(out), out)
for bad in ["", "[]", "not json", '{"error": 5}']:
    rc, out, _ = hook("fail", bad)
    check(f"хук fail: плохой вход {bad!r} → код 0 без вывода", rc == 0 and out == "", out)
rc, out, _ = hook("zap", {})
check("хук: неизвестная команда → код 0 без вывода", rc == 0 and out == "")

HINTD = os.path.join(STATE, "handoff", "hint")
ev = {"session_id": "s-1", "tool_name": "Bash", "tool_input": {"command": "launchctl kickstart gui/501/x"},
      "reason": "Self-Modification"}
rc, out, _ = hook("denied", ev)
mark = os.path.join(HINTD, "4242.s-1.json")
check("хук denied: вывода нет (канала к модели нет), отметка <pid>.<sid>.json", rc == 0 and out == ""
      and os.path.exists(mark), os.listdir(HINTD) if os.path.isdir(HINTD) else None)
rc, out, _ = hook("batch", {"session_id": "s-1", "agent_id": "sub-9"})
check("хук batch: отметка главной сессии, а пачка субагента → без вывода, отметка цела", out == "" and
      os.path.exists(mark), out)
rc, out, _ = hook("batch", {"session_id": "s-1"}, CLAUDE_PID="999")
check("хук batch: другой процесс → своей отметки нет", out == "" and os.path.exists(mark), out)
rc, out, _ = hook("batch", {"session_id": "s-1"})
check("хук batch: своя отметка → подсказка Гестии, отметка снята", "Гестия" in ctx_of(out) and
      "классификатор" in ctx_of(out) and not os.path.exists(mark), out)
rc, out, _ = hook("batch", {"session_id": "s-1"})
check("хук batch: второй раз → без вывода", out == "", out)
hook("denied", dict(ev, agent_id="sub-9"))
rc, out, _ = hook("batch", {"session_id": "s-1", "agent_id": "sub-9"})
check("хук batch: отметка субагента → выдаётся его пачке", "Гестия" in ctx_of(out), out)
hook("denied", ev)
with open(mark, encoding="utf-8") as fh:
    m = json.load(fh)
m["t"] = time.time() - H.HINT_TTL - 5
with open(mark, "w", encoding="utf-8") as fh:
    json.dump(m, fh)
rc, out, _ = hook("batch", {"session_id": "s-1"})
check("хук batch: отметка старше HINT_TTL → без вывода, снята", out == "" and not os.path.exists(mark), out)

# оболочка hooks.json: без отметки python не запускается
with open(os.path.join(PLUGIN, "hooks", "hooks.json"), encoding="utf-8") as fh:
    HJ = json.load(fh)["hooks"]
cmds = {ev_: [h["command"] for m_ in HJ.get(ev_, []) for h in m_["hooks"]] for ev_ in
        ("PostToolUseFailure", "PermissionDenied", "PostToolBatch")}
check("hooks.json: refusal.py fail / denied / batch на своих событиях",
      any(c.endswith('refusal.py" fail') for c in cmds["PostToolUseFailure"])
      and any(c.endswith('refusal.py" denied') for c in cmds["PermissionDenied"])
      and any('refusal.py" batch' in c for c in cmds["PostToolBatch"]), cmds)
SH = next((c for c in cmds["PostToolBatch"] if 'refusal.py" batch' in c), "echo PYTHON-STARTED")
FAKE_ROOT = os.path.join(_ROOT, "fake-plugin")
os.makedirs(os.path.join(FAKE_ROOT, "hooks"))
with open(os.path.join(FAKE_ROOT, "hooks", "python.sh"), "w") as fh:
    fh.write('#!/bin/sh\necho "PYTHON-STARTED $*"\n')


def shell(pid, root=FAKE_ROOT):
    e = dict(HENV, CLAUDE_PLUGIN_ROOT=root, PATH=HENV["PATH"])
    if pid is None:
        e.pop("CLAUDE_PID")
    else:
        e["CLAUDE_PID"] = pid
    r = subprocess.run(["sh", "-c", SH], input=json.dumps({"session_id": "s-2"}), env=e, capture_output=True,
                       text=True, timeout=60)
    return r.stdout.strip(), r.returncode


check("оболочка PostToolBatch: отметок нет → python не запускается", shell("4242") == ("", 0), shell("4242"))
hook("denied", dict(ev, session_id="s-2"))
check("оболочка: отметка другого процесса → не запускается", shell("1") == ("", 0), shell("1"))
check("оболочка: CLAUDE_PID не число → ищет nopid.*", shell("42a") == ("", 0), shell("42a"))
check("оболочка: своя отметка → python один раз", shell("4242") == (
    f"PYTHON-STARTED {FAKE_ROOT}/hooks/refusal.py batch", 0), shell("4242"))
out, rc = shell("4242", PLUGIN)
check("оболочка с настоящим плагином: подсказка выдана, отметка снята", "Гестия" in ctx_of(out) and
      not os.path.exists(os.path.join(HINTD, "4242.s-2.json")), out)

# ===================================================================================================================
# [журнал] три типовых отказа → строка доски
# ===================================================================================================================
clear_log()
hook("fail", {"tool_name": "Bash", "tool_input": {"command": "pnpm dev"}, "error": "listen EPERM: operation not "
              "permitted 127.0.0.1:3000"}, PANTHEON_TMP=os.path.join(CACHES, "win-c", "tmp"), PANTHEON_ROLE="dev-opus")
hook("denied", {"session_id": "s-3", "tool_name": "Bash", "tool_input": {"command": "curl 127.0.0.1:9334/eval"},
                "reason": "classifier"})
hook("fail", {"tool_name": "Bash", "tool_input": {"command": "tg-read"}, "error": "zsh: command not found: tg-read"})
L = log_lines()
check("журнал: три отказа — источник, кому передано, итог", [(e["source"], e["kind"], e["outcome"]) for e in L] ==
      [("sandbox", "outside", "handed"), ("classifier", "browser", "handed"), ("nocmd", "telegram", "handed")], L)
check("журнал: окно и роль хука — по PANTHEON_TMP и PANTHEON_ROLE", L and L[0].get("window") == "win-c"
      and L[0].get("role") == "dev-opus", L[:1])
rows, src = boardtext.handoffs(STATE, time.time())
line = boardtext.handoff_line(rows, src)
check("доска: «Отказы за сутки (источники): кому ×N — итог»", line and line.startswith(
    "- Отказы за сутки (классификатор 1, нет команды 1, песочница 1): ") and "браузер → Харон ×1 — передано 1" in line
      and "тесты и серверы → outside ×1 — передано 1" in line and "Telegram → read ×1 — передано 1" in line, line)
H.log("role", "touch", "waiting", id="20261105-120000-abcdef")
H.log("role", "touch", "done", id="20261105-120000-abcdef")
rows, src = boardtext.handoffs(STATE, time.time())
check("доска: заявка Touch ID — одно действие по последнему итогу", ("touch", 1, {"done": 1}) in rows
      and src.get("role") == 1, (rows, src))
with open(H.log_path(), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"t": time.time(), "source": "sandbox", "kind": "rm -rf /", "outcome": "handed"}) + "\n")
    fh.write("garbage\n")
rows, _ = boardtext.handoffs(STATE, time.time())
check("доска: вид не из словаря и мусор не показываются", all(r[0] in boardtext.HANDOFF_TO for r in rows), rows)
check("доска: старше суток не считается", boardtext.handoffs(STATE, time.time() + 2 * 86400) == ([], {}))
# время строки округлено и может обогнать часы читателя на доли секунды; дальше минуты вперёд — не считается
SKEW = os.path.join(_ROOT, "skew-state")
os.makedirs(os.path.join(SKEW, "logs"))
NOW = 1_800_000_000.0
with open(boardtext.handoff_log(SKEW), "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"t": NOW + 0.0004, "source": "sandbox", "kind": "browser", "outcome": "handed"}) + "\n")
    fh.write(json.dumps({"t": NOW + 30, "source": "sandbox", "kind": "outside", "outcome": "handed"}) + "\n")
    fh.write(json.dumps({"t": NOW + 600, "source": "sandbox", "kind": "telegram", "outcome": "handed"}) + "\n")
rows_skew, _ = boardtext.handoffs(SKEW, NOW)
check("доска: строка чуть «из будущего» (округление, сдвиг часов до минуты) считается, дальше — нет",
      sorted(r[0] for r in rows_skew) == ["browser", "outside"], rows_skew)
check("словари доски = словари handoff (SEC-13)", set(boardtext.HANDOFF_TO) == set(H.ROUTE_KEYS)
      and boardtext.HANDOFF_OUT == H.OUTCOME_RU and boardtext.HANDOFF_SRC == H.SOURCE_RU,
      (set(boardtext.HANDOFF_TO) ^ set(H.ROUTE_KEYS)))
check("доска: файл журнала отказов — в отпечатке свежести",
      H.log_path() in boardtext.watch_files(os.path.join(HOME, "ai", "pantheon"), STATE))

# ingest: окно — по месту, время не из будущего
os.makedirs(qdir("win-d"), exist_ok=True)
with open(os.path.join(qdir("win-d"), "log.jsonl"), "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"t": time.time() + 10 ** 6, "source": "role", "kind": "hestia", "outcome": "handed",
                         "window": "zeus", "task": "metis-1"}) + "\n")
clear_log()
H.ingest_logs()
L = log_lines()
check("перенос журнала окна: окно по месту папки (не из строки), время не из будущего",
      len(L) == 1 and L[0].get("window") == "win-d" and L[0]["t"] <= time.time() + 1, L)

# ===================================================================================================================
# тик: проход только при деле
# ===================================================================================================================
for n in os.listdir(CACHES):
    shutil.rmtree(os.path.join(CACHES, n, "handoff"), ignore_errors=True)
shutil.rmtree(qdir(), ignore_errors=True)
DRY = os.path.join(STATE, "dryrun.log")
with env(PANTHEON_DRYRUN="1"):
    P.handoff_kick()
check("тик: заявок нет → проход не запускается", "handoff-run" not in (open(DRY).read() if os.path.exists(DRY)
                                                                        else ""))
rc, rid, _ = touch("cdp-restart", "comet", "--task", "metis-0832", win="win-e")
with env(PANTHEON_DRYRUN="1"):
    P.handoff_kick()
check("тик: заявка в кэше окна → проход запускается", "handoff-run" in (open(DRY).read() if os.path.exists(DRY)
                                                                          else ""))

# ===================================================================================================================
# [только да] шаблоны ролей и hq: владельцу — только «да/нет», раздел handoff подключён
# ===================================================================================================================
ROLES = os.path.join(PLUGIN, "roles")
FORBIDDEN = re.compile(r"выполните\s+в\s+терминале|сделайте\s+сам|запустите\s+сам|перезапустите\s+сам|"
                       r"в\s+сво[её]м\s+терминале|из\s+его\s+терминала|в\s+терминале\s+владельца|"
                       r"владел\w*\s+(?:выполн|запуст|введ)\w*\s+(?:команд|в\s+терминал)", re.I)
srcs = sorted([os.path.join(ROLES, n) for n in os.listdir(ROLES) if n.endswith(".tmpl")] +
              [os.path.join(ROLES, "_parts", n) for n in os.listdir(os.path.join(ROLES, "_parts"))])
hits = []
for p in srcs:
    with open(p, encoding="utf-8") as fh:
        for i, ln in enumerate(fh, 1):
            if FORBIDDEN.search(ln):
                hits.append(f"{os.path.basename(p)}:{i}: {ln.strip()[:120]}")
check("шаблоны ролей и hq: нет «выполните в терминале / сделайте сами» для владельца", not hits, hits)
check("образец запрета ловит «выполните в терминале» и «сделайте сами»",
      FORBIDDEN.search("Владелец, выполните в терминале: pantheon x") and FORBIDDEN.search("сделайте сами"))
for n in ("dev-opus", "dev-sonnet", "dev-haiku", "codex-dev", "apollo", "hephaestus", "domain-coordinator",
          "workshop"):
    with open(os.path.join(ROLES, f"{n}.tmpl"), encoding="utf-8") as fh:
        check(f"шаблон {n}: раздел handoff подключён", "{{> handoff}}" in fh.read())
with open(os.path.join(ROLES, "_parts", "handoff.part"), encoding="utf-8") as fh:
    part = fh.read()
for word in ("Харон", "Гести", "pantheon outside", "pantheon read", "pantheon handoff touch", "«да/нет»", "Touch ID"):
    check(f"handoff.part называет «{word}»", word in part)
with open(os.path.join(ROLES, "hq.tmpl"), encoding="utf-8") as fh:
    hq = fh.read()
_step5 = hq[hq.index("Себя: допиши"):hq.index("## Прямые разговоры")]
check("hq: перезапуск Зевса — «да/нет» владельцу, без команды и без Гестии (guard ей pantheon start запрещает)",
      "«Перезапустить Зевса?»" in _step5 and "pantheon start" not in _step5 and "wake hestia" not in _step5, _step5)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
