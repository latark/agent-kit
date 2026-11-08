"""Что считать командой полного набора тестов — одно правило для outside (дозапуск, узкий набор) и обёртки heavy
(место «полный», metis-1007). Только стандартная библиотека, Python 3.9+: heavy грузит файл по пути и не тянет ядро.

Полный набор — run-tests.py (скрипт интерпретатора python) с папками плагинов и только ключами
-j/--jobs/--timeout/--log-dir (каждый со значением). Любой другой ключ (--affected, --base, --only, …) или ни одной
папки — не полный набор: узкий прогон идёт как раньше. В строке оболочки (sh -c) строка режется на сегменты по
| || && ; &, перенаправления (2>&1, >f) отбрасываются, разбирается только сегмент с run-tests.py.
"""
import os
import re
import shlex

VALUE_KEYS = ("-j", "--jobs", "--timeout", "--log-dir")
SEPARATORS = ("|", "||", "&&", ";", "&", "|&")
PYTHON = re.compile(r"python[0-9.]*\Z")


def parse_words(words, strict=False):
    """Слова одной команды → (путь run-tests.py, [папки]) или None. run-tests.py — скрипт интерпретатора python
    (перед ним только python и его ключи вроде -I), а не аргумент другой команды (grep foo …/run-tests.py).
    strict (outside): путь и папки относительные, без «..» — дозапуск берёт их из корня репозитория; heavy проверяет
    без strict: в worktree путь бывает абсолютным."""
    i = next((k for k, w in enumerate(words) if os.path.basename(w) == "run-tests.py"), None)
    if i is None:
        return None
    j = i - 1
    while j >= 0 and words[j].startswith("-"):
        j -= 1
    if j < 0 or not PYTHON.match(os.path.basename(words[j])):
        return None
    rest, dirs = iter(words[i + 1:]), []
    for w in rest:
        if w in VALUE_KEYS:
            if next(rest, None) is None:
                return None
        elif w.startswith("-"):
            return None
        else:
            dirs.append(w)
    rel = [words[i]] + dirs
    if not dirs or (strict and any(os.path.isabs(x) or ".." in x.split("/") for x in rel)):
        return None
    return words[i], dirs


def shell_segments(cmd):
    """Строка оболочки → список сегментов-слов: резка по | || && ; &, перенаправления (2>&1, >f, > f) отброшены.
    Не разобрать (кавычки) — ValueError."""
    lex = shlex.shlex(re.sub(r"\s#.*\Z", "", cmd, flags=re.S), posix=True, punctuation_chars=True)
    lex.whitespace_split, lex.commenters = True, ""
    segs, cur, skip = [], [], False
    for w in lex:
        if skip:  # цель перенаправления
            skip = False
        elif w in SEPARATORS:
            segs.append(cur)
            cur = []
        elif "<" in w or ">" in w:
            skip = True
            if cur and cur[-1].isdigit():  # номер дескриптора: 2>&1, 2>f
                cur.pop()
        else:
            cur.append(w)
    segs.append(cur)
    return segs


def runner_args(cmd, strict=True):
    """Строка команды (без heavy) → (путь run-tests.py, [папки]) или None. Разбирается только сегмент с run-tests.py."""
    try:
        segs = shell_segments(cmd)
    except ValueError:
        return None
    seg = next((s for s in segs if any(os.path.basename(w) == "run-tests.py" for w in s)), None)
    got = parse_words(seg, strict) if seg is not None else None
    if got is None:
        return None
    return (os.path.normpath(got[0]), [os.path.normpath(x) for x in got[1]]) if strict else got


def is_full(argv):
    """argv команды heavy → True, если это полный набор: сами слова (python3.14 -I …/run-tests.py -j 3 папки) или
    любое слово-строка с run-tests.py внутри (bash -c "… run-tests.py папки")."""
    if parse_words(list(argv)) is not None:
        return True
    return any("run-tests.py" in a and runner_args(a, strict=False) is not None for a in argv)
