# ruff: noqa: F405
"""`pantheon secret put|list` (metis-1135, lib/outside_secret.py): ключ проекта направления кладёт владелец скрытым
вводом в своём терминале; из окна Claude Code и без терминала — отказ, код 1, файл не тронут. Значения нет ни в выводе,
ни в подсказке ввода, ни в `list`; файл — тот, что читает dev_keys (serve и login вне окна роли), 600 в папке 700.
Запуск: python3.14 -I tests/test_outside_secret.py."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _outside_common import *  # noqa: F403,E402

ENV = O.env_dir()
VALUE = "sk_live_Abc#1$x'q=z"        # кавычка, #, $ и = — читается обратно как есть
OLD = "old-value-777"
DEV = os.path.join(ENV, "latark__app.env")


class _Tty:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


S = O.sub_mod("secret")
_real_stdin, _real_gp = S.sys.stdin, S.getpass.getpass
_answer = [VALUE]
_prompts = []


def _gp(prompt):
    _prompts.append(prompt)
    v = _answer[0]
    if isinstance(v, BaseException):
        raise v
    return v


def secret(*args, tty=True, via="pantheon"):
    """Команда через main pantheon (`pantheon secret …`) или outside (`pantheon outside secret …`) → (код, вывод)."""
    S.sys.stdin = _Tty(tty)
    S.getpass.getpass = _gp
    out, errb = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errb):
            rc = P.main(["secret", *args]) if via == "pantheon" else O.main(["secret", *args])
    finally:
        S.sys.stdin, S.getpass.getpass = _real_stdin, _real_gp
    return rc, out.getvalue() + errb.getvalue()


def text(p):
    return open(p).read() if os.path.exists(p) else ""


os.makedirs(ENV, mode=0o700, exist_ok=True)
with open(DEV, "w") as fh:
    fh.write(f"# владельца\nAPI_KEY={OLD}\nOTHER=1\n")
os.chmod(DEV, 0o600)

for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
    os.environ[var] = "1"
    try:
        rc, out = secret("put", "athena-x", "API_KEY")
    finally:
        os.environ.pop(var)
    check(f"put: из окна Claude Code ({var}) — отказ, код 1, файл не тронут, ввода не было",
          rc == 1 and OLD in text(DEV) and not _prompts and out.strip().splitlines()[-1].startswith("pantheon secret"),
          (rc, out))
rc, out = secret("put", "athena-x", "API_KEY", tty=False)
check("put: без терминала — отказ, код 1, файл не тронут", rc == 1 and OLD in text(DEV) and not _prompts, (rc, out))
for bad, why in (("PATH", "служебное"), ("PANTHEON_X", "служебное"), ("DYLD_INSERT", "служебное"),
                 ("1BAD", "не имя"), ("SUPABASE_DB_URL", "ключ тестов")):
    rc, out = secret("put", "athena-x", bad)
    check(f"put: имя {bad} ({why}) — код 2, ввода не было", rc == 2 and not _prompts and why in out, (rc, out))
rc, out = secret("put", "athena-x")
check("put: без имени — код 2", rc == 2, (rc, out))
rc, out = secret("put", "athena-x", "API_KEY", "--bogus", "1")
check("put: неизвестный флаг — код 2", rc == 2 and not _prompts, (rc, out))
rc, out = secret("put", "../etc", "API_KEY")
check("put: не имя направления — код 2", rc == 2 and not _prompts, (rc, out))
rc, out = secret("put", "nobody-dir", "API_KEY")
check("put: направления нет в domains.json — код 1, ввода не было", rc == 1 and not _prompts, (rc, out))
rc, out = secret("put", "athena-x", "API_KEY", "--repo", "latark/other")
check("put: --repo не из проектов направления — код 1", rc == 1 and not _prompts, (rc, out))
_answer[0] = "two\nlines"
rc, out = secret("put", "athena-x", "API_KEY")
check("put: значение в две строки — код 1, файл не тронут, значения в выводе нет",
      rc == 1 and OLD in text(DEV) and "lines" not in out, (rc, out))
_answer[0] = EOFError()
rc, out = secret("put", "athena-x", "API_KEY")
check("put: ввод прерван — код 1, файл не тронут", rc == 1 and OLD in text(DEV), (rc, out))

_prompts.clear()
_answer[0] = VALUE
rc, out = secret("put", "athena-x", "API_KEY")
body = text(DEV)
check("put: записан — код 0, значения нет ни в выводе, ни в подсказке ввода",
      rc == 0 and VALUE not in out and _prompts and all(VALUE not in p for p in _prompts) and "API_KEY" in out, (rc, out))
check("put: старое значение заменено, свои строки файла целы", OLD not in body and "OTHER=1" in body
      and "# владельца" in body, body)
check("put: ключ получат serve и login — dev_keys проекта отдаёт его как есть",
      O.dev_keys("latark/app")[0].get("API_KEY") == VALUE, O.dev_keys("latark/app")[0].keys())
check("put: файл 600, папка 700", (os.stat(DEV).st_mode & 0o777) == 0o600 and (os.stat(ENV).st_mode & 0o777) == 0o700,
      (oct(os.stat(DEV).st_mode), oct(os.stat(ENV).st_mode)))
check("put: временных файлов не осталось", sorted(os.listdir(ENV)) == ["latark__app.env"], os.listdir(ENV))

rc, out = secret("put", "athena-x", "WEB_KEY", "--app", "web", via="outside")
APPF = os.path.join(ENV, "latark__app__web.env")
check("put --app через `outside secret`: файл приложения, dev_keys приложения отдаёт ключ",
      rc == 0 and O.dev_keys("latark/app", "web")[0].get("WEB_KEY") == VALUE and VALUE not in out
      and (os.stat(APPF).st_mode & 0o777) == 0o600, (rc, out))
rc, out = secret("list", "athena-x")
check("list: только имена ключей обоих файлов, значений нет", rc == 0 and "API_KEY" in out and "WEB_KEY" in out
      and "OTHER" in out and VALUE not in out and OLD not in out, (rc, out))

_answer[0] = ""
rc, out = secret("put", "athena-x", "API_KEY")
check("put: пустой ввод убирает ключ, остальное цело", rc == 0 and "API_KEY" not in text(DEV)
      and "OTHER=1" in text(DEV) and "убран" in out, (rc, text(DEV)))

_pth = os.path.join(HOME, "pantheon-env-link")
os.rename(ENV, _pth)
os.symlink(_pth, ENV)
_answer[0] = VALUE
try:
    rc, out = secret("put", "athena-x", "API_KEY")
    check("put: папка ключей — ссылка, отказ, код 1, через ссылку не записано",
          rc == 1 and "API_KEY" not in text(os.path.join(_pth, "latark__app.env")), (rc, out))
finally:
    os.unlink(ENV)
    os.rename(_pth, ENV)

# --- ask / run: ввод владельцем в окне Touch ID со скрытым полем (metis-1135) --------------------------------------
_win = os.path.join(HOME, "Library", "Caches", "pantheon-sandbox", "athena-x")
os.makedirs(os.path.join(_win, "tmp"), exist_ok=True)
_calls = []
_touch, _val = [0], [VALUE]
S.touch_window = lambda t: (_calls.append(("touch", t)), _touch[0])[1]
S.ask_value = lambda t: (_calls.append(("ask", t)), _val[0])[1]
S.P.idle_sec = lambda: 0
S.P.merge_mod().clean_env = lambda: None    # окружение теста; сам clean_env — test_merge_env.py
QD = os.path.join(_win, "secret")


def ask(*args):
    os.environ["PANTHEON_TMP"] = os.path.join(_win, "tmp")
    try:
        return secret("ask", *args)
    finally:
        os.environ.pop("PANTHEON_TMP")


def run():
    return secret("run")


def results():
    return sorted((json.load(open(os.path.join(QD, f))) for f in os.listdir(QD) if f.endswith(".result.json")),
                  key=lambda r: r["time"])


rc, out = ask("athena-x", "API_KEY")
check("ask: без --task — код 2, заявки нет", rc == 2 and not os.path.isdir(QD), (rc, out))
rc, out = ask("athena-x", "PATH", "--task", "athena-0001")
check("ask: служебное имя — код 2", rc == 2, (rc, out))
rc, out = ask("athena-x", "API_KEY", "--task", "athena-0001")
reqs = [f for f in os.listdir(QD) if f.endswith(".req.json")]
check("ask: из окна роли — заявка в кэше окна, без значения", rc == 0 and len(reqs) == 1
      and VALUE not in open(os.path.join(QD, reqs[0])).read(), (rc, out, reqs))
os.environ["CLAUDECODE"] = "1"
try:
    rc, out = run()
finally:
    os.environ.pop("CLAUDECODE")
check("run: из окна Claude Code — отказ, код 1, окон не было", rc == 1 and not _calls, (rc, out))
S.P.idle_sec = lambda: 10_000
rc, out = run()
check("run: владельца нет у Mac — окна нет, заявка ждёт", rc == 0 and not _calls and S.pending(), _calls)
S.P.idle_sec = lambda: 0
_touch[0] = 1
rc, out = run()
check("run: отказ в окне Touch ID — отклонено, окна ввода не было, файл не тронут",
      [c[0] for c in _calls] == ["touch"] and results()[-1]["status"] == "declined" and "API_KEY" not in text(DEV)
      and not S.pending(), (_calls, results()))
_calls.clear()
_touch[0] = 0
ask("athena-x", "API_KEY", "--task", "athena-0001")
_val[0] = None
run()
check("run: окно ввода закрыто без ответа — ждёт повтора, файл не тронут",
      results()[-1]["status"] == "waiting" and "API_KEY" not in text(DEV) and not S.pending(), results())
for f in os.listdir(QD):
    if f.endswith(".result.json") and json.load(open(os.path.join(QD, f)))["status"] == "waiting":
        os.unlink(os.path.join(QD, f))
_calls.clear()
_val[0] = VALUE
rc, out = run()
logs = open(os.path.join(STATE, "logs", "secret.jsonl")).read()
check("run: палец и ввод — ключ записан, dev_keys отдаёт его; значения нет ни в выводе, ни в итоге, ни в журнале",
      rc == 0 and O.dev_keys("latark/app")[0].get("API_KEY") == VALUE and VALUE not in out and VALUE not in logs
      and all(VALUE not in json.dumps(r) for r in results()) and results()[-1]["status"] == "done"
      and [c[0] for c in _calls] == ["touch", "ask"] and all(VALUE not in c[1] for c in _calls), (out, results()))
check("run: заявка снята после итога", not [f for f in os.listdir(QD) if f.endswith(".req.json")], os.listdir(QD))
rc, out = ask("athena-x", "API_KEY", "--task", "athena-0001")
rid = out.split()[1].rstrip(":")
_p = os.path.join(QD, f"{rid}.req.json")
_r = json.load(open(_p))
_r["created"] -= 2 * 86400
json.dump(_r, open(_p, "w"))
_calls.clear()
run()
check("run: заявка старше суток — снята без окон", not _calls and json.load(open(os.path.join(QD, f"{rid}.result.json")))
      ["status"] == "dropped" and not os.path.exists(_p), results())
_calls.clear()
ask("athena-x", "API_KEY", "--task", "athena-0001")
_real_q = os.path.join(HOME, "secret-real-q")
os.rename(QD, _real_q)
os.symlink(_real_q, QD)
try:
    run()
    check("run: папка очереди окна — ссылка, проход её не читает, окон не было", not _calls, _calls)
finally:
    os.unlink(QD)
    os.rename(_real_q, QD)

# --- metis-1293: ключи Supabase для serve принимаются, строка базы тестов — нет ----------------------------------
check("name_problem: SUPABASE_SECRET_KEY и NEXT_PUBLIC_SUPABASE_URL принимаются (serve берёт их из env)",
      S.name_problem("SUPABASE_SECRET_KEY") is None and S.name_problem("NEXT_PUBLIC_SUPABASE_URL") is None,
      (S.name_problem("SUPABASE_SECRET_KEY"), S.name_problem("NEXT_PUBLIC_SUPABASE_URL")))
check("name_problem: SUPABASE_DB_URL по-прежнему отказ (ключ тестов, кладёт outside key)",
      "outside key" in (S.name_problem("SUPABASE_DB_URL") or ""), S.name_problem("SUPABASE_DB_URL"))

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
