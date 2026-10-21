#!/usr/bin/env python3
"""pantheon usage в песочнице окна роли (metis-0354): PANTHEON и состояние недоступны для записи — отчёт печатается
целиком в stdout, в stderr строка «отчёт не сохранён: …», код 0. Запись доступна — поведение прежнее (путь файла).

usage.py подменён заглушкой в временной копии PLUGIN. pantheon.py идёт в этом же процессе (3.11+; на 3.9 — перезапуск).
Запуск: python3 -I plugins/pantheon/tests/test_usage_ro.py  (код выхода 0 — все прошли)
"""
import atexit
import contextlib
import importlib.util
import io
import os
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402
if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)])

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="usage-ro-"))


def _cleanup():
    for dp, dns, _ in os.walk(ROOT):
        for d in dns:
            try:
                os.chmod(os.path.join(dp, d), 0o755)
            except OSError:
                pass
    shutil.rmtree(ROOT, True)


atexit.register(_cleanup)
HOME_, PAN, STATE = (os.path.join(ROOT, n) for n in ("home", "pantheon", "state"))
for d in (HOME_, PAN, STATE):
    os.makedirs(d)
os.environ.update({"HOME": HOME_, "PANTHEON_HOME": PAN, "PANTHEON_STATE": STATE, "PANTHEON_NO_NOTIFY": "1"})
os.environ.pop("PANTHEON_DRYRUN", None)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
spec = importlib.util.spec_from_file_location("pantheon_usage_ro", os.path.join(LIB, "pantheon.py"))
P = importlib.util.module_from_spec(spec)
sys.modules["pantheon_usage_ro"] = P
spec.loader.exec_module(P)

FAKE = os.path.join(ROOT, "plugin")
os.makedirs(os.path.join(FAKE, "scripts"))
REPORT = "Расход за 7 дн.\nroleA 1.00\nИтого 12.34 $\n"
with open(os.path.join(FAKE, "scripts", "usage.py"), "w") as fh:
    fh.write(f"import sys\nsys.stdout.write({REPORT!r})\n")
P.PLUGIN = FAKE

results = []


def check(name, ok, got=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or got is None else f" — получено {got!r}"))


def run():
    o, e = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
            code = P.usage_report([])
    except Exception as ex:  # без правки команда падает исключением
        code = f"исключение {type(ex).__name__}: {ex}"
    return code, o.getvalue(), e.getvalue()


# 1. запись доступна: прежнее поведение — файл, строка тревоги, в stdout путь
code, out, err = run()
f = os.path.join(PAN, "metrics", "usage", P.stamp()[:10] + ".txt")
check("запись доступна: код 0, в stdout путь файла", code == 0 and out.strip() == f, (code, out))
check("запись доступна: файл с отчётом", os.path.exists(f) and open(f).read() == REPORT)
check("запись доступна: строка в alerts.md",
      "отчёт расхода за 7 дн.: Итого 12.34 $" in open(os.path.join(PAN, "alerts.md")).read())
check("запись доступна: stderr без «не сохранён»", "не сохранён" not in err, err)

# 2. PANTHEON и STATE закрыты на запись (как в песочнице окна роли)
shutil.rmtree(os.path.join(PAN, "metrics"))
os.remove(os.path.join(PAN, "alerts.md"))
for d in (PAN, STATE):
    os.chmod(d, stat.S_IRUSR | stat.S_IXUSR)
if os.access(PAN, os.W_OK):
    print("пропуск: запись в read-only папку не закрывается (root?)")
else:
    code, out, err = run()
    check("read-only: код 0", code == 0, code)
    check("read-only: отчёт целиком в stdout", out == REPORT, out)
    check("read-only: строка «отчёт не сохранён: …» в stderr", "отчёт не сохранён: " in err, err)
    check("read-only: ничего не создано", not os.path.exists(os.path.join(PAN, "metrics")))
for d in (PAN, STATE):
    os.chmod(d, 0o755)

print(f"{sum(results)}/{len(results)}")
sys.exit(0 if results and all(results) else 1)
