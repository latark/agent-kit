#!/usr/bin/env python3
"""Ссылка уведомления ведёт на саму карточку (metis-0318): obsidian://open?path=<абсолютный путь файла в копии вида>.
Проверяем итоговую ссылку: tasks.card_url, pantheon.board_url (night.remind снят с вечерним вопросом, metis-0523); имя карточки
с «·» и «꞉»; ссылка раскодируется в существующий файл временной копии вида. Настоящий ~/ai/pantheon-view не трогаем.
Запуск: python3 -I plugins/pantheon/tests/test_card_link.py  (код 0 — все прошли)
"""
import atexit as _atexit
import importlib.util
import os
import shutil as _shutil
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402,F401  — Python 3.11+ и PANTHEON_TEST=1
_ROOT = tempfile.mkdtemp(prefix="cardlink-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
FAILS = []
os.environ.update({"HOME": os.path.join(_ROOT, "home"), "PANTHEON_STATE": os.path.join(_ROOT, "state"),
                   "PANTHEON_HOME": os.path.join(_ROOT, "home", "ai", "pantheon")})
_spec = importlib.util.spec_from_file_location("pantheon_cardlink_test", os.path.join(LIB, "pantheon.py"))
P = importlib.util.module_from_spec(_spec)
sys.modules["pantheon_cardlink_test"] = P
_spec.loader.exec_module(P)
# копия вида — вне HOME и в папке с пробелом: путь, зашитый от HOME, тест ловит (review-130, замечание 2)
VIEW = os.path.join(_ROOT, "вид с пробелом", "pantheon-view")
assert not VIEW.startswith(os.environ["HOME"] + os.sep)
P.VIEW = VIEW
T = P.tasks_mod()

HEAD = {"type": "inbox", "id": "inbox-0005", "title": 'Запустить: сегодня #на ночь "задачи" 8/10'}


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("НЕ ПРОШЛО:", what)


def target_path(url):
    u = urlsplit(url)
    check(u.scheme == "obsidian" and u.netloc == "open", f"не obsidian://open: {url}")
    q = parse_qs(u.query)
    check(list(q) == ["path"], f"в ссылке не только path (vault/file ломают холодный старт): {url}")
    return (q.get("path") or [""])[0]


def make_card(name, ext=".md"):
    d = os.path.join(VIEW, "Доска")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name + ext)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("---\n---\n")
    return p


def test_names():
    name = T.card_name(HEAD)
    check("꞉" in name and "·" in name, f"в имени нет «꞉» и «·»: {name}")


def test_card_url():
    name = T.card_name(HEAD)
    f = make_card(name)
    url = T.card_url(VIEW, name)
    check(target_path(url) == f and os.path.isfile(target_path(url)), f"card_url не ведёт на файл карточки: {url}")
    check("%2F" in url and "%20" in url and " " not in url, f"«/» и пробел не закодированы по Obsidian URI: {url}")


def test_board_url():
    base = make_card("Доска", ".base")
    url = P.board_url()
    check(target_path(url) == base, f"board_url() не ведёт на Доска.base: {url}")
    name = T.card_name(HEAD)
    check(target_path(P.board_url(name + ".md")) == os.path.join(VIEW, "Доска", name + ".md"),
          "board_url(имя.md) не ведёт на карточку")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append(f"{fn.__name__}: {type(ex).__name__}: {ex}")
    print(f"тестов: {len(tests)}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
