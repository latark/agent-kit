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
