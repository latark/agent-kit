#!/usr/bin/env python3
"""Синтетические тесты `pantheon plugins update` (metis-0052): тик ставит новые версии плагинов agent-kit после тестов.

Запуск: python3 -I plugins/pantheon/tests/test_plugins_update.py  (код выхода 0 — все прошли)
Идёт и на системном /usr/bin/python3 (3.9): сам pantheon.py тогда запускается через python3 из PATH (нужен 3.11).
Временный HOME с каталогом agent-kit и кэшем установленной версии; `claude` — заглушка первой в PATH: пишет argv в
файл, на `plugin list --json` отдаёт JSON из файла (после `plugin update` — уже с новой версией), на
`plugin marketplace update` — код из STUB_MKT_RC. Настоящие `claude plugin …` не запускаются.
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="plugins_update-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "pantheon.py")

STUB = """#!/bin/sh
echo "$*" >> "$STUB_DIR/argv.log"
case "$1 $2" in
  "plugin marketplace") exit "${STUB_MKT_RC:-0}" ;;
  "plugin list") cat "$STUB_DIR/list.json" ;;
  "plugin update")
    if [ "${STUB_UPD_RC:-0}" = 0 ] && [ -f "$STUB_DIR/list-after.json" ]; then
      cp "$STUB_DIR/list-after.json" "$STUB_DIR/list.json"
    fi
    exit "${STUB_UPD_RC:-0}" ;;
esac
exit 0
"""

OK = 'print("ok")\n'
OLD_FAIL = 'import os\nprint("FAIL старое падение в " + os.path.abspath(__file__))\nraise SystemExit(1)\n'
NEW_FAIL = 'print("FAIL новая ошибка")\nraise SystemExit(1)\n'
NEW_EXC = 'raise KeyError("x")\n'
OLD_FAIL_RC = 'print("FAIL старое", flush=True)\nraise SystemExit(1)\n'
NEW_KILLED = 'print("FAIL старое", flush=True)\nimport os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n'
# цветной трейсбек (так печатает 3.13+ при FORCE_COLOR): без вырезания ANSI тип исключения не разобрать
NEW_COLOR_EXC = ('print("\\x1b[35mTraceback (most recent call last):\\x1b[0m")\nprint("  File \\"t.py\\", line 1")\n'
                 'print("\\x1b[1;35mKeyError\\x1b[0m: \\x1b[35m\'x\'\\x1b[0m")\nraise SystemExit(1)\n')
# подпроцесс тестов пишет свой TMPDIR в файл: он обязан лежать внутри временной папки прогона
REC_TMPDIR = 'import os\nopen(os.environ["REC_FILE"] + ".t", "a").write(os.environ.get("TMPDIR", "") + "\\n")\n'
# тесты идут без цвета: FORCE_COLOR снят, NO_COLOR=1, PYTHON_COLORS=0
COLORLESS = ('import os\nif os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE") '
             'or os.environ.get("NO_COLOR") != "1" or os.environ.get("PYTHON_COLORS") != "0":\n'
             '    print("FAIL цвет включён")\n    raise SystemExit(1)\n')


def pantheon_python():
    if sys.version_info >= (3, 11):
        return sys.executable
    py = shutil.which("python3")
    if not py:
        sys.exit("нужен python3 3.11+ в PATH: pantheon.py на системном python не идёт")
    ver = subprocess.run([py, "-c", "import sys; print(sys.version_info >= (3, 11))"], capture_output=True,
                         text=True).stdout.strip()
    if ver != "True":
        sys.exit(f"{py} старше 3.11: pantheon.py на нём не идёт")
    return py


PY = pantheon_python()


class Env:
    """Временный HOME: каталог agent-kit, кэш установленной версии плагина x, заглушка claude."""

    def __init__(self, installed, catalog, base_test, new_test, known=True, name="x"):
        self.name = name
        self.tmp = tempfile.mkdtemp(prefix="plugins-update-test-")
        t = self.tmp
        self.home, self.stub = os.path.join(t, "home"), os.path.join(t, "stub")
        self.pantheon, self.state = os.path.join(t, "pantheon"), os.path.join(t, "state")
        self.counter = os.path.join(t, "runs.log")
        self.tmpdir = os.path.join(t, "T")  # свой TMPDIR: уборку проверяем здесь, а не в общей временной папке
        self.notes = os.path.join(t, "notify.log")
        for d in (self.home, self.stub, self.pantheon, self.tmpdir):
            os.makedirs(d)
        plugins = os.path.join(self.home, ".claude", "plugins")
        mkt = os.path.join(plugins, "marketplaces", "agent-kit")
        cache = os.path.join(plugins, "cache", "agent-kit", name, installed)
        self.src = os.path.join(mkt, "plugins", name)
        self.plugin(self.src, catalog, new_test)
        self.plugin(cache, installed, base_test)
        # что поставит `claude plugin update`: копия каталога в кэше плюс служебный .in_use
        self.after = os.path.join(plugins, "cache", "agent-kit", name, catalog + "-new")
        shutil.copytree(self.src, self.after, symlinks=True)
        self.write(os.path.join(self.after, ".in_use"), "1")
        self.write(os.path.join(mkt, ".claude-plugin", "marketplace.json"),
                   json.dumps({"name": "agent-kit", "plugins": [{"name": name, "source": "./plugins/" + name},
                                                               {"name": "far", "source": "../../elsewhere"}]}))
        if known:
            self.write(os.path.join(plugins, "known_marketplaces.json"),
                       json.dumps({"agent-kit": {"installLocation": mkt}}))
        other = [{"id": "x@other", "version": "0.1", "scope": "user", "installPath": "/nowhere"},
                 {"id": "x@agent-kit", "version": "0.0.1", "scope": "project", "installPath": "/nowhere"}]
        row = {"id": name + "@agent-kit", "version": installed, "scope": "user", "installPath": cache}
        self.write(os.path.join(self.stub, "list.json"), json.dumps(other + [row]))
        self.write(os.path.join(self.stub, "list-after.json"),
                   json.dumps(other + [{**row, "version": catalog, "installPath": self.after}]))
        self.write(os.path.join(self.stub, "claude"), STUB)
        os.chmod(os.path.join(self.stub, "claude"), 0o755)

    def write(self, p, text):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    def plugin(self, d, version, body):
        self.write(os.path.join(d, ".claude-plugin", "plugin.json"), json.dumps({"name": self.name, "version": version}))
        if body is not None:  # None — у версии нет tests/test_*.py
            self.write(os.path.join(d, "tests", "test_a.py"),
                       f"with open({self.counter!r}, 'a') as fh:\n    fh.write('run\\n')\n" + body)
        self.write(os.path.join(d, "tests", "helper.py"), "raise SystemExit(3)\n")  # не test_*.py — не гоняется

    def leftovers(self):
        """Что осталось от прогона: своя TMPDIR и STATE/plugins/tmp."""
        st = os.path.join(self.state, "plugins", "tmp")
        return os.listdir(self.tmpdir) + (os.listdir(st) if os.path.isdir(st) else [])

    def notified(self):
        return open(self.notes, encoding="utf-8").read() if os.path.exists(self.notes) else ""

    def run(self, *args, extra=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PANTHEON_", "STUB_"))}
        env.update({"PATH": self.stub + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.home,
                    "PANTHEON_HOME": self.pantheon, "PANTHEON_STATE": self.state, "PANTHEON_NO_NOTIFY": "1",
                    "PANTHEON_NOTIFY_LOG": self.notes, "STUB_DIR": self.stub, "TMPDIR": self.tmpdir})
        env.update(extra or {})
        args = args or ("plugins", "update", "--quiet")
        return subprocess.run([PY, "-I", LIB, *args], env=env, capture_output=True, text=True, timeout=300)

    def py(self, code, *args):
        """Код с `import pantheon as P` в этом HOME (как окно роли: только чтение реестра); stdout строками."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PANTHEON_", "STUB_"))}
        env.update({"HOME": self.home, "PANTHEON_HOME": self.pantheon, "PANTHEON_STATE": self.state,
                    "PANTHEON_NO_NOTIFY": "1", "TMPDIR": self.tmpdir})
        r = subprocess.run([PY, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pantheon as P\n" + code,
                            os.path.dirname(LIB), *args], env=env, capture_output=True, text=True, timeout=120)
        return r.stdout.split("\n")[:-1] if r.returncode == 0 else ["ERR " + r.stderr[-300:]]

    def verify(self, d):
        """verified.json: дерево d проверено (как после успешной установки)."""
        return self.py("P.verified_write(sys.argv[2], sys.argv[3], '?', 'test')", self.name, d)

    def verified(self):
        p = os.path.join(self.state, "plugins", "verified.json")
        return json.load(open(p)) if os.path.exists(p) else {}

    def argv(self):
        p = os.path.join(self.stub, "argv.log")
        return open(p).read() if os.path.exists(p) else ""

    def alerts(self):
        p = os.path.join(self.pantheon, "alerts.md")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    def runs(self):
        return open(self.counter).read().count("run") if os.path.exists(self.counter) else 0

    def marks(self):
        p = os.path.join(self.state, "plugins", "marks.json")
        return json.load(open(p)) if os.path.exists(p) else {}

    def journal(self):
        p = os.path.join(self.state, "plugins", "journal.log")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def main():
    results = []

    def check(name, cond, detail=""):
        results.append(bool(cond))
        print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else f"\n     {detail}"))

    # Новых нет: версия каталога та же — молчит, код 0, update не вызван, тесты не гонялись
    e = Env("1.0.0", "1.0.0", OK, OK)
    r = e.run()
    check("нет новых: --quiet молчит, код 0, update не вызван",
          r.returncode == 0 and r.stdout == "" and "plugin update" not in e.argv() and e.runs() == 0,
          f"{r.returncode} {r.stdout!r} {r.stderr!r} {e.argv()!r}")
    check("нет новых: каталог обновлён (marketplace update agent-kit)",
          "plugin marketplace update agent-kit" in e.argv())
    r = e.run("plugins", "update")
    check("без --quiet: строка на плагин", r.returncode == 0 and "x: 1.0.0, новее нет" in r.stdout, r.stdout)
    e.close()

    # metis-0321: ссылка ~/.local/share/pantheon/current — на установленную версию. Зелёные тесты и вставшая версия —
    # ссылка переезжает на новую папку кэша; красные — остаётся на старой, клон маркетплейса живым не становится
    e = Env("1.0.0", "1.1.0", OK, OK, name="pantheon")
    cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
    old_cache = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "pantheon", "1.0.0")
    os.makedirs(os.path.dirname(cur))
    os.symlink(old_cache, cur)
    r = e.run()
    check("pantheon зелёный: current → новая установленная версия, не клон",
          r.returncode == 0 and os.path.islink(cur) and os.path.realpath(cur) == os.path.realpath(e.after),
          f"{r.returncode} {r.stderr!r} {os.path.realpath(cur)}")
    e.close()
    e = Env("1.0.0", "1.1.0", OK, NEW_FAIL, name="pantheon")
    cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
    old_cache = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "pantheon", "1.0.0")
    os.makedirs(os.path.dirname(cur))
    os.symlink(old_cache, cur)
    r = e.run()
    check("pantheon красный: current остаётся на установленной, клон и новая папка не живые",
          "plugin update" not in e.argv() and os.readlink(cur) == old_cache, f"{e.argv()!r} {os.readlink(cur)}")
    e.close()
    e = Env("1.0.0", "1.1.0", OK, OK)
    cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
    e.run()
    check("другой плагин (x): ссылку current не трогает", not os.path.lexists(cur))
    e.close()

    # ревью 90a, п.2: тесты зелёные, а встала другая версия или другое дерево — current остаётся прежней
    # (мутант: link_current до сверки got == new и хеша в _plugin_install)
    for what in ("версия", "дерево"):
        e = Env("1.0.0", "1.1.0", OK, OK, name="pantheon")
        cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
        old_cache = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "pantheon", "1.0.0")
        os.makedirs(os.path.dirname(cur))
        os.symlink(old_cache, cur)
        if what == "версия":
            la = os.path.join(e.stub, "list-after.json")
            rows = json.load(open(la))
            for row in rows:
                if row["id"] == "pantheon@agent-kit":
                    row["version"] = "1.1.1"
            e.write(la, json.dumps(rows))
        else:
            e.write(os.path.join(e.after, "hooks", "evil.py"), "print('не проверялось')\n")
        plugins = os.path.join(e.home, ".claude", "plugins")
        reg = lambda p: e.write(os.path.join(plugins, "installed_plugins.json"), json.dumps({"version": 2, "plugins": {
            "pantheon@agent-kit": [{"scope": "user", "installPath": p, "version": "1.0.0"}]}}))
        reg(old_cache)
        e.verify(old_cache)
        e.run()
        check(f"pantheon, зелёные тесты, но встала другая {what}: current остаётся прежней, КРИТИЧНО в alerts.md",
              os.readlink(cur) == old_cache and "КРИТИЧНО" in e.alerts(), f"{os.readlink(cur)} {e.alerts()!r}")
        # второй проход (Claude Code записал новую папку в реестр): «новее нет» не должно перевести current на
        # непроверенное дерево (ревью 90b, круг 2; мутант: без метки unchecked.json)
        reg(e.after)
        e.run()
        check(f"pantheon, встала другая {what}, второй проход: current всё ещё прежняя, тревога о непроверенном дереве",
              os.readlink(cur) == old_cache and "не проверено" in e.alerts(), f"{os.readlink(cur)} {e.alerts()!r}")
        e.close()

    # успешная установка пишет verified.json (хеш, путь), окна идут на это дерево
    # (мутант: без verified_write в _plugin_install — agents.py окна не найден)
    e = Env("1.0.0", "1.1.0", OK, OK, name="pantheon")
    r = e.run()
    v = e.verified().get("pantheon") or {}
    reg_after = lambda: e.write(os.path.join(e.home, ".claude", "plugins", "installed_plugins.json"), json.dumps(
        {"version": 2, "plugins": {"pantheon@agent-kit": [{"scope": "user", "installPath": e.after, "version": "1.1.0"}]}}))
    reg_after()
    got = e.py("print(P.installed_dir('pantheon'))")
    check("успешная установка: verified.json — путь и хеш вставшего дерева, живой код и окна из него",
          r.returncode == 0 and v.get("path") == os.path.realpath(e.after) and v.get("version") == "1.1.0"
          and len(v.get("hash") or "") == 64 and got == [os.path.realpath(e.after)],
          f"{r.stderr!r} {v} {got}")
    e.close()

    # ревью 90a и 90b, круг 3: после КРИТИЧНО (встало непроверенное, реестр уже ведёт туда) ни один путь не делает его
    # живым — удалённая метка, третье дерево той же версии, служебные файлы, обычный проход, `pantheon install`; окна —
    # из последнего проверенного, не из клона (мутанты: вернуть клон в _installed_hook; убрать запись verified.json)
    for case in ("deleted", "third_tree", "dot_top", "pycache", "plain", "install", "no_verified", "broken_verified"):
        e = Env("1.0.0", "1.1.0", OK, OK, name="pantheon")
        cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
        old_cache = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "pantheon", "1.0.0")
        clone_hook = os.path.join(e.src, "hooks", "agents.py")
        e.write(os.path.join(old_cache, "hooks", "agents.py"), "# проверенный 1.0.0\n")
        e.write(clone_hook, "# клон: голова main\n")
        os.makedirs(os.path.dirname(cur))
        os.symlink(old_cache, cur)
        e.write(os.path.join(e.home, ".claude", "plugins", "installed_plugins.json"), json.dumps(
            {"version": 2, "plugins": {"pantheon@agent-kit": [{"scope": "user", "installPath": old_cache}]}}))
        e.verify(old_cache)
        e.write(os.path.join(e.after, "hooks", "evil.py"), "print(1)\n")
        e.write(os.path.join(e.after, "hooks", "agents.py"), "# непроверенный\n")
        e.run()
        reg_after = lambda: e.write(os.path.join(e.home, ".claude", "plugins", "installed_plugins.json"), json.dumps(
            {"version": 2, "plugins": {"pantheon@agent-kit": [{"scope": "user", "installPath": e.after,
                                                               "version": "1.1.0"}]}}))
        reg_after()
        e.run()
        um = os.path.join(e.state, "plugins", "unchecked.json")
        vj = os.path.join(e.state, "plugins", "verified.json")
        if case == "deleted":
            os.remove(um)
        elif case == "third_tree":
            e.write(os.path.join(e.after, "hooks", "evil2.py"), "print(2)\n")
        elif case == "dot_top":
            e.write(os.path.join(e.after, ".orphaned_at"), "123\n")
        elif case == "pycache":
            e.write(os.path.join(e.after, "lib", "__pycache__", "x.pyc"), "x\n")
        elif case == "no_verified":
            os.remove(vj)
        elif case == "broken_verified":
            e.write(vj, "{")
        r = e.run("install", extra={"PANTHEON_DRYRUN": "1"}) if case == "install" else e.run()
        hook = (e.py("print(P.agents_script())") or ["-"])[0]
        live_ok = os.path.realpath(cur) == os.path.realpath(old_cache)
        if case in ("no_verified", "broken_verified"):
            want_hook = not os.path.exists(hook) and "marketplaces" not in hook
        else:
            want_hook = hook == os.path.realpath(os.path.join(old_cache, "hooks", "agents.py"))
        check(f"после КРИТИЧНО, {case}: current на последнем проверенном, окна не из клона и не из непроверенного",
              live_ok and want_hook and "не проверено" in e.alerts() + r.stdout,
              f"rc={r.returncode} cur={os.path.realpath(cur)} hook={hook} {r.stdout[-200:]!r}")
        e.close()

    # ревью 90a, п.3: версию поставили руками (новее нет), а current отстала или повисла — перевешивается
    # на installed_dir; плагин x ссылку не трогает
    for what in ("отстала", "повисла"):
        e = Env("1.0.0", "1.0.0", OK, OK, name="pantheon")
        plugins = os.path.join(e.home, ".claude", "plugins")
        cache = os.path.join(plugins, "cache", "agent-kit", "pantheon", "1.0.0")
        e.write(os.path.join(plugins, "installed_plugins.json"), json.dumps({"version": 2, "plugins": {
            "pantheon@agent-kit": [{"scope": "user", "installPath": cache, "version": "1.0.0"}]}}))
        cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
        os.makedirs(os.path.dirname(cur))
        if what == "отстала":
            stale = os.path.join(plugins, "cache", "agent-kit", "pantheon", "0.9.0")
            e.plugin(stale, "0.9.0", OK)
        else:
            stale = os.path.join(plugins, "cache", "agent-kit", "pantheon", "0.8.0")  # папки нет
        os.symlink(stale, cur)
        e.verify(cache)
        r = e.run()
        check(f"pantheon, новее нет, current {what}: перевешена на установленную проверенную папку",
              r.returncode == 0 and os.path.realpath(cur) == os.path.realpath(cache), f"{r.stderr!r} {os.readlink(cur)}")
        e.close()
    e = Env("1.0.0", "1.0.0", OK, OK, name="pantheon")
    plugins = os.path.join(e.home, ".claude", "plugins")
    cache = os.path.join(plugins, "cache", "agent-kit", "pantheon", "1.0.0")
    e.write(os.path.join(plugins, "installed_plugins.json"), json.dumps({"version": 2, "plugins": {
        "pantheon@agent-kit": [{"scope": "user", "installPath": cache, "version": "1.0.0"}]}}))
    cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
    os.makedirs(os.path.dirname(cur))
    os.symlink(cache, cur)
    before = os.lstat(cur).st_ino
    e.run()
    check("pantheon, новее нет, current верна: ссылка не пересоздаётся",
          os.readlink(cur) == cache and os.lstat(cur).st_ino == before)
    e.close()

    # Каталог старее установленной — откат не ставим
    e = Env("1.0.0", "0.9.0", OK, OK)
    r = e.run()
    check("версия каталога старее: не ставим", r.returncode == 0 and "plugin update" not in e.argv() and e.runs() == 0)
    e.close()

    # Новая, тесты зелёные — update, строка в alerts.md и журнал, метки нет
    e = Env("1.0.0", "1.1.0", OK, OK)
    r = e.run()
    check("зелёные: вызван plugin update x@agent-kit -s user, код 0",
          r.returncode == 0 and "plugin update x@agent-kit -s user" in e.argv(),
          f"{r.returncode} {r.stderr!r} {e.argv()!r}")
    check("зелёные: без -y", " -y" not in e.argv())
    check("зелёные: «обновлён x 1.0.0 → 1.1.0» в alerts.md",
          "plugins-update · обновлён x 1.0.0 → 1.1.0, плановый проход перезапустит свободные окна" in e.alerts(), e.alerts())
    rsp = os.path.join(e.state, "plugins", "respawn.json")
    rj = json.load(open(rsp)) if os.path.exists(rsp) else {}
    check("зелёные: отметка «нужен перезапуск» respawn.json {since, plugins: [x], done: []} (metis-0181)",
          rj.get("plugins") == ["x"] and float(rj.get("since") or 0) > 0 and rj.get("done") == [], rj)
    check("зелёные: строка в журнале, метки нет", "x 1.0.0 → 1.1.0: обновлён" in e.journal() and "x" not in e.marks())
    log = os.path.join(e.state, "plugins", "x-1.1.0.log")
    check("зелёные: в логе обе версии, helper.py не гонялся",
          os.path.exists(log) and "новая 1.1.0" in open(log).read() and "база 1.0.0" in open(log).read()
          and "helper.py" not in open(log).read())
    check("зелёные: временные копии убраны (своя TMPDIR и STATE/plugins/tmp пусты)", e.leftovers() == [],
          e.leftovers())
    check("зелёные: без критической тревоги (хеш кэша с .in_use совпал с проверенной копией)",
          "КРИТИЧНО" not in e.alerts() and e.notified() == "")
    e.close()

    # Подпроцесс тестов получает TMPDIR внутри временной папки прогона (STATE/plugins/tmp), а не общий
    e = Env("1.0.0", "1.1.0", REC_TMPDIR, REC_TMPDIR)
    rec = os.path.join(e.tmp, "rec")
    r = e.run(extra={"REC_FILE": rec})
    seen = open(rec + ".t").read().split() if os.path.exists(rec + ".t") else []
    root = os.path.join(e.state, "plugins", "tmp") + os.sep
    check("TMPDIR подпроцесса тестов — внутри временной папки прогона, не общий",
          len(seen) >= 2 and all(os.path.realpath(t).startswith(os.path.realpath(root)) for t in seen)
          and e.tmpdir not in seen, f"{seen} {r.stderr!r}")
    check("TMPDIR подпроцесса: после прогона папок не осталось", e.leftovers() == [], e.leftovers())
    e.close()

    # Встало не то, что проверяли: update сам подтянул каталог — другое содержимое той же версии
    e = Env("1.0.0", "1.1.0", OK, OK)
    e.write(os.path.join(e.after, "hooks", "evil.py"), "print('не проверялось')\n")
    r = e.run()
    check("TOCTOU, другое содержимое: КРИТИЧНО в alerts.md и уведомление, код 76, метки нет",
          r.returncode == 76 and "КРИТИЧНО: встала непроверенная версия x 1.1.0 (проверялась 1.1.0)" in e.alerts()
          and "Пантеон · критично|встала непроверенная версия x 1.1.0" in e.notified() and "x" not in e.marks()
          and "Руками" not in e.alerts() and "обновлён" not in e.alerts(), f"{r.returncode} {e.alerts()!r}")
    e.close()

    # Встало не то, что проверяли: другая версия
    e = Env("1.0.0", "1.1.0", OK, OK)
    p = os.path.join(e.stub, "list-after.json")
    rows = json.load(open(p))
    rows[-1]["version"] = "1.2.0"
    e.write(p, json.dumps(rows))
    r = e.run()
    check("TOCTOU, другая версия: КРИТИЧНО «x 1.2.0 (проверялась 1.1.0)», код 76",
          r.returncode == 76 and "встала непроверенная версия x 1.2.0 (проверялась 1.1.0)" in e.alerts()
          and "x" not in e.marks(), e.alerts())
    e.close()

    # Нет тестов у новой версии — красное, даже если их нет и у базы
    e = Env("1.0.0", "1.1.0", None, None)
    r = e.run()
    check("нет tests/test_*.py ни у новой, ни у базы: красное «нет тестов», update не вызван",
          r.returncode == 76 and "нет тестов" in e.alerts() and "plugin update" not in e.argv(), e.alerts())
    e.close()
    e = Env("1.0.0", "1.1.0", OK, None)
    r = e.run()
    check("нет тестов у новой, у базы есть: красное", r.returncode == 76 and "plugin update" not in e.argv())
    e.close()

    # Гибель по сигналу за той же строкой FAIL, что и у базы, — новое падение («код -9»)
    e = Env("1.0.0", "1.1.0", OLD_FAIL_RC, NEW_KILLED)
    r = e.run()
    check("SIGKILL при старой строке FAIL: красное с «код -9»",
          r.returncode == 76 and "test_a.py: код -9" in e.alerts() and "plugin update" not in e.argv(), e.alerts())
    e.close()

    # Цветной трейсбек: ANSI вырезается до разбора
    e = Env("1.0.0", "1.1.0", OK, NEW_COLOR_EXC)
    r = e.run()
    check("цветной трейсбек: подпись «исключение KeyError»",
          r.returncode == 76 and "test_a.py: исключение KeyError" in e.alerts(), e.alerts())
    e.close()

    # Тесты идут без цвета, даже если у тика FORCE_COLOR
    e = Env("1.0.0", "1.1.0", OK, COLORLESS)
    r = e.run(extra={"FORCE_COLOR": "1", "CLICOLOR_FORCE": "1", "NO_COLOR": ""})
    check("окружение тестов: FORCE_COLOR снят, NO_COLOR=1, PYTHON_COLORS=0",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), e.alerts())
    e.close()

    # Прерванный прогон: метка testing той же версии — красное без прогона; остатки временных копий убраны
    e = Env("1.0.0", "1.1.0", OK, OK)
    e.write(os.path.join(e.state, "plugins", "marks.json"),
            json.dumps({"x": {"version": "1.1.0", "result": "testing", "log": "x.log", "at": "раньше"}}))
    e.write(os.path.join(e.state, "plugins", "tmp", "x-old", "new", "x", "f.py"), "остаток\n")
    r = e.run()
    check("метка testing: красное «прогон прерван» без прогона, update не вызван",
          r.returncode == 76 and "прогон тестов прерван" in e.alerts() and e.runs() == 0
          and "plugin update" not in e.argv() and e.marks().get("x", {}).get("result") == "red", e.alerts())
    check("остатки прерванного прогона в STATE/plugins/tmp удалены", e.leftovers() == [], e.leftovers())
    e.close()

    # За один запуск — тесты не больше одного плагина
    e = Env("1.0.0", "1.1.0", OK, OK)
    mkt = os.path.dirname(os.path.dirname(e.src))
    e.plugin(os.path.join(mkt, "plugins", "y"), "2.1.0", OK)
    ycache = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "y", "2.0.0")
    e.plugin(ycache, "2.0.0", OK)
    e.write(os.path.join(mkt, ".claude-plugin", "marketplace.json"),
            json.dumps({"name": "agent-kit", "plugins": [{"name": "x", "source": "./plugins/x"},
                                                        {"name": "y", "source": "./plugins/y"}]}))
    yrow = {"id": "y@agent-kit", "version": "2.0.0", "scope": "user", "installPath": ycache}
    for f in ("list.json", "list-after.json"):
        p = os.path.join(e.stub, f)
        e.write(p, json.dumps(json.load(open(p)) + [yrow]))
    r = e.run()
    check("два плагина с новыми версиями: за запуск проверен и поставлен один",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv() and "plugin update y@agent-kit" not in e.argv()
          and "y" not in e.marks(), f"{r.returncode} {e.argv()!r} {e.marks()}")
    e.run()
    check("второй плагин — на следующем запуске", "plugin update y@agent-kit" in e.argv(), e.argv())
    e.close()

    # Метка testing старой версии не мешает новой
    e = Env("1.0.0", "1.1.0", OK, OK)
    e.write(os.path.join(e.state, "plugins", "marks.json"),
            json.dumps({"x": {"version": "1.0.5", "result": "testing", "log": "x.log", "at": "раньше"}}))
    r = e.run()
    check("метка testing другой версии: тесты и установка", r.returncode == 0 and e.runs() > 0
          and "обновлён x 1.0.0 → 1.1.0" in e.alerts())
    e.close()

    # Новая, тесты красные — не ставим, тревога с логом, метка red, код 76
    e = Env("1.0.0", "1.2.0", OK, NEW_FAIL)
    r = e.run()
    al = e.alerts()
    check("красные: update не вызван, код 76", r.returncode == 76 and "plugin update" not in e.argv(),
          f"{r.returncode} {r.stderr!r} {e.argv()!r}")
    check("красные: тревога с путём к логу и подписью",
          "x 1.2.0 не поставлен" in al and "x-1.2.0.log" in al and "FAIL новая ошибка" in al, al)
    check("красные: метка red на 1.2.0", e.marks().get("x", {}).get("result") == "red"
          and e.marks()["x"].get("version") == "1.2.0", e.marks())
    n = e.runs()
    r = e.run()
    check("красная версия повторно: тесты не гоняются, код 0, тревоги нет",
          r.returncode == 0 and e.runs() == n and n > 0 and e.alerts() == al and "plugin update" not in e.argv(),
          f"{r.returncode} {n} {e.runs()}")
    e.close()

    # Исключение в конце вывода — тоже новое падение
    e = Env("1.0.0", "1.2.0", OK, NEW_EXC)
    r = e.run()
    check("исключение в новой версии: красное с подписью «исключение KeyError»",
          r.returncode == 76 and "test_a.py: исключение KeyError" in e.alerts(), e.alerts())
    e.close()

    # Старое падение есть и у установленной версии (пути во временной папке разные) — база его гасит
    e = Env("1.0.0", "1.1.0", OLD_FAIL, OLD_FAIL)
    r = e.run()
    check("старое падение и у базы: update вызван, код 0",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), f"{r.returncode} {e.alerts()!r}")
    e.close()

    # Нет папки установленной версии — база пустая, старое падение уже красное
    e = Env("1.0.0", "1.1.0", OLD_FAIL, OLD_FAIL)
    shutil.rmtree(os.path.join(e.home, ".claude", "plugins", "cache"))
    r = e.run()
    check("без installPath база пустая: любое падение — красное", r.returncode == 76 and "plugin update" not in e.argv())
    e.close()

    # Каталог без known_marketplaces.json — запасной путь ~/.claude/plugins/marketplaces/agent-kit
    e = Env("1.0.0", "1.1.0", OK, OK, known=False)
    r = e.run()
    check("запасной путь каталога", r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), r.stderr)
    e.close()

    # Тесты зелёные, а update не удался — метка green, тревога один раз, тесты не повторяются
    e = Env("1.0.0", "1.1.0", OK, OK)
    r = e.run(extra={"STUB_UPD_RC": "1"})
    check("update упал: код 76, метка green", r.returncode == 76 and e.marks().get("x", {}).get("result") == "green",
          f"{r.returncode} {e.marks()}")
    check("update упал: отметки «нужен перезапуск» нет (metis-0181)",
          not os.path.exists(os.path.join(e.state, "plugins", "respawn.json")))
    n = e.runs()
    r = e.run(extra={"STUB_UPD_RC": "1"})
    check("update упал повторно: тесты не гоняются, update пробуется, тревога одна",
          r.returncode == 76 and e.runs() == n and e.argv().count("plugin update x@agent-kit") == 2
          and e.alerts().count("тесты прошли, но claude plugin update не поставил") == 1, e.alerts())
    r = e.run()
    check("update прошёл позже: обновлён, метка снята",
          r.returncode == 0 and "обновлён x 1.0.0 → 1.1.0" in e.alerts() and "x" not in e.marks() and e.runs() == n)
    e.close()

    # Метка green, а каталог той же версии изменился — тесты заново
    e = Env("1.0.0", "1.1.0", OK, OK)
    e.run(extra={"STUB_UPD_RC": "1"})
    n = e.runs()
    check("метка green хранит хеш проверенной копии", len(e.marks().get("x", {}).get("hash") or "") == 64, e.marks())
    e.write(os.path.join(e.src, "hooks", "new.py"), "print('другое содержимое')\n")
    r = e.run(extra={"STUB_UPD_RC": "1"})
    check("green, хеш каталога другой: тесты гоняются заново", e.runs() > n, f"{n} {e.runs()}")
    e.close()

    # Каталог не обновился (нет сети) — 75, дальше не идём
    e = Env("1.0.0", "1.1.0", OK, OK)
    r = e.run(extra={"STUB_MKT_RC": "1"})
    check("marketplace update упал: код 75, без тревоги и тестов",
          r.returncode == 75 and e.alerts() == "" and e.runs() == 0 and "plugin list" not in e.argv())
    e.close()

    # Второй запуск при занятой блокировке — сразу 0
    e = Env("1.0.0", "1.1.0", OK, OK)
    os.makedirs(os.path.join(e.state, "locks"))
    with open(os.path.join(e.state, "locks", "plugins-update.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        r = e.run()
    check("блокировка занята: код 0, claude не вызван", r.returncode == 0 and e.argv() == "")
    e.close()

    # Разбор команды тиком и подписи падений
    probe = f"""
import json, sys
sys.path.insert(0, {os.path.dirname(LIB)!r})
import pantheon as p
cmds = ["pantheon plugins update --quiet", "pantheon plugins update", "pantheon plugins foo",
        "pantheon plugins update --force", "pantheon plugins"]
sig = p._failure_signatures
print(json.dumps({{
  "cmds": {{c: p.parse_command(c) is not None for c in cmds}},
  "tmp": sig("t.py", "FAIL x " + p.tempfile.gettempdir() + "/abc/new/x/f.py\\n  FAIL y /private/tmp/q/z\\n", 1),
  "code": sig("t.py", "что-то\\n", 2), "ok": sig("t.py", "ok\\n", 0), "timeout": sig("t.py", "", None),
  "exc": sig("t.py", "FAIL a\\nTraceback (most recent call last):\\n  File \\"t.py\\", line 1\\nValueError: b\\n", 1),
  "ansi": sig("t.py", "\\x1b[31mFAIL c\\x1b[0m\\n", 1), "killed": sig("t.py", "FAIL d\\n", -9),
  "newer": [p._version_newer("0.11.10", "0.11.9"), p._version_newer("1.0", "1.0"), p._version_newer("1.0-rc", "1.0")],
}}))
"""
    r = subprocess.run([PY, "-I", "-c", probe], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(r.stdout)
    except ValueError:
        got = {}
        print(r.stderr)
    cmds = got.get("cmds", {})
    check("parse_command пропускает pantheon plugins update [--quiet]",
          cmds.get("pantheon plugins update --quiet") and cmds.get("pantheon plugins update"), cmds)
    check("parse_command не пропускает plugins foo, plugins, update с другим флагом",
          cmds and not any(cmds[c] for c in ("pantheon plugins foo", "pantheon plugins update --force",
                                              "pantheon plugins")), cmds)
    check("подписи: временные пути → <tmp>", got.get("tmp") == ["FAIL x <tmp>", "FAIL y <tmp>", "t.py: код 1"],
          got.get("tmp"))
    check("подписи: код без FAIL, зелёный файл, таймаут",
          got.get("code") == ["t.py: код 2"] and got.get("ok") == [] and got.get("timeout") == ["t.py: таймаут"],
          got)
    check("подписи: FAIL, исключение в конце и код", got.get("exc") == ["FAIL a", "t.py: исключение ValueError",
                                                                        "t.py: код 1"], got.get("exc"))
    check("подписи: ANSI вырезан, код при FAIL — всегда",
          got.get("ansi") == ["FAIL c", "t.py: код 1"] and got.get("killed") == ["FAIL d", "t.py: код -9"], got)
    check("версии: числа, равные, не разобрать", got.get("newer") == [True, False, True], got.get("newer"))
    # База не досчитана: файл базы кончился таймаутом или сроком прогона — падение новой версии в нём остаётся
    # падением; интерпретаторы: тесты pantheon только 3.11+, guard — на всех
    probe2 = f"""
import json, sys, collections
sys.path.insert(0, {os.path.dirname(LIB)!r})
import pantheon as p
C = collections.Counter
new = C({{("py", "t.py", "t.py: таймаут"): 1, ("py", "t.py", "FAIL x"): 1, ("py", "u.py", "FAIL old"): 1,
         ("py", "v.py", "v.py: срок прогона"): 1}})
base = C({{("py", "t.py", "t.py: срок прогона"): 1, ("py", "t.py", "FAIL x"): 1, ("py", "u.py", "FAIL old"): 1}})
fresh, unk = p._fresh_failures(new, base)
clean, unk2 = p._fresh_failures(C({{("py", "u.py", "FAIL old"): 1}}), C({{("py", "u.py", "FAIL old"): 1}}))
p._test_pythons = lambda: [sys.executable, "/old/python3"]
p._py_ge311 = lambda py: py == sys.executable
print(json.dumps({{"fresh": sorted(k[1] + "|" + k[2] for k in fresh), "unk": sorted(unk), "clean": sorted(clean),
                  "clean_unk": sorted(unk2), "pan": p._pythons_for("pantheon") == [sys.executable],
                  "guard": p._pythons_for("guard") == [sys.executable, "/old/python3"]}}))
"""
    r = subprocess.run([PY, "-I", "-c", probe2], capture_output=True, text=True, timeout=60)
    try:
        g2 = json.loads(r.stdout)
    except ValueError:
        g2 = {}
        print(r.stderr)
    check("база не досчитана: таймаут новой и её FAIL в файле, где база не дошла до конца, остаются новыми падениями",
          g2.get("fresh") == ["t.py|FAIL x", "t.py|t.py: таймаут", "v.py|v.py: срок прогона"]
          and g2.get("unk") == [["py", "t.py"]], g2)
    check("база дошла до конца: то же падение в обеих версиях — не новое", g2.get("clean") == [] and
          g2.get("clean_unk") == [], g2)
    check("интерпретаторы: pantheon — только 3.11+, guard — все", g2.get("pan") and g2.get("guard"), g2)
    r = subprocess.run([PY, "-I", LIB, "plugins", "foo"], capture_output=True, text=True, timeout=60)
    check("pantheon plugins foo — код 2", r.returncode == 2)

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
