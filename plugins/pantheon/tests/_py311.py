"""Интерпретатор для вызова CLI pantheon из тестов — тот же, что гоняет тест (Python 3.11+, metis-0571).

Подключение (тесты идут с -I, поэтому каталог добавляется явно):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _py311 import PY311
Тесты идут только на Python 3.11+ (AGENTS.md «Как проверять», CI — 3.14). Старше — код 1 и одна строка: pantheon.py
без tomllib не идёт, а молчаливый пропуск прятал бы непроверенное."""
import os
import sys

if sys.version_info < (3, 11):
    print("FAIL тесты pantheon идут на Python 3.11+, здесь %d.%d (%s)" % (sys.version_info[:2] + (sys.executable,)))
    sys.exit(1)

# Признак теста для всех тестов pantheon и их подпроцессов, унаследовавших окружение: notify пишет в
# STATE/notify-test.log, а не на экран владельца (metis-0307). Тест со своим окружением с нуля защищает сам
# notify: временный PANTHEON_STATE или HOME тоже уводят уведомление в файл.
os.environ["PANTHEON_TEST"] = "1"
PY311 = sys.executable


def mkroot(prefix):
    """Корневая временная папка теста, где git умеет создавать репозитории (metis-0715).

    Под `heavy` в окне роли TMPDIR — кэш песочницы, а песочница запрещает там запись в `.git/hooks` и `.git/config`
    (защита от подмены хуков): `git init` падает, тест видит «нет такой папки». Свой TMPDIR роли
    (`/tmp/claude-<uid>`) такой защиты не имеет. Берём TMPDIR, если в нём `.git/hooks` создаётся; иначе — первую
    папку из запасных, где создаётся; ни одной — TMPDIR как был (тест упадёт на своём месте, а не здесь)."""
    import tempfile
    uid = os.getuid()
    for base in (os.environ.get("TMPDIR"), "/tmp/claude-%d" % uid, "/private/tmp/claude-%d" % uid):
        if not base or not os.path.isdir(base):
            continue
        try:
            probe = tempfile.mkdtemp(prefix="gitprobe-", dir=base)
        except OSError:
            continue
        try:
            os.makedirs(os.path.join(probe, ".git", "hooks"))
            with open(os.path.join(probe, ".git", "config"), "w"):
                pass
            ok = True
        except OSError:
            ok = False
        finally:
            import shutil
            shutil.rmtree(probe, ignore_errors=True)
        if ok:
            return tempfile.mkdtemp(prefix=prefix, dir=base)
    return tempfile.mkdtemp(prefix=prefix)
