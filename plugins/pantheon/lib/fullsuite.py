"""Что считать командой полного набора тестов — одно правило для outside (дозапуск, узкий набор) и обёртки heavy
(место «полный», metis-1007). Только стандартная библиотека, Python 3.9+: heavy грузит файл по пути и не тянет ядро.

Полный набор — run-tests.py с папками плагинов и только ключами -j/--jobs/--timeout/--log-dir (каждый со значением).
Любой другой ключ (--affected, --base, --only, …) или ни одной папки — не полный набор: узкий прогон идёт как раньше.
"""
import os
import re
import shlex

VALUE_KEYS = ("-j", "--jobs", "--timeout", "--log-dir")


def parse_words(words, strict=False):
    """Слова команды → (путь run-tests.py, [папки]) или None. strict (outside): путь и папки относительные, без «..»
    — дозапуск берёт их из корня репозитория; heavy проверяет без strict: в worktree путь бывает абсолютным."""
    i = next((k for k, w in enumerate(words) if os.path.basename(w) == "run-tests.py"), None)
    if i is None:
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


def runner_args(cmd, strict=True):
    """Строка команды (без heavy) → (путь run-tests.py, [папки]) или None."""
    try:
        words = shlex.split(re.sub(r"\s#.*\Z", "", cmd, flags=re.S))
    except ValueError:
        return None
    got = parse_words(words, strict)
    if got is None:
        return None
    return (os.path.normpath(got[0]), [os.path.normpath(x) for x in got[1]]) if strict else got


def is_full(argv):
    """argv команды heavy → True, если это полный набор: сами слова (python3.14 -I …/run-tests.py -j 3 папки) или
    любое слово-строка с run-tests.py внутри (bash -c "… run-tests.py папки")."""
    if parse_words(list(argv)) is not None:
        return True
    return any("run-tests.py" in a and runner_args(a, strict=False) is not None for a in argv)
