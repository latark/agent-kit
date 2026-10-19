"""Python 3.11+ для вызова CLI pantheon из тестов: сам pantheon.py на системном 3.9 (нет tomllib) не идёт.

Подключение (тесты идут с -I, поэтому каталог добавляется явно):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _py311 import PY311
Тест на 3.11+ берёт свой интерпретатор; на 3.9 — первый подходящий (python3 из PATH, python3.14…3.11, Homebrew,
python.org). Не нашёлся — тест честно пропускается (код 0, строка в stdout), а не падает трассой tomllib в CLI."""
import glob
import os
import shutil
import subprocess
import sys


def _ok(py):
    try:
        return subprocess.run([py, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"],
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def find():
    if sys.version_info >= (3, 11):
        return sys.executable
    cands = [shutil.which("python3")] + [shutil.which(f"python3.{v}") for v in (14, 13, 12, 11)]
    for d in ("/opt/homebrew/bin", "/usr/local/bin", *glob.glob("/Library/Frameworks/Python.framework/Versions/*/bin")):
        cands += [os.path.join(d, f"python3.{v}") for v in (14, 13, 12, 11)]
    for c in cands:
        if c and os.path.exists(c) and _ok(c):
            return c
    print("пропуск: нужен Python 3.11+ для CLI pantheon, не найден")
    sys.exit(0)


# Признак теста для всех тестов pantheon и их подпроцессов, унаследовавших окружение: notify пишет в
# STATE/notify-test.log, а не на экран владельца (metis-0307). Тест со своим окружением с нуля защищает сам
# notify: временный PANTHEON_STATE или HOME тоже уводят уведомление в файл.
os.environ["PANTHEON_TEST"] = "1"
PY311 = find()
