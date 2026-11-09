# ruff: noqa: F405
"""Ключи тестов outside (metis-1016, athena-0297 вариант А): строка подключения к базе одного проекта — только
`outside test --script` этого проекта; не проверке проекта, не серверу, не другим проектам. Профиль прогона — сеть
только на порт базы; pg_dump из libpq в PATH только этому прогону; значения не попадают в журнал, итог, status и
outside.jsonl; `pantheon outside key` кладёт значение скрытым вводом. Запуск: python3.14 -I tests/test_outside_test_keys.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _outside_common import *  # noqa: F403,E402

PW = "S3cr/t-pw-xyz"                       # пароль как есть; в строке — %2F
URL_APP = "postgresql://postgres.abcd:S3cr%2Ft-pw-xyz@aws-0-eu.pooler.supabase.com:6543/postgres"
URL_OTHER = "postgresql://postgres.other:0ther-only-pw@db.other.supabase.co:5432/postgres"
SECRETS = (URL_APP, PW, "S3cr%2Ft-pw-xyz", URL_OTHER, "0ther-only-pw")

TENV = O.test_env_dir()
os.makedirs(TENV, mode=0o700, exist_ok=True)
os.makedirs(O.env_dir(), mode=0o700, exist_ok=True)


def put(where, name, text):
    p = os.path.join(where, name)
    with open(p, "w") as fh:
        fh.write(text)
    os.chmod(p, 0o600)


put(TENV, "latark__app.env", f"SUPABASE_DB_URL='{URL_APP}'\nSUPABASE_ACCESS_TOKEN=sbp_tok_not_for_tests\n")
put(TENV, "latark__other.env", f"SUPABASE_DB_URL={URL_OTHER}\n")
put(O.env_dir(), "latark__app.env", "DEV_ONLY=1\n")   # dev-файл сервера: в нём строки базы нет

# --- выбор ключей: только свой файл и белый список -------------------------------------------------------------
k, f, skip = O.test_keys("latark/app")
check("test_keys: свой проект — своя строка из test-env", k == {"SUPABASE_DB_URL": URL_APP} and f == "latark__app.env",
      (sorted(k), f))
check("test_keys: имя не из белого списка (токен аккаунта) не передаётся, имя — в пропущенных",
      "SUPABASE_ACCESS_TOKEN" not in k and skip == ["SUPABASE_ACCESS_TOKEN"], skip)
check("test_keys: другой проект — только его строка", O.test_keys("latark/other")[0] == {"SUPABASE_DB_URL": URL_OTHER})
check("test_keys: проект без файла — пусто", O.test_keys("latark/none") == ({}, None, []))
check("test_keys: dev-файл сервера ключом тестов не служит", "DEV_ONLY" not in O.test_keys("latark/app")[0])
put(TENV, "latark__empty.env", "SUPABASE_DB_URL=\n")
check("test_keys: пустое значение не передаётся", O.test_keys("latark/empty")[0] == {})

# --- профиль и порты -------------------------------------------------------------------------------------------
_tenv_rule = f"(subpath {O._q(os.path.realpath(TENV))})"
check("профиль: папка ключей тестов закрыта для чтения всегда (и у сервера)",
      _tenv_rule in O.profile_text(()) and _tenv_rule in O.profile_text((), {5432}))
_pdb = O.profile_text((), {6543})
check("профиль с портом базы: вся сеть IP закрыта, открыты localhost и TCP на порт базы",
      '(deny network-outbound (remote ip "*:*"))' in _pdb and '(remote ip "localhost:*")' in _pdb
      and '(remote tcp "*:6543")' in _pdb, _pdb)
check("профиль с портом базы: порты браузеров и прокси закрыты после него (позднее сильнее)",
      _pdb.index('(remote tcp "*:6543")') < _pdb.index(f'(remote ip "*:{O.DENY_PORTS[0]}")'))
check("профиль без ключей тестов: сеть не сужена", '"*:*"' not in O.profile_text(()))
check("db_ports: порт из строки подключения", O.db_ports({"SUPABASE_DB_URL": URL_APP}) == {6543})
check("db_ports: без порта — 5432", O.db_ports({"SUPABASE_DB_URL": "postgres://u:pw@h/db"}) == {5432})
check("db_ports: несколько хостов", O.db_ports({"SUPABASE_DB_URL": "postgresql://u:p@a:5433,b:5434/db"}) == {5433, 5434})
check("db_ports: порт 0 и нечисло — 5432", O.db_ports({"SUPABASE_DB_URL": "postgresql://u:p@h:0/db"}) == {5432})
check("db_ports: строка ключ=значение", O.db_ports({"SUPABASE_DB_URL": "host=h port=6000 user=u"}) == {6000})

# --- вырезание значений ------------------------------------------------------------------------------------------
_K = {"SUPABASE_DB_URL": URL_APP}
_r = O.redact(f"a {URL_APP} b {PW} c S3cr%2Ft-pw-xyz d", _K)
check("redact: строка → <SUPABASE_DB_URL>, пароль как есть и раскодированный → ***",
      all(s not in _r for s in (URL_APP, PW, "S3cr%2Ft-pw-xyz")) and "<SUPABASE_DB_URL>" in _r and _r.count("***") == 2, _r)
check("redact: без ключей текст не меняется", O.redact("x " + PW, {}) == "x " + PW)

# --- прогон --script на APP: ключ, профиль, libpq, вырезание -----------------------------------------------------
LIBPQ = os.path.join(HOME, "fake-libpq", "bin")
os.makedirs(LIBPQ)
with open(os.path.join(LIBPQ, "pg_dump"), "w") as fh:
    fh.write("#!/bin/sh\necho pg_dump-fake\n")
os.chmod(os.path.join(LIBPQ, "pg_dump"), 0o755)
O.LIBPQ_BINS = (os.path.join(HOME, "no-libpq", "bin"), LIBPQ)
check("libpq_bins: только папки с исполняемым pg_dump", O.libpq_bins() == [LIBPQ], O.libpq_bins())

BODY = f'echo "url=$SUPABASE_DB_URL"; echo "pw={PW}"; echo "path=$PATH"; pg_dump'
pkg = dict(PKG, scripts=dict(PKG["scripts"], test=BODY))
commit(APP, {"package.json": json.dumps(pkg)}, "test script")


def last_call(before):
    got = calls()[before:]
    return got[-1] if got else {}


def leaks(text):
    return [s for s in SECRETS if s in (text or "")]


n0 = len(calls())
q, rid = new_request("athena-x", APP, "test", "--script", "test")
run_pass()
res = O.load_result(q, rid) or {}
c = last_call(n0)
env = c.get("env", {})
check("test --script на APP: прогон зелёный", res.get("state") == "done" and res.get("code") == 0, res)
check("test --script на APP: строка своего проекта в окружении", env.get("SUPABASE_DB_URL") == URL_APP, sorted(env))
check("test --script на APP: токен аккаунта и dev-ключи — нет",
      "SUPABASE_ACCESS_TOKEN" not in env and "DEV_ONLY" not in env, sorted(env))
check("test --script на APP: профиль profile-db.sb с портом базы",
      os.path.basename(c.get("profile", "")) == "profile-db.sb"
      and '(remote tcp "*:6543")' in open(c["profile"]).read(), c.get("profile"))
check("test --script на APP: pg_dump из libpq в PATH", LIBPQ in env.get("PATH", "").split(":"), env.get("PATH"))
_log = open(res["log"]).read() if res.get("log") else ""
check("test --script: прогон увидел строку (вывод команды есть)", "url=<SUPABASE_DB_URL>" in _log and "pg_dump-fake" in _log,
      _log[-400:])
check("test --script: журнал прогона без значений (строка и пароль вырезаны)", not leaks(_log) and "pw=***" in _log,
      leaks(_log))
check("test --script: журнал прогона — 600", (os.stat(res["log"]).st_mode & 0o777) == 0o600 if res.get("log") else False)
_resj = open(os.path.join(q, rid + ".json")).read() if os.path.exists(os.path.join(q, rid + ".json")) else json.dumps(res)
check("test --script: итог без значений, имена ключей — есть", not leaks(_resj) and res.get("keys") == ["SUPABASE_DB_URL"],
      (leaks(_resj), res.get("keys")))
check("test --script: имя токена из файла названо в пометке итога", "SUPABASE_ACCESS_TOKEN" in (res.get("note") or ""),
      res.get("note"))
_ev = json.dumps(events(rid))
check("test --script: outside.jsonl без значений, имена — есть", not leaks(_ev) and "SUPABASE_DB_URL" in _ev, _ev[-300:])
_rc, _st = say("athena-x", "status", rid)
check("status: без значений", not leaks(_st), leaks(_st))
check("test --script: записи tests для шлюза нет", not tests_for(git(APP, "rev-parse", "HEAD")))

# --- гашение по тишине: последняя строка вывода со строкой базы (argus #410 Б1) ------------------------------------
# сторож тишины пишет последнюю строку вывода в why итога и события test-silent; CPU дерева — 0 (гасим наверняка, не
# завися от libproc и ps в песочнице), IDLE_TIMEOUT — 2 с
_idle, _cpu = O.IDLE_TIMEOUT, O.tree_cpu
O.IDLE_TIMEOUT, O.tree_cpu = 2, (lambda pid: 0.0)
try:
    commit(APP, {"package.json": json.dumps(dict(PKG, scripts=dict(
        PKG["scripts"], test=f'echo "url=$SUPABASE_DB_URL pw={PW}"; exec sleep 31337')))}, "silent script")
    q, rid = new_request("athena-x", APP, "test", "--script", "test")
    run_pass()
finally:
    O.IDLE_TIMEOUT, O.tree_cpu = _idle, _cpu
    commit(APP, {"package.json": json.dumps(pkg)}, "test script back")
res = O.load_result(q, rid) or {}
_sil = events(rid, "test-silent")
check("тишина: прогон погашен сторожем, событие test-silent есть",
      res.get("state") == "failed" and "тишина" in (res.get("why") or "") and len(_sil) == 1, (res.get("why"), _sil))
check("тишина: в why события — последняя строка, строка базы вырезана в имя",
      bool(_sil) and "url=<SUPABASE_DB_URL> pw=***" in _sil[0].get("why", ""), _sil)
_ev = open(os.path.join(STATE, "logs", "outside.jsonl")).read()
check("тишина: outside.jsonl без значений", not leaks(_ev), leaks(_ev))
_resj = json.dumps(res) + (open(os.path.join(q, rid + ".json")).read() if os.path.exists(os.path.join(q, rid + ".json"))
                           else "")
check("тишина: итог (why, tail) без значений", not leaks(_resj), leaks(_resj))
check("тишина: журнал прогона без значений", not leaks(open(res["log"]).read() if res.get("log") else "x" + PW))
# событие stop прогона с ключами (снят «стопом» или superseded) — та же причина через clean_why
_w = O.TestWatch("20261109-000000-aaaaaa", q, "athena-x", APP)
_w.keys, _w.why = _K, f"причина {URL_APP} {PW}"
_w.log_stop(sha="abc", code=0)
_st_ev = events("20261109-000000-aaaaaa", "stop")
check("stop прогона с ключами: в outside.jsonl причина без значений, имя — есть",
      len(_st_ev) == 1 and not leaks(json.dumps(_st_ev)) and "<SUPABASE_DB_URL>" in _st_ev[0].get("why", ""), _st_ev)
_w.keys, _w.why = {}, "заявка «стоп»"
check("stop без ключей: причина как есть", _w.clean_why() == "заявка «стоп»")

# --- проверка проекта (без --script) на APP: ключа нет ---------------------------------------------------------
n0 = len(calls())
q, rid = new_request("athena-x", APP, "test")
run_pass()
c = last_call(n0)
check("проверка проекта на APP: строки базы в окружении нет", c and "SUPABASE_DB_URL" not in c.get("env", {}),
      sorted(c.get("env", {})))
check("проверка проекта на APP: обычный профиль, libpq не в PATH",
      os.path.basename(c.get("profile", "")) == "profile.sb" and LIBPQ not in c.get("env", {}).get("PATH", ""),
      (c.get("profile"), c.get("env", {}).get("PATH")))

# --- test --sha --script на APP (своя копия на коммите): ключ тот же, установка зависимостей — без него ----------
n0 = len(calls())
q, rid = new_request("athena-x", APP, "test", "--script", "test", "--sha", git(APP, "rev-parse", "HEAD"))
run_pass()
res = O.load_result(q, rid) or {}
got = calls()[n0:]
run_c = [x for x in got if x["cmd"][-2:] == ["run", "test"]]
inst_c = [x for x in got if x["cmd"][1:2] in (["ci"], ["install"])]
check("test --sha --script: прогон получил строку своего проекта",
      res.get("state") == "done" and res.get("code") == 0 and run_c and run_c[-1]["env"].get("SUPABASE_DB_URL") == URL_APP, (res.get("state"), res.get("why")))
check("test --sha --script: установка зависимостей — без строки и с обычным профилем",
      all("SUPABASE_DB_URL" not in x["env"] and x["profile"].endswith("profile.sb") for x in inst_c), len(inst_c))

# --- другой проект: только свой ключ ---------------------------------------------------------------------------
commit(OTHER, {"package.json": json.dumps({"name": "other", "scripts": {"test": 'echo "o=$SUPABASE_DB_URL"'}})}, "o2")
n0 = len(calls())
q, rid = new_request("metis-y", OTHER, "test", "--script", "test")
run_pass()
c = last_call(n0)
check("test --script на OTHER: строка OTHER, не APP", c.get("env", {}).get("SUPABASE_DB_URL") == URL_OTHER,
      (O.load_result(q, rid) or {}).get("why"))
os.unlink(os.path.join(TENV, "latark__other.env"))
n0 = len(calls())
q, rid = new_request("metis-y", OTHER, "test", "--script", "test")
run_pass()
c = last_call(n0)
check("test --script на OTHER без своего файла: ключа нет (чужой не берётся)",
      c and "SUPABASE_DB_URL" not in c.get("env", {}) and c["profile"].endswith("profile.sb"), sorted(c.get("env", {})))

# --- сервер APP: только dev-ключи ------------------------------------------------------------------------------
_real_pick = O.pick_port
O.pick_port = lambda taken: O.SERVER_PORTS.start + 7   # окно роли: bind закрыт, а окружение пишется до bind
try:
    n0 = len(calls())
    rc, q, rid = role_request("athena-x", APP, "serve", "--minutes", "1")
    serve_pass()
    dev = [x for x in calls()[n0:] if x["cmd"][-2:] == ["run", "dev"]]
    check("сервер APP: dev-ключ есть, строки базы нет",
          dev and dev[-1]["env"].get("DEV_ONLY") == "1" and "SUPABASE_DB_URL" not in dev[-1]["env"],
          (O.load_result(q, rid) or {}).get("why"))
    check("сервер APP: обычный профиль, libpq не в PATH",
          dev and dev[-1]["profile"].endswith("profile.sb") and LIBPQ not in dev[-1]["env"]["PATH"])
finally:
    O.pick_port = _real_pick
    kill_all_servers()

# --- срез процессов: строка из командной строки вырезана -------------------------------------------------------
_kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "--dbname", URL_APP])
TEST_PROCS.append(_kid)
try:
    _rows = wait_for(lambda: O.procs_of(_kid.pid, _K), 5)
    if _rows:
        _cmds = " ".join(r["cmd"] for r in _rows)
        check("procs_of: строка подключения в команде → <SUPABASE_DB_URL>",
              not leaks(_cmds) and "<SUPABASE_DB_URL>" in _cmds, _cmds)
    else:
        print("пропущено: ps здесь не запускается — срез процессов не проверен")
finally:
    _kid.kill()
    _kid.wait()

# --- pantheon outside key: скрытый ввод, отказы, права -----------------------------------------------------------
class _Tty:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


_real_stdin, _real_gp = O.sys.stdin, O.getpass.getpass
_answer = ["postgresql://u:p#a$s'q@h:5432/db"]
_prompts = []


def _gp(prompt):
    _prompts.append(prompt)
    v = _answer[0]
    if isinstance(v, BaseException):
        raise v
    return v


def key(*args, tty=True):
    O.sys.stdin = _Tty(tty)
    O.getpass.getpass = _gp
    out, errb = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errb):
            rc = O.main(["key", *args])
    finally:
        O.sys.stdin, O.getpass.getpass = _real_stdin, _real_gp
    return rc, out.getvalue() + errb.getvalue()


KF = os.path.join(TENV, "latark__keytest.env")
put(TENV, "latark__keytest.env", "# владельца\nSUPABASE_DB_URL=old\nOTHER=1\n")
os.environ["CLAUDECODE"] = "1"
try:
    rc, out = key("latark/keytest", "SUPABASE_DB_URL")
finally:
    os.environ.pop("CLAUDECODE")
check("key: из окна Claude Code — отказ, код 1, файл не тронут", rc == 1 and "old" in open(KF).read() and not _prompts,
      (rc, out))
rc, out = key("latark/keytest", "SUPABASE_DB_URL", tty=False)
check("key: без терминала — отказ, код 1", rc == 1 and not _prompts and "old" in open(KF).read(), (rc, out))
rc, out = key("latark/keytest", "SUPABASE_ACCESS_TOKEN")
check("key: имя не из белого списка — код 2", rc == 2 and not _prompts, (rc, out))
rc, out = key("../etc", "SUPABASE_DB_URL")
check("key: не OWNER/REPO — код 2", rc == 2 and not _prompts, (rc, out))
rc, out = key("latark/keytest")
check("key: без имени — код 2", rc == 2, (rc, out))
_answer[0] = "not-a-url"
rc, out = key("latark/keytest", "SUPABASE_DB_URL")
check("key: не строка postgres — код 1, файл не тронут, значения в выводе нет",
      rc == 1 and "old" in open(KF).read() and "not-a-url" not in out, (rc, out))
_answer[0] = EOFError()
rc, out = key("latark/keytest", "SUPABASE_DB_URL")
check("key: ввод прерван — код 1", rc == 1 and "old" in open(KF).read(), (rc, out))
V = "postgresql://u:p#a$s'q@h:5432/db"
_answer[0] = V
rc, out = key("Latark/KeyTest", "SUPABASE_DB_URL")
_txt = open(KF).read()
check("key: записан — код 0, значение в выводе и подсказке не показано", rc == 0 and V not in out
      and all(V not in p for p in _prompts), (rc, out))
check("key: свои строки файла сохранены, старое значение заменено", "OTHER=1" in _txt and "old" not in _txt
      and "# владельца" in _txt, _txt)
check("key: значение читается обратно как есть (кавычки, # и $)", O.test_keys("latark/keytest")[0] == {"SUPABASE_DB_URL": V},
      O.test_keys("latark/keytest")[0] == {})
check("key: файл 600, папка 700", (os.stat(KF).st_mode & 0o777) == 0o600 and (os.stat(TENV).st_mode & 0o777) == 0o700,
      (oct(os.stat(KF).st_mode), oct(os.stat(TENV).st_mode)))
check("key: временных файлов не осталось", sorted(os.listdir(TENV)) == sorted(
    ["latark__app.env", "latark__empty.env", "latark__keytest.env"]), os.listdir(TENV))
_answer[0] = ""
rc, out = key("latark/keytest", "SUPABASE_DB_URL")
check("key: пустой ввод убирает ключ, остальное цело", rc == 0 and "SUPABASE_DB_URL" not in open(KF).read()
      and "OTHER=1" in open(KF).read(), (rc, open(KF).read()))
_pth = os.path.join(HOME, "pantheon-test-env-link")
os.rename(TENV, _pth)
os.symlink(_pth, TENV)
_answer[0] = V
try:
    rc, out = key("latark/keytest", "SUPABASE_DB_URL")
    check("key: папка ключей — ссылка, отказ, код 1", rc == 1, (rc, out))
finally:
    os.unlink(TENV)
    os.rename(_pth, TENV)

# --- синтаксис профиля настоящим sandbox-exec (65 — ошибка разбора; 71 — профиль цел, но песочница во вложенной) ---
_prof = O.write_profile((), {5432})
_sx = "/usr/bin/sandbox-exec"
if MAC and os.path.exists(_sx):
    r = subprocess.run([_sx, "-f", _prof, "/usr/bin/true"], capture_output=True, text=True)
    check_mac("профиль с портом базы разбирается sandbox-exec", r.returncode == 0
              or (r.returncode == 71 and "sandbox_apply" in r.stderr), (r.returncode, r.stderr[-200:]))
    if r.returncode == 0:   # не вложенная песочница: проверить и действие правил на TEST-NET (192.0.2.1 не отвечает)
        probe = ("import socket, sys\nout = []\nfor p in (443, 5432):\n    s = socket.socket(); s.settimeout(1)\n"
                 "    try:\n        s.connect(('192.0.2.1', p)); out.append('ok')\n"
                 "    except PermissionError:\n        out.append('deny')\n"
                 "    except OSError:\n        out.append('net')\nprint(' '.join(out))\n")
        r = subprocess.run([_sx, "-f", _prof, sys.executable, "-I", "-c", probe], capture_output=True, text=True,
                           timeout=30)
        check_mac("профиль с портом базы: TCP 443 закрыт песочницей, 5432 — нет", r.stdout.split() == ["deny", "net"]
                  or r.stdout.split() == ["deny", "ok"], (r.stdout, r.stderr[-200:]))
else:
    print("пропущено: нужен macOS — синтаксис профиля sandbox-exec")

print(f"{TOTAL[0] - len(FAILS) - len(SKIPPED_BIND)} из {TOTAL[0]} прошли"
      + (f", пропущено при закрытом bind: {len(SKIPPED_BIND)}" if SKIPPED_BIND else ""))
sys.exit(1 if FAILS else 0)
