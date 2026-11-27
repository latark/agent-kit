#!/usr/bin/env python3
"""Тревога на петле ревью argus (metis-1347, приём PurpleFlow п. 1, разбор metis-1339): review_loop — проверка
дежурного — по записям шлюза (records.jsonl) считает круги PR (круг — один проверенный head) и на круге 3 и дальше,
кончившемся «вернуть», пишет тревогу один раз на head.

Запуск: python3 -I plugins/pantheon/tests/test_review_loop.py  (код выхода 0 — все прошли)
Проверяет: три head, последний «вернуть» → тревога «петля ревью … круг 3» в alerts.md, повтор прохода молчит; два
круга «вернуть» → тревоги нет; круг 3 «принять» → нет; вердикт старше REVIEW_LOOP_AGE → нет. Мутанты — внутри теста:
копия плагина с порогом круга 4 и копия без условия «вернуть» — каждую убивает свой случай.
"""
# ruff: noqa: F403, F405
import os
import shutil
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_common import *  # noqa: F403

LOOP = ("import sys; sys.path.insert(0, sys.argv[1]); import pantheon as p; "
        "print(' '.join(p.review_loop(float(sys.argv[2]))))")
ROUND = "REVIEW_LOOP_ROUND = 3\n"
LAST = 'last != "вернуть" or '




def copy_plugin(src, dst):
    """Копия плагина без bin/ и tests/ (metis-1431): папками верхнего уровня, а не copytree корня, чтобы карта не
    связывала тест с bin/heavy, которого он не зовёт."""
    os.makedirs(dst)
    for n in sorted(os.listdir(src)):
        if n in ("bin", "tests", "__pycache__", ".git"):
            continue
        s = os.path.join(src, n)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dst, n), ignore=shutil.ignore_patterns("__pycache__", "tests", ".git"))
        else:
            shutil.copy2(s, os.path.join(dst, n))

def stamp(t):
    return datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


def box(kinds, age=600):
    """PR #7 с кругами по kinds («accept»/«reject») на разных head; последний вердикт — age с до T0."""
    b = Box()
    b.records = []
    shas = [f"{i:07x}" + "c" * 33 for i in range(1, len(kinds) + 1)]
    for i, (sha, kind) in enumerate(zip(shas, kinds)):
        b.add(kind, sha=sha, sid=f"s{i}", aid=f"a{i}", time=stamp(T0 - age - 60 * (len(kinds) - 1 - i)))
    return b, shas[-1]


def loop(b, libdir=LIBDIR):
    r = subprocess.run([PY311, "-I", "-c", LOOP, libdir, str(T0)], env=b.env(T0), capture_output=True, text=True,
                       timeout=60)
    return r.returncode, r.stdout.strip(), r.stdout + r.stderr


def alerted(b):
    return "петля ревью latark/agent-kit#7" in b.alerts()


def mutant_lib(tmp, old, new):
    """Копия плагина pantheon с заменой old → new в lib/review.py → путь к её lib (None — old не один)."""
    plugins = os.path.join(tmp, "mut", "plugins")
    plug = os.path.join(plugins, "pantheon")
    copy_plugin(os.path.dirname(LIBDIR), plug)
    os.symlink(os.path.dirname(GUARD_HOOKS), os.path.join(plugins, "guard"))   # соседний плагин, как в репозитории
    f = os.path.join(plug, "lib", "review.py")
    src = open(f, encoding="utf-8").read()
    if src.count(old) != 1:
        return None
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(src.replace(old, new))
    return os.path.join(plug, "lib")


def test_round3_reject_alerts_once():
    b, last = box(["reject", "reject", "reject"])
    rc, keys, out = loop(b)
    text = b.alerts()
    check("круг 3 «вернуть» — тревога «петля ревью … круг 3» с head и «3 из 3»",
          rc == 0 and keys == "review-loop-latark/agent-kit#7" and alerted(b) and "круг 3" in text
          and last[:8] in text and "3 из 3" in text, out + text)
    rc, keys, out = loop(b)
    check("повтор прохода на том же head — тревога не дублируется",
          rc == 0 and b.alerts().count("петля ревью") == 1, out + b.alerts())


def test_round2_no_alert():
    b, _ = box(["reject", "reject"])
    rc, keys, out = loop(b)
    check("круг 2 «вернуть» — тревоги нет", rc == 0 and keys == "" and not alerted(b), out + b.alerts())


def test_round3_accept_no_alert():
    b, _ = box(["reject", "reject", "accept"])
    rc, keys, out = loop(b)
    check("круг 3 «принять» — тревоги нет", rc == 0 and keys == "" and not alerted(b), out + b.alerts())


def test_old_round_no_alert():
    b, _ = box(["reject", "reject", "reject"], age=4 * 24 * 3600)
    rc, keys, out = loop(b)
    check("круг 3 «вернуть» старше 3 суток — тревоги нет (давно брошенный PR)", rc == 0 and keys == ""
          and not alerted(b), out + b.alerts())


def test_mutant_round_threshold():
    b, _ = box(["reject", "reject", "reject"])
    lib = mutant_lib(b.tmp, ROUND, "REVIEW_LOOP_ROUND = 4\n")
    check("мутант: строка порога круга в review.py одна", lib is not None, ROUND)
    if lib:
        rc, keys, out = loop(b, lib)
        check("мутант «порог круга 4» убит случаем «круг 3 — тревога»", keys == "" and not alerted(b), out)


def test_mutant_no_reject_condition():
    b, _ = box(["reject", "reject", "accept"])
    lib = mutant_lib(b.tmp, LAST, "")
    check("мутант: условие «вернуть» в review_loop одно", lib is not None, LAST)
    if lib:
        rc, keys, out = loop(b, lib)
        check("мутант без условия «вернуть» убит случаем «круг 3 принять — тревоги нет»", alerted(b), out)


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    cases = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    run_cases(cases, FAILS, lambda name, err: FAILS.append(name))
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else f'{len(cases)} из {len(cases)} случаев прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
