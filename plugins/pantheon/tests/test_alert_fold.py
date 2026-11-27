#!/usr/bin/env python3
"""metis-1025: повторяющаяся тревога одной причины — одна строка в сутки со счётчиком (P.alert_fold).

Запуск: python3 -I plugins/pantheon/tests/test_alert_fold.py  (код выхода 0 — все прошли)
- первая тревога ключа пишется; повторы в течение окна (сутки) — без строки, даже с другими числами в тексте;
- после окна — новая строка с «повторов ×N с <время первой>»; без повторов — без счётчика;
- другой ключ не сливается; время из прошлого (часы назад) окно не продлевает; битая метка — строка пишется;
- плановый проход: уборка кэшей песочниц, где ничего не убрано и те же записи не удаляются каждые 5 мин (690 строк
  за 3 дня в alerts.md до правки), — одна строка; убрано что-то — строка каждый раз, как прежде.
Мутанты внутри теста (подмена исходника): без проверки окна, без счётчика, уборка через P.alert — набор краснеет.
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

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="alert-fold-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
T0 = 1_792_800_000
DAY = 86400
results = []


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


def fold_cases(P, out):
    """Свёртка alert_fold. out(имя, условие, подробность)."""
    at(T0)
    out("первая тревога ключа пишется", P.alert_fold("k", "уборка: не удалось 57", "watch") is True
        and len(lines(P, "уборка: не удалось")) == 1, lines(P, "уборка"))
    for i, dt in enumerate((300, 600, 3600, DAY - 60)):
        at(T0 + dt)
        P.alert_fold("k", f"уборка: не удалось {58 + i}", "watch")
    out("повторы за сутки (числа другие) — без новой строки", len(lines(P, "уборка: не удалось")) == 1,
        lines(P, "уборка"))
    at(T0 + DAY + 1)
    P.alert_fold("k", "уборка: не удалось 61", "watch")
    got = lines(P, "уборка: не удалось")
    out("после суток — вторая строка со счётчиком повторов", len(got) == 2 and "повторов ×4 с " + P.stamp(T0) in got[1]
        and got[1].startswith(P.stamp(T0 + DAY + 1) + " · watch · уборка: не удалось 61"), got)
    at(T0 + 2 * DAY + 10)
    P.alert_fold("k", "уборка: не удалось 62", "watch")
    got = lines(P, "уборка: не удалось")
    out("сутки без повторов — строка без счётчика", len(got) == 3 and "повторов" not in got[2], got)
    P.alert_fold("other", "уборка: не удалось 62", "watch")
    out("другой ключ — своя строка", len(lines(P, "уборка: не удалось")) == 4, lines(P, "уборка"))
    at(T0 + 10)  # часы ушли назад: метка «из будущего» окно не продлевает
    out("время из прошлого — строка пишется", P.alert_fold("k", "уборка: часы назад", "watch") is True
        and len(lines(P, "часы назад")) == 1)
    with open(P.once_path("fold-bad"), "w") as fh:
        fh.write("не json")
    out("битая метка — строка пишется", P.alert_fold("bad", "битая метка", "watch") is True
        and len(lines(P, "битая метка")) == 1)


def sweep_cases(P, w, out):
    """Уборка кэшей песочниц плановым проходом (watch.sandbox_sweep)."""
    w.set_core(P)
    root = os.path.join(P.HOME, "Library", "Caches", "pantheon-sandbox")
    os.makedirs(root, exist_ok=True)
    w.sandbox_root = lambda: root
    w._open_paths = lambda: set()
    w.sandbox_mb = lambda r, force=False: 1
    res = [(0, 57)]
    w.sandbox_clean = lambda *a, **k: res[0]
    for i in range(12):  # час проходов по 5 мин
        at(T0 + 300 * i)
        w.sandbox_sweep(T0 + 300 * i)
    out("уборка: те же 57 неудаляемых за час — одна строка", len(lines(P, "кэши песочниц: убрано")) == 1,
        lines(P, "кэши песочниц"))
    res[0] = (3, 57)
    for i in range(2):
        at(T0 + 4000 + i)
        w.sandbox_sweep(T0 + 4000 + i)
    out("уборка: что-то убрано — строка каждый раз", len(lines(P, "кэши песочниц: убрано записей 3")) == 2,
        lines(P, "кэши песочниц"))


def run(lib, tag):
    """Случаи на lib/ (настоящей или копии с мутантом) → [(имя, ок, подробность)]."""
    env(tag)
    sys.path.insert(0, lib)
    P = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("watch_alert_fold", os.path.join(lib, "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    got = []

    def out(name, ok, detail=""):
        got.append((name, ok, detail))
    fold_cases(P, out)
    sweep_cases(P, w, out)
    return got


MUTANTS = {
    "без проверки окна": ("pantheon.py", "if last is not None and last <= t < last + window:", "if False:"),
    "без счётчика": ("pantheon.py", "if last is not None and n > 0:", "if False:"),
    "уборка через P.alert": ("watch.py", 'P.alert_fold("sandbox-sweep-failed", msg, "watch")', 'P.alert(msg, "watch")'),
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
                       text=True, timeout=120)
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
