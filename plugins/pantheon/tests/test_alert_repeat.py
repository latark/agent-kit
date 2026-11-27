#!/usr/bin/env python3
"""metis-1381, 1382, 1384, 1385, 1386: повторяющиеся тревоги — до одной в сутки или ни одной.

Запуск: python3 -I plugins/pantheon/tests/test_alert_repeat.py  (код выхода 0 — все прошли)
- 1381/1386: разовый сетевой сбой (EOF, TLS handshake, SSL_ERROR_SYSCALL) — тревога только на 3-м проходе подряд, дальше
  свёртка раз в сутки; удача сбрасывает счёт; лёгкий тик по кэшу (count=False) счёт не растит; не сетевая ошибка —
  тревога сразу, как прежде; gh_json повторяет сетевой сбой один раз, прочие — нет;
- 1382: файл inbox, что выпал из набора и вернулся, тревогу заново не даёт (свёртка по файлу, 14 суток);
- 1384: срок задачи check не ниже TIMEOUT_FLOOR, как бы ни стоял timeout в schedule.toml;
- 1385: тревога о длинных CLAUDE.md не повторяется при каждом изменении числа строк.
Мутанты внутри теста (подмена исходника в копии lib/): без счётчика серии, без свёртки inbox, без пола срока, без
свёртки инструкций, без повтора gh, сброс серии при count=False (metis-1402, 1406), 403 как сетевой сбой (metis-1407)
— набор краснеет.
"""
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402,F401  — Python 3.11+ и PANTHEON_TEST=1

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="alert-repeat-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
T0 = 1_792_800_000
DAY = 86400
results = []
EOF_ERR = 'Post "https://api.github.com/graphql": unexpected EOF'
TLS_ERR = "fatal: unable to access 'https://github.com/x/y/': SSL_ERROR_SYSCALL, errno 54"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:800]}]"))


def env(tag):
    d = os.path.join(ROOT, tag)
    for k, sub in (("HOME", "home"), ("PANTHEON_HOME", "pantheon"), ("PANTHEON_STATE", "state")):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
        os.environ[k] = os.path.join(d, sub)
    os.environ.pop("PANTHEON_DRYRUN", None)
    return d


def lines(P, part):
    try:
        text = open(os.path.join(P.PANTHEON, "alerts.md"), encoding="utf-8").read()
    except OSError:
        return []
    return [ln for ln in text.splitlines() if part in ln]


def at(t):
    os.environ["PANTHEON_NOW"] = str(t)


def streak_cases(P, out):
    at(T0)
    for i in range(2):
        at(T0 + 60 * i)
        P.alert_streak("k", True, "fetch: " + TLS_ERR, "release-tick")
    out("серия: два сбоя подряд — тревоги нет", not lines(P, "fetch:"), lines(P, "fetch:"))
    at(T0 + 200)
    P.alert_streak("k", False, "", "release-tick")
    for i in range(2):
        P.alert_streak("k", True, "fetch: " + TLS_ERR, "release-tick")
    out("серия: удача между сбоями сбрасывает счёт", not lines(P, "fetch:"), lines(P, "fetch:"))
    P.alert_streak("k", True, "fetch: " + TLS_ERR, "release-tick", count=False)
    out("серия: count=False (тик по кэшу) счёт не растит", not lines(P, "fetch:"), lines(P, "fetch:"))
    P.alert_streak("k", False, "", "release-tick", count=False)  # metis-1402, 1406: тик по кэшу без своих ошибок
    P.alert_streak("k", True, "fetch: " + TLS_ERR, "release-tick")
    out("серия: третий сбой подряд — одна строка (удача count=False серию не сбросила, metis-1402)",
        len(lines(P, "fetch:")) == 1, lines(P, "fetch:"))
    for i in range(5):
        at(T0 + 300 + 60 * i)
        P.alert_streak("k", True, "fetch: " + TLS_ERR, "release-tick")
    out("серия: сбой держится — в течение суток без новых строк", len(lines(P, "fetch:")) == 1, lines(P, "fetch:"))
    at(T0 + DAY + 600)
    P.alert_streak("k", True, "fetch: " + TLS_ERR, "release-tick")
    got = lines(P, "fetch:")
    out("серия: через сутки — строка со счётчиком повторов", len(got) == 2 and "повторов ×" in got[1], got)
    out("net_error: EOF, TLS, SSL_ERROR — да; ошибка данных — нет",
        all(P.net_error(x) for x in (EOF_ERR, TLS_ERR, "net/http: TLS handshake timeout"))
        and not P.net_error("Could not resolve to a Repository with the name x")
        and not P.net_error("gh вернул не JSON"), None)
    auth = ("fatal: unable to access 'https://github.com/x/y/': The requested URL returned error: 403",
            "gh: HTTP 403: Resource not accessible by integration (https://api.github.com/graphql)",
            "fatal: Authentication failed for 'https://github.com/x/y/'")
    out("net_error: отказ авторизации 403/401 — не сетевой, даже с «unable to access» (metis-1407)",
        not any(P.net_error(x) for x in auth), [x for x in auth if P.net_error(x)])
    P.alert_net("auth", "fetch: " + auth[0], "выпуск без Actions: 403", "pantheon-tick")
    out("alert_net: 403 — тревога с первого прохода, а не с третьего (metis-1407)",
        len(lines(P, "выпуск без Actions: 403")) == 1, lines(P, "403"))


def autoclose_cases(P, out):
    at(T0)
    for i in range(2):
        P.autoclose_alerts(["latark/x"], {"latark/x": "gh pr list: " + EOF_ERR})
    P.autoclose_alerts(["latark/x"], {})
    P.autoclose_alerts(["latark/x"], {"latark/x": "gh pr list: " + EOF_ERR})
    out("автозакрытие: разовые EOF, между ними успех — тревоги нет", not lines(P, "автозакрытие задач"),
        lines(P, "автозакрытие задач"))
    P.autoclose_alerts(["latark/x"], {})
    for i in range(3):
        P.autoclose_alerts(["latark/x"], {"latark/x": "gh pr list: " + EOF_ERR}, count=(i != 1))
    P.autoclose_alerts(["latark/x"], {}, count=False)  # metis-1402: лёгкий тик без ошибок серию fetch не сбрасывает
    out("автозакрытие: тик по кэшу (count=False) серию не растит — на 3 вызова 2 счёта, тревоги нет",
        not lines(P, "автозакрытие задач"), lines(P, "автозакрытие задач"))
    P.autoclose_alerts(["latark/x"], {"latark/x": "gh pr list: " + EOF_ERR})
    out("автозакрытие: сбой подряд на 3-м счёте — одна строка, лёгкий тик без ошибок между ними не сбросил",
        len(lines(P, "автозакрытие задач")) == 1,
        lines(P, "автозакрытие задач"))
    P.autoclose_alerts(["latark/y"], {"latark/y#5": "закрытие задачи: нет такого поля"})
    out("автозакрытие: ошибка не сетевая — тревога сразу", len(lines(P, "нет такого поля")) == 1,
        lines(P, "автозакрытие задач"))
    P.alert_net("rt", "fetch origin main: " + TLS_ERR, "выпуск без Actions: " + TLS_ERR, "pantheon-tick")
    P.alert_net("rt", "fetch origin main: " + TLS_ERR, "выпуск без Actions: " + TLS_ERR, "pantheon-tick")
    out("alert_net: два обрыва fetch — тревоги нет", not lines(P, "выпуск без Actions"), lines(P, "выпуск"))
    P.alert_net("rt", "fetch origin main: " + TLS_ERR, "выпуск без Actions: " + TLS_ERR, "pantheon-tick")
    out("alert_net: третий — одна строка", len(lines(P, "выпуск без Actions")) == 1, lines(P, "выпуск"))
    P.alert_net("rt2", "release.py код 1", "выпуск без Actions: код 1", "pantheon-tick")
    out("alert_net: не сетевой сбой — сразу", len(lines(P, "код 1")) == 1, lines(P, "код 1"))
    # автозакрытие выключено (кэш старше часа): повтор — одна строка в сутки
    A = P.autoclose_mod()
    P.autoclose_repo_dirs = lambda: {"latark/x": "/nonexistent"}
    A.run = lambda *a, **k: ([], {})
    reasons = ["автозакрытие выключено: кэш старше часа (задача не идёт)", None] * 3
    for i, r in enumerate(reasons):  # кэш то старше часа, то свежий: alert_once снимался на каждой удаче и писал заново
        P.autoclose_off_reason = lambda t, d=None, r=r: r
        P.autoclose_tick(T0 + 600 * i)
    out("autoclose-off: кэш старше часа три раза с удачами между — одна строка", len(lines(P, "кэш старше часа")) == 1,
        lines(P, "кэш старше часа"))


def tail_cases(P, out):
    at(T0)
    P.tail_alert(None, [])  # первый проход: запоминает набор
    at(T0 + 60)
    P.tail_alert(None, [("отчёт", "inbox/research-a.md", "inbox/research-a.md")])
    out("inbox: новый файл — одна тревога", len(lines(P, "research-a.md")) == 1, lines(P, "research-a.md"))
    at(T0 + 3 * DAY)
    P.tail_alert(None, [])  # файл выпал из набора (раздел разобран, потом вернулся)
    at(T0 + 4 * DAY)
    P.tail_alert(None, [("отчёт", "inbox/research-a.md", "inbox/research-a.md")])
    out("inbox: тот же файл вернулся через сутки — без новой строки", len(lines(P, "research-a.md")) == 1,
        lines(P, "research-a.md"))
    at(T0 + 5 * DAY)
    P.tail_alert(None, [("отчёт", "inbox/research-a.md", "inbox/research-a.md"),
                        ("отчёт", "inbox/research-b.md", "inbox/research-b.md")])
    out("inbox: другой файл — своя строка", len(lines(P, "research-b.md")) == 1, lines(P, "research-b.md"))


def instr_cases(P, out):
    at(T0)
    folder = os.path.join(ROOT, "proj")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(P.PANTHEON, "directions.toml"), "w", encoding="utf-8") as fh:
        fh.write(f'[[direction]]\nname = "x"\nfolders = ["{folder}"]\n')
    for n in (260, 265, 270):
        with open(os.path.join(folder, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write("строка\n" * n)
        at(T0 + 60 * n)
        P.instructions_check(quiet=True)
    out("инструкции: длина CLAUDE.md растёт 260 → 270 строк — одна тревога в сутки", len(lines(P, "инструкции длиннее")) == 1,
        lines(P, "инструкции длиннее"))


def gh_cases(out, lib):
    spec = importlib.util.spec_from_file_location("autoclose_repeat", os.path.join(lib, "autoclose.py"))
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    stub = os.path.join(ROOT, "gh-stub")
    count = os.path.join(ROOT, "gh-count")
    for body, name in ((f"{EOF_ERR}", "net"), ("HTTP 404: Not Found", "plain")):
        open(count, "w").close()
        with open(stub, "w") as fh:
            fh.write(f"#!/bin/sh\necho x >> {count}\necho '{body}' >&2\nexit 1\n")
        os.chmod(stub, 0o755)
        data, err = A.gh_json(["pr", "list"], env={"PANTHEON_GH": stub, "PATH": os.environ.get("PATH", "")})
        n = len(open(count).read().split())
        out(f"gh_json: {'сетевой сбой — один повтор' if name == 'net' else 'прочая ошибка — без повтора'}",
            data is None and err and n == (2 if name == "net" else 1), (n, err))


def jobs_cases(out, lib):
    src = open(os.path.join(lib, "jobs.py"), encoding="utf-8").read()
    ns = {}
    floor = src[src.index("TIMEOUT_FLOOR = "):].split("\n", 1)[0]
    exec(floor, ns)  # noqa: S102 — одна строка присваивания из своего исходника
    out("check: пол срока не меньше 120 с (60 с обрывало проход под нагрузкой)", ns["TIMEOUT_FLOOR"].get("check", 0) >= 120,
        floor)
    out("run_job берёт срок с полом", 'max(float(job.get("timeout", 600)), TIMEOUT_FLOOR.get(name, 0))' in src)


def run(lib, tag):
    """Случаи на lib/ (настоящей или копии с мутантом) → [(имя, ок, подробность)]."""
    env(tag)
    sys.path.insert(0, lib)
    P = importlib.import_module("pantheon")
    got = []

    def out(name, ok, detail=""):
        got.append((name, ok, detail))
    streak_cases(P, out)
    autoclose_cases(P, out)
    tail_cases(P, out)
    instr_cases(P, out)
    gh_cases(out, lib)
    jobs_cases(out, lib)
    return got


MUTANTS = {
    "без счётчика серии": ("pantheon.py", "return c >= n and alert_fold(", "return alert_fold("),
    "без свёртки inbox": ("pantheon.py", 'alert_fold("tail-" + k, f"{TAIL_TEXT[kind]}: {w}{tail}", "check", window=TAIL_FOLD_WINDOW)',
                          'alert(f"{TAIL_TEXT[kind]}: {w}{tail}", "check")'),
    "без свёртки autoclose-off": ("pantheon.py", 'alert_fold("autoclose-off", off, "pantheon-tick")',
                                  # прежний код целиком: alert_once снимался на каждой удаче (clear_once в else)
                                  'alert_once("autoclose-off", off, off, "pantheon-tick")\n    else:\n'
                                  '        clear_once("autoclose-off")'),
    "без свёртки инструкций": ("instructions.py", 'P.alert_fold("instr-long", ', 'P.alert_once("instr-long", ",".join(sorted(long_)), '),
    "без пола срока": ("jobs.py", 'TIMEOUT_FLOOR = {"check": 180}', "TIMEOUT_FLOOR = {}"),
    "без повтора gh": ("autoclose.py", "for attempt in (0, 1):", "for attempt in (1,):"),
    "net_error всегда нет": ("pantheon.py", "return bool(NET_ERR_RE.search(str(text)))", "return False"),
    "count=False сбрасывает серию": ("pantheon.py", "if c and count:", "if c:"),  # metis-1402, 1406
    "403 — сетевой сбой": ("pantheon.py", " and not AUTH_ERR_RE.search(str(text))", ""),  # metis-1407
}


def mutant(name):
    """Копия lib/ с подменой исходника; прогон случаев в отдельном процессе → код выхода (не 0 — мутант убит)."""
    fname, old, new = MUTANTS[name]
    lib = os.path.join(ROOT, "lib-" + str(sorted(MUTANTS).index(name)))
    shutil.copytree(LIB, lib, ignore=shutil.ignore_patterns("__pycache__"))
    src = open(os.path.join(lib, fname), encoding="utf-8").read()
    if old not in src:
        return None
    open(os.path.join(lib, fname), "w", encoding="utf-8").write(src.replace(old, new))
    r = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--lib", lib], capture_output=True,
                       text=True, timeout=300)
    return r.returncode


def main():
    if sys.argv[1:2] == ["--lib"]:
        got = run(sys.argv[2], "mut")
        for name, ok, _ in got:
            print(("ok   " if ok else "FAIL ") + name)
        return 0 if all(ok for _, ok, _ in got) else 1
    try:
        for name, ok, detail in run(LIB, "real"):
            check(name, ok, detail)
        for name in MUTANTS:
            rc = mutant(name)
            check(f"мутант «{name}» убит (случаи краснеют)", rc not in (None, 0), f"код {rc}; None — подмена не нашлась")
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} ok")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
