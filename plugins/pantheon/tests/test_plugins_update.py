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

OK = 'print("ok")\nprint("1 из 1 прошли")\n'  # с итогом: файл без итога (код 0, ok) база сверяет (metis-0361)
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
             '    print("FAIL цвет включён")\n    raise SystemExit(1)\nprint("ok   цвет выключен")\nprint("1 из 1 прошли")\n')


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
        return self.py("P.verified_write(sys.argv[2], sys.argv[3], P._tree_hash(sys.argv[3]), '?', 'test')", self.name, d)

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
    ltxt = open(log).read() if os.path.exists(log) else ""
    check("зелёные: в логе прогон новой версии и строка «база 1.0.0 … не гоняются» (базу не гоняли), helper.py не гонялся",
          "===== новая 1.1.0 · " in ltxt and "===== база 1.0.0 · " not in ltxt
          and "база 1.0.0: " in ltxt and "не гоняются" in ltxt and "helper.py" not in ltxt, ltxt[-300:])
    check("зелёные: временные копии убраны (своя TMPDIR и STATE/plugins/tmp пусты)", e.leftovers() == [],
          e.leftovers())
    check("зелёные: без критической тревоги (хеш кэша с .in_use совпал с проверенной копией)",
          "КРИТИЧНО" not in e.alerts() and e.notified() == "")
    e.close()

    # Подпроцесс тестов получает TMPDIR внутри временной папки прогона (STATE/plugins/tmp), а не общий
    # падение у обеих версий одинаковое: база гоняется (metis-0358) и тоже пишет свой TMPDIR
    e = Env("1.0.0", "1.1.0", REC_TMPDIR + OLD_FAIL_RC, REC_TMPDIR + OLD_FAIL_RC)
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
    log = os.path.join(e.state, "plugins", "x-1.1.0.log")
    text = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
    check("старое падение и у базы: база гонялась по упавшему файлу на каждом python (прогонов базы столько же)",
          e.runs() >= 2 and text.count("===== база 1.0.0 · ") == text.count("===== новая 1.1.0 · ") == e.runs() // 2,
          f"{e.runs()} {text[-400:]!r}")
    e.close()

    # metis-0358: новая чиста — база не гоняется (раньше шла по всем файлам и не успевала в срок прогона)
    e = Env("1.0.0", "1.1.0", OLD_FAIL, OK)
    r = e.run()
    log = os.path.join(e.state, "plugins", "x-1.1.0.log")
    text = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
    check("новая чиста: база не гоняется ни на одном python, update вызван, в логе — сколько файлов базы пропущено",
          r.returncode == 0 and e.runs() == text.count("===== новая 1.1.0 · ") > 0
          and "===== база 1.0.0 · " not in text and "plugin update x@agent-kit" in e.argv()
          and f"база 1.0.0: {e.runs()} файл(ов) не гоняются" in text,
          f"{r.returncode} {e.runs()} {text[-400:]!r}")
    e.close()

    # metis-0358: два файла, у новой упал один; база — только по нему, а срок базы — остаток после новой версии.
    # Подпроцесс подменён: новая «тратит» 1700 из 1800 с, базе остаётся 100 с, одинаковое падение гасится.
    e = Env("1.0.0", "1.1.0", OLD_FAIL_RC, OLD_FAIL_RC)
    base = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "x", "1.0.0")
    for d in (e.src, base):
        e.write(os.path.join(d, "tests", "test_b.py"), OK)
    got = e.py("""import json, os, subprocess, time
clock = [1000.0]
P.time.monotonic = lambda: clock[0]
P._pythons_for = lambda name: ["py"]
seen = []
real = subprocess.run
def fake(cmd, cwd=None, timeout=None, **kw):
    if cmd[0] == "git":  # git init/add/commit копии-клона (metis-0368) — настоящий, это не прогон тестов
        return real(cmd, cwd=cwd, timeout=timeout, **kw)
    who = "new" if "/new/" in cwd else "base"
    f = cmd[-1].split("/")[-1]
    seen.append([who, f, round(timeout)])
    if who == "new" and f == "test_a.py":
        clock[0] += 1700
    if f == "test_a.py":
        return subprocess.CompletedProcess(cmd, 1, stdout=b"FAIL old\\n")
    return subprocess.CompletedProcess(cmd, 0, stdout="ok\\n1 из 1 прошли\\n".encode())
P.subprocess.run = fake
os.makedirs(P.path("plugins", "tmp"), exist_ok=True)
log, digest, fresh = P._plugin_check("x", "1.0.0", "1.1.0", sys.argv[2], sys.argv[3], {})
print(json.dumps({"seen": seen, "fresh": sorted(k[2] for k in fresh)}))""", e.src, base)
    try:
        g = json.loads(got[-1])
    except (ValueError, IndexError):
        g = {}
    check("база только по упавшему у новой файлу: test_b (чистый у новой) у базы не гоняется",
          [x[:2] for x in g.get("seen", [])] == [["new", "test_a.py"], ["new", "test_b.py"], ["base", "test_a.py"]],
          got)
    check("срок базы — остаток после новой: 1800 − 1700 = 100 с, одинаковое падение базой погашено",
          g.get("seen", [[0, 0, 0]] * 3)[-1][2] == 100 and g.get("fresh") == [], got)
    e.close()

    # metis-0368: копия — как клон agent-kit: рядом соседний guard (у новой — из каталога, у базы — установленный),
    # .claude-plugin/marketplace.json в корне, корень — git-репозиторий с коммитом (всё закоммичено). Тест в копии
    # пишет, что видит; обе версии падают одинаково, чтобы база тоже гонялась. Хеш — только дерево x: update встал
    SEE_PEERS = (
        'import json, os, subprocess\n'
        'here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n'
        'root = os.path.dirname(os.path.dirname(here))\n'
        'g = os.path.join(here, "..", "guard", "marker.txt")\n'
        'git = lambda *a: subprocess.run(["git", "-C", here, *a], capture_output=True, text=True)\n'
        'top = git("rev-parse", "--show-toplevel").stdout.strip()\n'
        'rec = {"who": os.path.basename(root), "guard": open(g).read() if os.path.exists(g) else None,\n'
        '       "top": bool(top) and os.path.realpath(top) == os.path.realpath(root),\n'
        '       "commit": git("log", "--oneline").stdout.count("\\n") == 1,\n'
        '       "clean": git("status", "--porcelain").returncode == 0 and git("status", "--porcelain").stdout == "",\n'
        '       "mkt": os.path.isfile(os.path.join(root, ".claude-plugin", "marketplace.json"))}\n'
        'open(os.environ["REC_FILE"], "a").write(json.dumps(rec, sort_keys=True) + "\\n")\n'
        'print("FAIL окружение копии")\nraise SystemExit(1)\n')
    e = Env("1.0.0", "1.1.0", SEE_PEERS, SEE_PEERS)
    mkt = os.path.dirname(os.path.dirname(e.src))
    gcat = os.path.join(mkt, "plugins", "guard")
    gcache = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "guard", "3.0.0")
    for d, mark in ((gcat, "каталог"), (gcache, "установлен")):
        e.write(os.path.join(d, ".claude-plugin", "plugin.json"), json.dumps({"name": "guard", "version": "3.0.0"}))
        e.write(os.path.join(d, "marker.txt"), mark)
    e.write(os.path.join(mkt, ".claude-plugin", "marketplace.json"),
            json.dumps({"name": "agent-kit", "plugins": [{"name": "x", "source": "./plugins/x"},
                                                        {"name": "guard", "source": "./plugins/guard"}]}))
    grow = {"id": "guard@agent-kit", "version": "3.0.0", "scope": "user", "installPath": gcache}
    for f in ("list.json", "list-after.json"):
        p = os.path.join(e.stub, f)
        e.write(p, json.dumps(json.load(open(p)) + [grow]))
    rec = os.path.join(e.tmp, "peers.rec")
    r = e.run(extra={"REC_FILE": rec})
    seen = [json.loads(ln) for ln in open(rec, encoding="utf-8")] if os.path.exists(rec) else []
    want = {"new": "каталог", "base": "установлен"}
    check("0368: копия с соседом — у новой guard из каталога, у базы установленный",
          sorted({(s["who"], s["guard"]) for s in seen}) == sorted(want.items()), seen)
    check("0368: копия — git-репозиторий с одним коммитом, всё закоммичено, marketplace.json в корне",
          len(seen) >= 2 and all(s["top"] and s["commit"] and s["clean"] and s["mkt"] for s in seen), seen)
    check("0368: хеш — только дерево x: одинаковое падение обеих погашено, update встал на проверенное",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv() and "plugin update guard" not in e.argv()
          and "обновлён x 1.0.0 → 1.1.0" in e.alerts(), f"{r.returncode} {e.alerts()[-300:]!r}")
    e.close()

    # metis-0369 п.2: установленный сосед с installPath, папки которого нет, берётся из каталога (как неустановленный)
    # metis-0362 (ревью 112, M7): installPath, указывающий на файл, а не на папку, — то же, что отсутствующая папка
    for what in ("нет папки", "файл вместо папки"):
        e = Env("1.0.0", "1.1.0", SEE_PEERS, SEE_PEERS)
        mkt = os.path.dirname(os.path.dirname(e.src))
        gcat = os.path.join(mkt, "plugins", "guard")
        e.write(os.path.join(gcat, ".claude-plugin", "plugin.json"), json.dumps({"name": "guard", "version": "3.0.0"}))
        e.write(os.path.join(gcat, "marker.txt"), "каталог")
        e.write(os.path.join(mkt, ".claude-plugin", "marketplace.json"),
                json.dumps({"name": "agent-kit", "plugins": [{"name": "x", "source": "./plugins/x"},
                                                            {"name": "guard", "source": "./plugins/guard"}]}))
        ghost = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "guard", "ghost")  # папки нет
        if what == "файл вместо папки":
            e.write(ghost, "не папка")
        grow = {"id": "guard@agent-kit", "version": "3.0.0", "scope": "user", "installPath": ghost}
        for f in ("list.json", "list-after.json"):
            p = os.path.join(e.stub, f)
            e.write(p, json.dumps(json.load(open(p)) + [grow]))
        rec = os.path.join(e.tmp, "peers.rec")
        e.run(extra={"REC_FILE": rec})
        seen = [json.loads(ln) for ln in open(rec, encoding="utf-8")] if os.path.exists(rec) else []
        check(f"0369 п.2 ({what}): сосед базы с таким installPath — у базы guard из каталога",
              sorted({(s["who"], s["guard"]) for s in seen}) == [("base", "каталог"), ("new", "каталог")], seen)
        e.close()

    # metis-0369 п.1: git не работает в копиях (заглушка в PATH падает) и тесты падают одинаково у обеих версий —
    # база это не гасит: красное «копия новой версии не собралась» с причиной в логе и в тревоге, update не вызван
    e = Env("1.0.0", "1.1.0", 'print("FAIL env")\nraise SystemExit(1)\n', 'print("FAIL env")\nraise SystemExit(1)\n')
    e.write(os.path.join(e.stub, "git"), '#!/bin/sh\necho "fatal: git сломан в копии" >&2\nexit 128\n')
    os.chmod(os.path.join(e.stub, "git"), 0o755)
    r = e.run()
    lg = open(os.path.join(e.state, "plugins", "x-1.1.0.log"), encoding="utf-8").read()
    check("0369 п.1: git упал в обеих копиях — красное без вычитания базой, update не вызван",
          r.returncode == 76 and "plugin update" not in e.argv(), f"{r.returncode} {lg[-400:]!r}")
    check("0369 п.1: причина в логе (копия новой, git init, текст ошибки) и в тревоге",
          "копия новой версии не собралась: git init: код 128" in lg and "git сломан в копии" in lg
          and "копия новой версии не собралась" in e.alerts(), f"{lg[-400:]!r} {e.alerts()[-300:]!r}")
    e.close()
    # сосед новой версии не собрался (папки нет) — тоже красное: _plugin_check напрямую
    e = Env("1.0.0", "1.1.0", 'print("ok a")\nprint("1 из 1 прошли")\n', 'print("ok a")\nprint("1 из 1 прошли")\n')
    got = e.py("""
import json, os
P._pythons_for = lambda name: [sys.executable]
os.makedirs(P.path("plugins", "tmp"), exist_ok=True)
log, digest, fresh = P._plugin_check("x", "1.0.0", "1.1.0", sys.argv[2], sys.argv[3], {},
                                     peers_new={"guard": "/нет/такой/папки"})
print(json.dumps(sorted(k[2] for k in fresh), ensure_ascii=False))""", e.src, os.path.dirname(e.after) + "/1.0.0")
    check("0369 п.1: сосед новой версии без папки — красное «копия новой версии не собралась: сосед guard»",
          bool(got) and "копия новой версии не собралась: сосед guard: нет папки" in got[-1], got)
    e.close()

    # metis-0360: подписи не гасят настоящие поломки (ревью 0358, второй argus). fresh_of — новые падения из лога.
    def log_of(e, ver="1.1.0"):
        p = os.path.join(e.state, "plugins", f"x-{ver}.log")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    def fresh_of(e, ver="1.1.0"):
        text = log_of(e, ver)
        return text.split("===== новых падений:")[-1] if "===== новых падений:" in text else ""

    # п.1: база красная (FAIL окружения, код 1, есть итог), новая молча обрывается кодом 1 после первой проверки —
    # общие с базой «FAIL env» и «код 1» не прячут оборванный остаток: «нет итоговой строки»; с итогом, но проверок
    # меньше, чем у базы, — «проверок меньше»; та же картина у обеих — по-прежнему гасится (мутант: без сравнения)
    BASE_RED = 'print("ok   a")\nprint("FAIL env — нет соседа")\nprint("ok   b")\nprint("2 из 3 прошли")\nraise SystemExit(1)\n'
    NEW_CUT = 'print("ok   a")\nprint("FAIL env — нет соседа", flush=True)\nimport sys\nsys.exit(1)\n'
    NEW_FEWER = 'print("ok   a")\nprint("FAIL env — нет соседа")\nprint("1 из 2 прошли")\nraise SystemExit(1)\n'
    for what, body, want in (("обрыв без итога", NEW_CUT, "test_a.py: нет итоговой строки"),
                             ("итог есть, проверок меньше", NEW_FEWER, "test_a.py: проверок меньше, чем у базы (1 < 2)"),
                             ("как у базы", BASE_RED, None)):
        e = Env("1.0.0", "1.1.0", BASE_RED, body)
        r = e.run()
        fr = fresh_of(e)
        if want:
            check(f"0360 п.1, {what}: база красная в том же файле — новая всё равно красная",
                  r.returncode == 76 and "plugin update" not in e.argv() and want in fr and "FAIL env" not in fr,
                  f"{r.returncode} {fr!r}")
        else:
            check(f"0360 п.1, {what}: то же падение, те же проверки — база гасит, update вызван",
                  r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), f"{r.returncode} {fr!r}")
        e.close()

    # п.2: исключение сравнивается с текстом сообщения — FileNotFoundError окружения у базы не гасит другой
    # FileNotFoundError новой; тот же текст с другим временным путём — гасит (мутант: подпись только по типу)
    BASE_FNF = 'import os\nraise FileNotFoundError("нет соседнего guard: " + os.path.abspath(__file__))\n'
    NEW_FNF = 'import os\nopen(os.path.join(os.path.dirname(os.path.abspath(__file__)), "нет-файла.json"))\n'
    e = Env("1.0.0", "1.1.0", BASE_FNF, NEW_FNF)
    r = e.run()
    fr = fresh_of(e)
    check("0360 п.2: другой FileNotFoundError у новой — не гасится FileNotFoundError базы",
          r.returncode == 76 and "исключение FileNotFoundError: [Errno 2] No such file or directory: "
          "'<tmp>/…/<copy>/plugins/x/tests/нет-файла.json'" in fr, f"{r.returncode} {fr!r}")
    e.close()
    e = Env("1.0.0", "1.1.0", BASE_FNF, BASE_FNF)
    r = e.run()
    check("0360 п.2: то же исключение с тем же текстом (пути во временной папке разные) — база гасит",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), f"{r.returncode} {fresh_of(e)!r}")
    e.close()

    # п.4: файл тестов ничего не проверил (код 0, ни ok, ни FAIL, ни итога) — красное, и база это не гасит, даже
    # пустая так же; базу ради такого файла не гоняем (мутант: без NO_CHECKS)
    e = Env("1.0.0", "1.1.0", "", "")
    r = e.run()
    fr = fresh_of(e)
    check("0360 п.4: пустой файл тестов — красное «ни одной проверки», база его не гасит и не гоняется",
          r.returncode == 76 and "test_a.py: ни одной проверки" in fr and "===== база 1.0.0 ·" not in log_of(e),
          f"{r.returncode} {fr!r}")
    e.close()

    # Ревью 0359 (второй argus). п.1: FileNotFoundError на разных файлах во временной папке — разные подписи: путь
    # внутри копии и имя файла остаются, корень копии (new/ и base/) и случайные папки — нет (мутант: путь целиком
    # в <tmp>); тот же файл у обеих — гасится (выше, BASE_FNF)
    def open_in_copy(rel):
        return ("import os\nhere = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
                f"open(os.path.join(here, {rel!r}))\n")
    e = Env("1.0.0", "1.1.0", open_in_copy("README.md"), open_in_copy("lib/rules.toml"))
    r = e.run()
    fr = fresh_of(e)
    check("0359b п.1: FileNotFoundError на другом файле в tmp — не гасится базой, путь внутри копии в подписи",
          r.returncode == 76 and "No such file or directory: '<tmp>/…/<copy>/plugins/x/lib/rules.toml'" in fr
          and "README.md" not in fr, f"{r.returncode} {fr!r}")
    e.close()
    e = Env("1.0.0", "1.1.0", open_in_copy("README.md"), open_in_copy("README.md"))
    r = e.run()
    check("0359b п.1: тот же отсутствующий файл в своей копии у обеих — база гасит",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), f"{r.returncode} {fresh_of(e)!r}")
    e.close()

    # п.2: итог с нулём проверок («0 из 0 прошли», «тестов: 0, …») при коде 0 — тоже «ни одной проверки»
    # (мутант: итог с нулём считается итогом)
    for body in ('print("0 из 0 прошли")\n', 'print("тестов: 0, не прошло: 0")\n'):
        e = Env("1.0.0", "1.1.0", body, body)
        r = e.run()
        fr = fresh_of(e)
        check(f"0359b п.2: итог «{body[7:-3]}» без проверок — красное «ни одной проверки»",
              r.returncode == 76 and "test_a.py: ни одной проверки" in fr, f"{r.returncode} {fr!r}")
        e.close()

    # п.3: файл без строк ok (как test_svc_ondemand) — число проверок из итога: база красная «38 из 39», новая
    # с той же строкой провала и «12 из 13» — «проверок меньше по итогу» (мутант: сравнение только строк ok)
    NOOK_BASE = 'print("НЕ ПРОШЁЛ: env")\nprint("38 из 39 прошли")\nraise SystemExit(1)\n'
    NOOK_NEW = 'print("НЕ ПРОШЁЛ: env")\nprint("12 из 13 прошли")\nraise SystemExit(1)\n'
    e = Env("1.0.0", "1.1.0", NOOK_BASE, NOOK_NEW)
    r = e.run()
    fr = fresh_of(e)
    check("0359b п.3: без строк ok, итог 13 < 39 у базы — красное «проверок меньше по итогу»",
          r.returncode == 76 and "test_a.py: проверок меньше, чем у базы (по итогу 13 < 39)" in fr
          and "НЕ ПРОШЁЛ" not in fr, f"{r.returncode} {fr!r}")
    e.close()
    e = Env("1.0.0", "1.1.0", NOOK_BASE, NOOK_BASE)
    r = e.run()
    check("0359b п.3: без строк ok, итог как у базы — база гасит",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), f"{r.returncode} {fresh_of(e)!r}")
    e.close()

    # п.4: итог — только последняя строка. Новая дописала проверки, деталь FAIL несёт «2/3» из вывода ребёнка, затем
    # молчаливый обрыв: «2/3» в середине (мутант: итог в любой строке) или последней строкой при 6 строках ok
    # (мутант: без сверки N итога с числом ok) — «нет итоговой строки»
    G_BASE = ('print("ok   a")\nprint("FAIL env — вывод:\\n2/3")\nfor i in range(5): print(f"ok   x{i}")\n'
              'print("6 из 7 прошли")\nraise SystemExit(1)\n')
    for what, tail in (("в середине", 'print("ok   b", flush=True)\n'), ("последней строкой", "")):
        body = ('for i in range(4): print(f"ok   n{i}")\nprint("ok   a")\nprint("FAIL env — вывод:\\n2/3")\n'
                + tail + 'import sys\nsys.stdout.flush()\nimport os\nos._exit(1)\n')
        if not tail:
            body = 'print("ok   n4")\n' + body
        e = Env("1.0.0", "1.1.0", G_BASE, body)
        r = e.run()
        fr = fresh_of(e)
        check(f"0359b п.4: «2/3» из детали FAIL {what}, обрыв, строк ok столько же — красное «нет итоговой строки»",
              r.returncode == 76 and "test_a.py: нет итоговой строки" in fr and "проверок меньше" not in fr,
              f"{r.returncode} {fr!r}")
        e.close()

    # Ревью 0359 (первый argus): «НЕ ПРОШЛО» / «НЕ ПРОШЁЛ» / «ОШИБКА:» — строки провала, как FAIL: база с провалом
    # окружения в том же файле не гасит новый провал (мутант: только FAIL)
    NP_BASE = 'print("НЕ ПРОШЛО: env")\nprint("тестов: 5, не прошло: 1")\nraise SystemExit(1)\n'
    for line in ("НЕ ПРОШЛО: новое", "НЕ ПРОШЁЛ: новое", "ОШИБКА: test_x KeyError 'k'"):
        e = Env("1.0.0", "1.1.0", NP_BASE,
                f'print("НЕ ПРОШЛО: env")\nprint({line!r})\nprint("тестов: 5, не прошло: 2")\nraise SystemExit(1)\n')
        r = e.run()
        fr = fresh_of(e)
        check(f"0359b: строка «{line.split(':')[0]}» — подпись провала, база с другим провалом её не гасит",
              r.returncode == 76 and line in fr and "НЕ ПРОШЛО: env" not in fr, f"{r.returncode} {fr!r}")
        e.close()
    # деталь в той же строке: изменчивое (pid, порты, время) в подписи — N, тот же провал окружения с другими pid
    # и временем у базы гасится (мутант: без _VOLATILE — тик держал бы обновление на каждом флаке keep-alive)
    KA = ('print("НЕ ПРОШЁЛ: keep-alive ответов 10 из ≥11, [{}, {}] pid {} в {} 127.0.0.1:{}")\n'
          'print("38 из 39 прошли")\nraise SystemExit(1)\n')
    e = Env("1.0.0", "1.1.0", KA.format(40600, 40601, 812, "12:01:02.5", 52311),
            KA.format(308, 567, 97, "2026-10-22T13:45:12+03:00", 60001))
    r = e.run()
    check("0359b: «НЕ ПРОШЁЛ» с другими pid, портом и временем — тот же провал, база гасит",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), f"{r.returncode} {fresh_of(e)!r}")
    e.close()
    # Круг 3, п.1: номер и значение проверки не N — соседние проверки цикла test_night/test_watch («запас +0» и
    # «запас +4», «ответ в 23:10» и «в 22:30», «сбой 1» и «сбой 3») — разные подписи: провал базы в одной не гасит
    # провал новой в другой (мутант: все числа — N). Счётчик в детали тоже остаётся: флак с другим счётчиком — красное
    SUMN = 'print("тестов: 40, не прошло: 1")\nraise SystemExit(1)\n'
    for was, now in (("запас +0: бюджет 2.5, ждали 3", "запас +4: бюджет 2.5, ждали 3"),
                     ("ответ в 23:10 — opened_at None", "ответ в 22:30 — opened_at None"),
                     ("сбой 1 не засчитан: {'fails': 0}", "сбой 3 не засчитан: {'fails': 0}"),
                     ("keep-alive ответов 10 из ≥11", "keep-alive ответов 9 из ≥11")):
        e = Env("1.0.0", "1.1.0", f"print('НЕ ПРОШЛО:', {was!r})\n" + SUMN, f"print('НЕ ПРОШЛО:', {now!r})\n" + SUMN)
        r = e.run()
        fr = fresh_of(e)
        check(f"0359 круг 3 п.1: «{was}» у базы не гасит «{now}» у новой",
              r.returncode == 76 and f"НЕ ПРОШЛО: {now}" in fr and was not in fr, f"{r.returncode} {fr!r}")
        e.close()

    # Круг 3, п.2: итог без числа проверок («OK 0», старый test_mmv) при коде 0 и без строк ok — «ни одной проверки»
    # (мутант: только итог с нулём); test_mmv печатает «тестов: N, не прошло: K» — число проверок видно, пропуск
    # проверок при том же провале окружения — «проверок меньше по итогу»
    e = Env("1.0.0", "1.1.0", 'print("OK", 0)\n', 'print("OK", 0)\n')
    r = e.run()
    fr = fresh_of(e)
    check("0359 круг 3 п.2: код 0, «OK 0», ни строки ok — красное «ни одной проверки»",
          r.returncode == 76 and "test_a.py: ни одной проверки" in fr, f"{r.returncode} {fr!r}")
    e.close()
    MMV = 'print("НЕ ПРОШЛО: CLI mmv: 1")\nprint("тестов: {}, не прошло: 1")\nraise SystemExit(1)\n'
    e = Env("1.0.0", "1.1.0", MMV.format(27), MMV.format(2))
    r = e.run()
    fr = fresh_of(e)
    check("0359 круг 3 п.2: итог «тестов: 2» против «тестов: 27» у базы — красное «проверок меньше по итогу»",
          r.returncode == 76 and "test_a.py: проверок меньше, чем у базы (по итогу 2 < 27)" in fr, f"{r.returncode} {fr!r}")
    e.close()
    r = subprocess.run([PY, "-I", os.path.join(ROOT, "tests", "test_mmv.py")], stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
    mmv = subprocess.run([PY, "-I", "-c", f"import sys; sys.path.insert(0, {os.path.dirname(LIB)!r}); import pantheon as p;"
                          "print(p._ok_count(sys.stdin.read())[1])"], input=r.stdout, capture_output=True, text=True,
                         timeout=60).stdout.strip()
    check("0359 круг 3 п.2: настоящий test_mmv.py — итог с числом проверок",
          r.returncode == 0 and mmv.isdigit() and int(mmv) > 20, f"{r.returncode} {mmv!r} {r.stdout[-300:]}")

    # Круг 3, п.4: файл без строк ok, деталь «НЕ ПРОШЁЛ» несёт «39/39» последней строкой, затем молчаливый обрыв —
    # «все прошли» при строке провала не итог: «нет итоговой строки» (мутант: без этой сверки — зелёное)
    e = Env("1.0.0", "1.1.0", 'print("НЕ ПРОШЁЛ: keep-alive x")\nprint("38 из 39 прошли")\nraise SystemExit(1)\n',
            'print("НЕ ПРОШЁЛ: keep-alive x\\n39/39", flush=True)\nimport os\nos._exit(1)\n')
    r = e.run()
    fr = fresh_of(e)
    check("0359 круг 3 п.4: «39/39» из детали провала последней строкой — красное «нет итоговой строки»",
          r.returncode == 76 and "test_a.py: нет итоговой строки" in fr, f"{r.returncode} {fr!r}")
    e.close()

    # metis-0361: код 0, несколько ok и ни строки итога. Пять файлов agent-kit так кончаются законно, поэтому базу
    # по такому файлу гоняем и сверяем. Проба D: новая оборвалась (sys.exit(0) в проверяемом коде) раньше базы —
    # красное «проверок меньше» (мутант: файл без итога не идёт к базе); итог у базы был, у новой пропал — «оборвался
    # без итога»; у базы файла нет — то же; тот же стиль без итога и столько же ok — зелёное, причина — в логе
    BARE = "код 0, строки ok и ни строки итога — оборвался без итога"
    OK5 = "".join(f'print("ok   n{i}")\n' for i in range(5))
    e = Env("1.0.0", "1.1.0", OK5, 'print("ok   n0")\nprint("ok   n1")\nprint("ok   n2", flush=True)\nimport sys\nsys.exit(0)\n')
    r = e.run()
    fr = fresh_of(e)
    check("0361 проба D: код 0, три ok из пяти у базы, обрыв без итога — красное «проверок меньше», причина в логе",
          r.returncode == 76 and "test_a.py: проверок меньше, чем у базы (3 < 5)" in fr
          and "проверок меньше, чем у базы (3 < 5)" in log_of(e), f"{r.returncode} {fr!r}")
    e.close()
    e = Env("1.0.0", "1.1.0", OK5 + 'print("5 из 5 прошли")\n', OK5)
    r = e.run()
    fr = fresh_of(e)
    check("0361: итог у базы был, у новой нет (код 0, ok столько же) — красное «оборвался без итога», причина в логе",
          r.returncode == 76 and "test_a.py: " + BARE + " (у базы итог был)" in fr
          and "оборвался без итога (у базы итог был)" in log_of(e), f"{r.returncode} {fr!r}")
    e.close()
    e = Env("1.0.0", "1.1.0", None, OK5)
    r = e.run()
    fr = fresh_of(e)
    check("0361: у базы такого файла нет — красное «оборвался без итога (у базы такого файла нет)»",
          r.returncode == 76 and "test_a.py: " + BARE + " (у базы такого файла нет)" in fr, f"{r.returncode} {fr!r}")
    e.close()
    e = Env("1.0.0", "1.1.0", OK5, OK5)
    r = e.run()
    check("0361: тот же стиль без итога, столько же ok — зелёное, update вызван",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), f"{r.returncode} {fresh_of(e)!r}")
    e.close()
    e = Env("1.0.0", "1.1.0", OK5, OK5 + 'print("5 из 5 прошли")\n')
    r = e.run()
    check("0361: у новой итог есть — зелёное", r.returncode == 0 and "plugin update x@agent-kit" in e.argv(),
          f"{r.returncode} {fresh_of(e)!r}")
    e.close()

    # Ревью 115, п.1: «тот же стиль без итога» — только если и база кончилась кодом 0. База, которая упала (код не 0,
    # FAIL, Traceback), — красное «у базы файл упал» (мутант: упавшая база = тот же стиль — зелёное)
    OK2 = "".join(f'print("ok   n{i}")\n' for i in range(2))
    OK4 = "".join(f'print("ok   n{i}")\n' for i in range(4))
    for name, base in (("P1 os._exit(1)", OK2 + 'import os, sys\nsys.stdout.flush()\nos._exit(1)\n'),
                       ("P1b FAIL и код 1", OK2 + 'print("FAIL env")\nraise SystemExit(1)\n'),
                       ("P1c Traceback", OK2 + 'raise KeyError("env")\n')):
        e = Env("1.0.0", "1.1.0", base, OK4 + 'import sys\nsys.exit(0)\n')
        r = e.run()
        fr = fresh_of(e)
        check(f"115 {name}: база упала, новая без итога с большим числом ok — красное «у базы файл упал»",
              r.returncode == 76 and "test_a.py: " + BARE + " (у базы файл упал)" in fr
              and "plugin update" not in e.argv(), f"{r.returncode} {fr!r}")
        e.close()
    # Ревью 115, M10: последняя строка базы «2/3» при трёх строках ok — деталь, а не итог; «нет итога» базы с пояснением
    # не гасит молчаливый обрыв новой (мутант: _summary_of отдаёт why=None в этой ветке — зелёное)
    e = Env("1.0.0", "1.1.0", 'print("ok   a")\nprint("ok   b")\nprint("ok   c")\nprint("2/3")\nraise SystemExit(1)\n',
            'print("ok   a")\nprint("ok   b")\nprint("ok   c", flush=True)\nimport os\nos._exit(1)\n')
    r = e.run()
    fr = fresh_of(e)
    check("115 M10: у базы «2/3» при трёх ok — не итог, обрыв новой — красное «нет итоговой строки»",
          r.returncode == 76 and "test_a.py: нет итоговой строки" in fr, f"{r.returncode} {fr!r}")
    e.close()
    # Ревью 115, п.3: голое «N/M» у файла без строк ok и без строки провала — не итог (P11: деталь «38/39» ребёнка при
    # коде 0; мутант: правило снова требует строку провала — зелёное)
    e = Env("1.0.0", "1.1.0", 'print("тестов: 40, не прошло: 0")\n', 'print("ребёнок:")\nprint("38/39")\n')
    r = e.run()
    fr = fresh_of(e)
    check("115 P11: без строк ok деталь «38/39» при коде 0 — не итог, красное «ни одной проверки»",
          r.returncode == 76 and "test_a.py: ни одной проверки" in fr, f"{r.returncode} {fr!r}")
    e.close()

    # metis-0362, R1: «M/M» после строки провала у базы — не итог; её «нет итоговой строки» не должна гасить молчаливый
    # обрыв новой с теми же ok (мутант: подпись без пояснения — зелёное)
    e = Env("1.0.0", "1.1.0",
            'print("ok   a")\nprint("НЕ ПРОШЛО: лимит 3600")\nprint("ok   b")\nprint("2/2")\nraise SystemExit(1)\n',
            'print("ok   a")\nprint("ok   b", flush=True)\nimport os\nos._exit(1)\n')
    r = e.run()
    fr = fresh_of(e)
    check("0362 R1: «нет итога» у базы (2/2 после провала) не гасит обрыв новой — красное «нет итоговой строки»",
          r.returncode == 76 and "test_a.py: нет итоговой строки" in fr and "деталь провала" not in fr,
          f"{r.returncode} {fr!r}")
    e.close()
    # «38/39» из детали — не итог, даже если у базы настоящий итог «38 из 39 прошли» (S1b; мутант: без правила
    # голого N/M — зелёное); настоящий итог «N из M прошли» без строк ok по-прежнему итог
    e = Env("1.0.0", "1.1.0", 'print("НЕ ПРОШЁЛ: x")\nprint("38 из 39 прошли")\nraise SystemExit(1)\n',
            'print("НЕ ПРОШЁЛ: x\\n38/39", flush=True)\nimport os\nos._exit(1)\n')
    r = e.run()
    fr = fresh_of(e)
    check("0362 S1b: «38/39» из детали последней строкой при итоге «38 из 39» у базы — красное «нет итоговой строки»",
          r.returncode == 76 and "test_a.py: нет итоговой строки (последняя строка — деталь провала, не итог)" in fr,
          f"{r.returncode} {fr!r}")
    e.close()
    e = Env("1.0.0", "1.1.0", 'print("НЕ ПРОШЁЛ: x")\nprint("38 из 39 прошли")\nraise SystemExit(1)\n',
            'print("НЕ ПРОШЁЛ: x")\nprint("38 из 39 прошли")\nraise SystemExit(1)\n')
    r = e.run()
    check("0362 S1b: настоящий итог «38 из 39 прошли» у обеих — база гасит",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), f"{r.returncode} {fresh_of(e)!r}")
    e.close()
    # шапка: числа от 4 знаков в строке провала — N (склеиваются), короче — нет (мутант: порог 3 знака или 5)
    SUM = 'print("тестов: 40, не прошло: 1")\nraise SystemExit(1)\n'
    for was, now, same in (("размер 4096", "размер 8192", True), ("размер 999", "размер 998", False)):
        e = Env("1.0.0", "1.1.0", f"print('НЕ ПРОШЛО:', {was!r})\n" + SUM, f"print('НЕ ПРОШЛО:', {now!r})\n" + SUM)
        r = e.run()
        check(f"0362 шапка: «{was}» против «{now}» — " + ("склеиваются (число от 4 знаков — N)" if same else "разные"),
              (r.returncode == 0) == same, f"{r.returncode} {fresh_of(e)!r}")
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
  "rand": [p._tmp_sub("x " + p.tempfile.gettempdir() + "/guard-ab12cd34/" + w + "/guard/tmpq1w2e3r4/README.md")
           for w in ("new", "base")]
          + [p._tmp_sub("'" + p.tempfile.gettempdir() + "/board-root-1az784c9/board-test-ef6u2lif/state/x.json'")],
  "names": [p._tmp_sub(p.tempfile.gettempdir() + "/home-q1w2e3r4/ai/pantheon/directions/" + d + "/STATUS.md")
            for d in ("metis-pantheon", "hephaestus-pantheon")],
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
    NS = "t.py: нет итоговой строки"
    check("подписи: корень временной папки → <tmp>, путь внутри остаётся (ревью 0359, п.1)",
          got.get("tmp") == ["FAIL x <tmp>/abc/new/x/f.py", "FAIL y <tmp>/q/z", "t.py: код 1", NS], got.get("tmp"))
    check("подписи: случайные папки mkdtemp → «…», корень копии new/ и base/ → <copy>, имя файла остаётся",
          got.get("rand") == ["x <tmp>/…/<copy>/guard/…/README.md"] * 2 + ["'<tmp>/…/state/x.json'"], got.get("rand"))
    check("подписи: имя с дефисом и 8 знаками ниже настоящей папки — не «…» (ревью 0359, круг 3, п.3)",
          got.get("names") == [f"<tmp>/…/ai/pantheon/directions/{d}/STATUS.md"
                               for d in ("metis-pantheon", "hephaestus-pantheon")], got.get("names"))
    check("подписи: код без FAIL, зелёный файл, таймаут",
          got.get("code") == ["t.py: код 2", NS] and got.get("ok") == [] and got.get("timeout") == ["t.py: таймаут"],
          got)
    check("подписи: FAIL, исключение в конце с текстом и код",
          got.get("exc") == ["FAIL a", "t.py: исключение ValueError: b", "t.py: код 1", NS], got.get("exc"))
    check("подписи: ANSI вырезан, код при FAIL — всегда",
          got.get("ansi") == ["FAIL c", "t.py: код 1", NS] and got.get("killed") == ["FAIL d", "t.py: код -9", NS], got)
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
tg = p._base_targets(C({{("py", "a.py", "FAIL x"): 1, ("py", "t.py", "t.py: таймаут"): 1, ("py", "t.py", "FAIL y"): 1,
                         ("py", "v.py", "v.py: срок прогона"): 1, ("py2", "a.py", "a.py: код 1"): 1}}))
p._test_pythons = lambda: [sys.executable, "/old/python3"]
p._py_ge311 = lambda py: py == sys.executable
print(json.dumps({{"fresh": sorted(k[1] + "|" + k[2] for k in fresh), "unk": sorted(unk), "clean": sorted(clean),
                  "clean_unk": sorted(unk2), "targets": sorted(tg), "pan": p._pythons_for("pantheon") == [sys.executable],
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
    check("цели базы: только (python, файл) с падениями новой, без таймаута и срока прогона (metis-0358)",
          g2.get("targets") == [["py", "a.py"], ["py2", "a.py"]], g2.get("targets"))
    check("интерпретаторы: pantheon — только 3.11+, guard — все", g2.get("pan") and g2.get("guard"), g2)
    r = subprocess.run([PY, "-I", LIB, "plugins", "foo"], capture_output=True, text=True, timeout=60)
    check("pantheon plugins foo — код 2", r.returncode == 2)

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
