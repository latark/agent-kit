#!/usr/bin/env python3
"""pantheon usage в песочнице окна роли (metis-0354): PANTHEON и состояние недоступны для записи — отчёт печатается
целиком в stdout, в stderr «отчёт не сохранён: …», код 1 (плановый проход поднимет тревогу). Закрыт только alerts.md —
файл сохранён, путь в stdout, в stderr «тревога не записана», код 1. Запись доступна — поведение прежнее (путь файла).

usage.py подменён заглушкой в временной копии PLUGIN. pantheon.py идёт в этом же процессе.
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
from _py311 import PY311  # noqa: E402,F401  — Python 3.11+ и PANTHEON_TEST=1

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
    check("read-only: код 1", code == 1, code)
    check("read-only: отчёт целиком в stdout", out == REPORT, out)
    check("read-only: строка «отчёт не сохранён: …» в stderr", "отчёт не сохранён: " in err, err)
    check("read-only: ничего не создано", not os.path.exists(os.path.join(PAN, "metrics")))
for d in (PAN, STATE):
    os.chmod(d, 0o755)

# 3. закрыт только alerts.md (окно штаба): файл сохранён, путь в stdout, «не сохранён» нет, код 1
shutil.rmtree(os.path.join(PAN, "metrics"), True)
AL = os.path.join(PAN, "alerts.md")
if os.path.lexists(AL):
    os.remove(AL)
os.mkdir(AL)  # alert() не может писать в папку — как отказ на alerts.md
code, out, err = run()
check("только alerts: код 1", code == 1, code)
check("только alerts: файл сохранён, путь в stdout", out.strip() == f and open(f).read() == REPORT, out)
check("только alerts: «тревога не записана» в stderr, «не сохранён» нет",
      "тревога не записана: " in err and "не сохранён" not in err, err)
os.rmdir(AL)

# 4. закрыто всё ещё раз: код 1 и отчёт в stdout (плановый проход по коду видит сбой)
shutil.rmtree(os.path.join(PAN, "metrics"), True)
for d in (PAN, STATE):
    os.chmod(d, stat.S_IRUSR | stat.S_IXUSR)
if not os.access(PAN, os.W_OK):
    code, out, err = run()
    check("всё закрыто: код 1, отчёт в stdout", code == 1 and out == REPORT, (code, out))
for d in (PAN, STATE):
    os.chmod(d, 0o755)

# 5. metrics закрыт (путь занят файлом), alerts.md открыт — плановый проход usage-weekly: код 1 из ветки файла,
# в alerts.md нет строки с путём к несуществующему файлу
shutil.rmtree(os.path.join(PAN, "metrics"), True)
if os.path.lexists(AL):
    os.remove(AL)
with open(os.path.join(PAN, "metrics"), "w") as fh:
    fh.write("занято")
code, out, err = run()
check("metrics закрыт, alerts открыт: код 1, отчёт в stdout", code == 1 and out == REPORT, (code, out))
al_text = open(AL).read() if os.path.exists(AL) else ""
check("metrics закрыт, alerts открыт: в alerts.md нет строки с путём", "отчёт расхода" not in al_text and "metrics" not in al_text, al_text)

# 6. вывод через трубу (stdout и stderr в одну, как в run_job): причина — последняя строка, не теряется за отчётом
import subprocess  # noqa: E402
DRV = os.path.join(ROOT, "drv.py")
with open(DRV, "w") as fh:
    fh.write("import importlib.util, sys\n"
             f"s = importlib.util.spec_from_file_location('pp', {os.path.join(LIB, 'pantheon.py')!r})\n"
             "P = importlib.util.module_from_spec(s); sys.modules['pp'] = P; s.loader.exec_module(P)\n"
             f"P.PLUGIN = {FAKE!r}\n"
             "sys.exit(P.usage_report([]))\n")
pr = subprocess.run([sys.executable, "-I", DRV], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ)
lines = pr.stdout.strip().splitlines()
check("труба: код 1", pr.returncode == 1, pr.returncode)
check("труба: последняя строка — «отчёт не сохранён: …», отчёт целиком перед ней",
      bool(lines) and lines[-1].startswith("отчёт не сохранён: ") and pr.stdout.startswith(REPORT), pr.stdout)
os.remove(os.path.join(PAN, "metrics"))

print(f"{sum(results)}/{len(results)}")
sys.exit(0 if results and all(results) else 1)
