#!/usr/bin/env python3
"""Синтетические тесты `pantheon plugins update` (metis-0052): тик ставит новые версии плагинов agent-kit.

Запуск: python3 -I plugins/pantheon/tests/test_plugins_update.py  (код выхода 0 — все прошли)
Тесты плагинов идут до слияния — workflow tests в GitHub Actions (п. 8 страницы упрощения 27.10). Тик ставит выпуск,
только если запись в .claude-plugin/releases.json каталога совпала с ним (версия и дерево), без локального прогона
тестов и без порога памяти. Временный HOME с каталогом agent-kit и кэшем установленной версии; `claude` — заглушка
первой в PATH: пишет argv в файл, на `plugin list --json` отдаёт JSON из файла (после `plugin update` — уже с новой
версией), на `plugin marketplace update` — код из STUB_MKT_RC. Настоящие `claude plugin …` не запускаются.
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

RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
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

PY = sys.executable


class Env:
    """Временный HOME: каталог agent-kit, кэш установленной версии плагина x, заглушка claude."""

    def __init__(self, installed, catalog, known=True, name="x", release=True):
        self.name = name
        self.release = release  # True — перед каждым run запись выпуска в releases.json совпадает с каталогом
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
        self.release_names = None
        self.plugin(self.src, catalog)
        self.plugin(cache, installed)
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

    def plugin(self, d, version):
        self.write(os.path.join(d, ".claude-plugin", "plugin.json"), json.dumps({"name": self.name, "version": version}))
        # тест версии отмечает каждый запуск: тик тестов локально не гоняет (п. 8), счётчик должен остаться 0
        self.write(os.path.join(d, "tests", "test_a.py"),
                   f"with open({self.counter!r}, 'a') as fh:\n    fh.write('run\\n')\n")

    def released(self, plugins=None):
        """releases.json каталога: запись выпуска — версия и дерево каталога каждого плагина (как workflow release)."""
        mkt = os.path.join(self.home, ".claude", "plugins", "marketplaces", "agent-kit")
        rec = {}
        for n in plugins or [self.name]:
            d = os.path.join(mkt, "plugins", n)
            ver = json.load(open(os.path.join(d, ".claude-plugin", "plugin.json")))["version"]
            rec[n] = {"version": ver, "tree": (self.py("print(P._tree_hash(sys.argv[2]))", d) or ["?"])[0]}
        self.write(os.path.join(mkt, ".claude-plugin", "releases.json"), json.dumps({"v": 1, "plugins": rec}))

    def notified(self):
        return open(self.notes, encoding="utf-8").read() if os.path.exists(self.notes) else ""

    def run(self, *args, extra=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PANTHEON_", "STUB_"))}
        env.update({"PATH": self.stub + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.home,
                    "PANTHEON_HOME": self.pantheon, "PANTHEON_STATE": self.state, "PANTHEON_NO_NOTIFY": "1",
                    "PANTHEON_NOTIFY_LOG": self.notes, "STUB_DIR": self.stub, "TMPDIR": self.tmpdir})
        env.update(extra or {})
        args = args or ("plugins", "update", "--quiet")
        if self.release is True and args[:2] == ("plugins", "update"):
            self.released(self.release_names)
        return subprocess.run([PY, "-I", RUN_PY, *args], env=env, capture_output=True, text=True, timeout=300)

    def py(self, code, *args, stub=False):
        """Код с `import pantheon as P` в этом HOME (как окно роли: только чтение реестра); stdout строками. stub —
        заглушка claude первой в PATH, как у run (весь проход plugins update внутри процесса)."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PANTHEON_", "STUB_"))}
        env.update({"HOME": self.home, "PANTHEON_HOME": self.pantheon, "PANTHEON_STATE": self.state,
                    "PANTHEON_NO_NOTIFY": "1", "TMPDIR": self.tmpdir})
        if stub:
            env.update({"PATH": self.stub + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
                        "STUB_DIR": self.stub, "PANTHEON_NOTIFY_LOG": self.notes})
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

    # Новых нет: версия каталога та же — молчит, код 0, update не вызван
    e = Env("1.0.0", "1.0.0")
    r = e.run()
    check("нет новых: --quiet молчит, код 0, update не вызван",
          r.returncode == 0 and r.stdout == "" and "plugin update" not in e.argv() and e.runs() == 0,
          f"{r.returncode} {r.stdout!r} {r.stderr!r} {e.argv()!r}")
    check("нет новых: каталог обновлён (marketplace update agent-kit)",
          "plugin marketplace update agent-kit" in e.argv())
    r = e.run("plugins", "update")
    check("без --quiet: строка на плагин", r.returncode == 0 and "x: 1.0.0, новее нет" in r.stdout, r.stdout)
    e.close()

    # metis-0321: ссылка ~/.local/share/pantheon/current — на установленную версию. Выпуск встал — ссылка переезжает
    # на новую папку кэша; выпуска нет — остаётся на старой, клон маркетплейса живым не становится
    e = Env("1.0.0", "1.1.0", name="pantheon")
    cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
    old_cache = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "pantheon", "1.0.0")
    os.makedirs(os.path.dirname(cur))
    os.symlink(old_cache, cur)
    r = e.run()
    check("pantheon выпуск встал: current → новая установленная версия, не клон",
          r.returncode == 0 and os.path.islink(cur) and os.path.realpath(cur) == os.path.realpath(e.after),
          f"{r.returncode} {r.stderr!r} {os.path.realpath(cur)}")
    e.close()
    e = Env("1.0.0", "1.1.0", name="pantheon", release=False)
    cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
    old_cache = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "pantheon", "1.0.0")
    os.makedirs(os.path.dirname(cur))
    os.symlink(old_cache, cur)
    r = e.run()
    check("pantheon без записи выпуска: update не вызван, current остаётся на установленной, клон не живой",
          "plugin update" not in e.argv() and os.readlink(cur) == old_cache, f"{e.argv()!r} {os.readlink(cur)}")
    e.close()
    e = Env("1.0.0", "1.1.0")
    cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
    e.run()
    check("другой плагин (x): ссылку current не трогает", not os.path.lexists(cur))
    e.close()

    # ревью 90a, п.2: выпуск сверен, а встала другая версия или другое дерево — current остаётся прежней
    # (мутант: link_current до сверки got == new и хеша в _plugin_install)
    for what in ("версия", "дерево"):
        e = Env("1.0.0", "1.1.0", name="pantheon")
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
        check(f"pantheon, выпуск сверен, но встала другая {what}: current остаётся прежней, КРИТИЧНО в alerts.md",
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
    e = Env("1.0.0", "1.1.0", name="pantheon")
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
        e = Env("1.0.0", "1.1.0", name="pantheon")
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
        e = Env("1.0.0", "1.0.0", name="pantheon")
        plugins = os.path.join(e.home, ".claude", "plugins")
        cache = os.path.join(plugins, "cache", "agent-kit", "pantheon", "1.0.0")
        e.write(os.path.join(plugins, "installed_plugins.json"), json.dumps({"version": 2, "plugins": {
            "pantheon@agent-kit": [{"scope": "user", "installPath": cache, "version": "1.0.0"}]}}))
        cur = os.path.join(e.home, ".local", "share", "pantheon", "current")
        os.makedirs(os.path.dirname(cur))
        if what == "отстала":
            stale = os.path.join(plugins, "cache", "agent-kit", "pantheon", "0.9.0")
            e.plugin(stale, "0.9.0")
        else:
            stale = os.path.join(plugins, "cache", "agent-kit", "pantheon", "0.8.0")  # папки нет
        os.symlink(stale, cur)
        e.verify(cache)
        r = e.run()
        check(f"pantheon, новее нет, current {what}: перевешена на установленную проверенную папку",
              r.returncode == 0 and os.path.realpath(cur) == os.path.realpath(cache), f"{r.stderr!r} {os.readlink(cur)}")
        e.close()
    e = Env("1.0.0", "1.0.0", name="pantheon")
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
    e = Env("1.0.0", "0.9.0")
    r = e.run()
    check("версия каталога старее: не ставим", r.returncode == 0 and "plugin update" not in e.argv() and e.runs() == 0)
    e.close()

    # Новая, запись выпуска совпала — update, строка в alerts.md и журнал
    e = Env("1.0.0", "1.1.0")
    r = e.run()
    check("выпуск: вызван plugin update x@agent-kit -s user, код 0",
          r.returncode == 0 and "plugin update x@agent-kit -s user" in e.argv(),
          f"{r.returncode} {r.stderr!r} {e.argv()!r}")
    check("выпуск: без -y", " -y" not in e.argv())
    check("выпуск: «обновлён x 1.0.0 → 1.1.0» в alerts.md",
          "plugins-update · обновлён x 1.0.0 → 1.1.0, плановый проход перезапустит свободные окна" in e.alerts(), e.alerts())
    rsp = os.path.join(e.state, "plugins", "respawn.json")
    rj = json.load(open(rsp)) if os.path.exists(rsp) else {}
    check("выпуск: отметка «нужен перезапуск» respawn.json {since, plugins: [x], done: []} (metis-0181)",
          rj.get("plugins") == ["x"] and float(rj.get("since") or 0) > 0 and rj.get("done") == [], rj)
    check("выпуск: строка в журнале", "x 1.0.0 → 1.1.0: обновлён" in e.journal())
    check("выпуск: тесты версии локально не гонялись, временных копий нет (п. 8)",
          e.runs() == 0 and not os.path.exists(os.path.join(e.state, "plugins", "tmp"))
          and not os.path.exists(os.path.join(e.state, "plugins", "results")), e.runs())
    check("выпуск: без критической тревоги (хеш кэша с .in_use совпал с деревом каталога)",
          "КРИТИЧНО" not in e.alerts() and e.notified() == "")
    e.close()

    # Встало не то, что выпущено: update сам подтянул каталог — другое содержимое той же версии
    e = Env("1.0.0", "1.1.0")
    e.write(os.path.join(e.after, "hooks", "evil.py"), "print('не проверялось')\n")
    r = e.run()
    check("TOCTOU, другое содержимое: КРИТИЧНО в alerts.md и уведомление, код 76",
          r.returncode == 76 and "КРИТИЧНО: встала непроверенная версия x 1.1.0 (выпуск 1.1.0)" in e.alerts()
          and "Пантеон · критично|встала непроверенная версия x 1.1.0" in e.notified()
          and "Руками" not in e.alerts() and "обновлён" not in e.alerts(), f"{r.returncode} {e.alerts()!r}")
    e.close()

    # Встало не то, что выпущено: другая версия
    e = Env("1.0.0", "1.1.0")
    p = os.path.join(e.stub, "list-after.json")
    rows = json.load(open(p))
    rows[-1]["version"] = "1.2.0"
    e.write(p, json.dumps(rows))
    r = e.run()
    check("TOCTOU, другая версия: КРИТИЧНО «x 1.2.0 (выпуск 1.1.0)», код 76",
          r.returncode == 76 and "встала непроверенная версия x 1.2.0 (выпуск 1.1.0)" in e.alerts()
         , e.alerts())
    e.close()

    # п. 8: за один проход ставятся все плагины с выпуском (раньше — тесты не больше одного плагина за запуск)
    e = Env("1.0.0", "1.1.0")
    mkt = os.path.dirname(os.path.dirname(e.src))
    e.plugin(os.path.join(mkt, "plugins", "y"), "2.1.0")
    ycache = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "y", "2.0.0")
    e.plugin(ycache, "2.0.0")
    e.write(os.path.join(mkt, ".claude-plugin", "marketplace.json"),
            json.dumps({"name": "agent-kit", "plugins": [{"name": "x", "source": "./plugins/x"},
                                                        {"name": "y", "source": "./plugins/y"}]}))
    yafter = os.path.join(e.home, ".claude", "plugins", "cache", "agent-kit", "y", "2.1.0-new")
    shutil.copytree(os.path.join(mkt, "plugins", "y"), yafter)
    yrow = {"id": "y@agent-kit", "version": "2.0.0", "scope": "user", "installPath": ycache}
    p = os.path.join(e.stub, "list.json")
    e.write(p, json.dumps(json.load(open(p)) + [yrow]))
    p = os.path.join(e.stub, "list-after.json")
    e.write(p, json.dumps(json.load(open(p)) + [{**yrow, "version": "2.1.0", "installPath": yafter}]))
    e.release_names = ["x", "y"]
    r = e.run()
    check("два плагина с выпуском: оба поставлены за один проход, тесты не гонялись",
          r.returncode == 0 and "plugin update x@agent-kit" in e.argv() and "plugin update y@agent-kit" in e.argv()
          and "обновлён y 2.0.0 → 2.1.0" in e.alerts() and e.runs() == 0, f"{r.returncode} {e.argv()!r} {e.alerts()!r}")
    e.close()

    # п. 8: старые метки прогона тестов (red, testing, partial, отсрочка) и давление памяти выпуск не держат
    for mark in ("red", "testing", "partial"):
        e = Env("1.0.0", "1.1.0")
        e.write(os.path.join(e.state, "plugins", "marks.json"), json.dumps(
            {"x": {"version": "1.1.0", "result": mark, "log": "x.log", "at": "раньше", "deferred_since": 1}}))
        r = e.run()
        check(f"старая метка {mark} той же версии: выпуск ставится", r.returncode == 0
              and "обновлён x 1.0.0 → 1.1.0" in e.alerts(), f"{r.returncode} {e.alerts()!r}")
        e.close()
    e = Env("1.0.0", "1.1.0")
    r = e.run(extra={"PANTHEON_FAKE_PRESSURE": "4", "PANTHEON_FAKE_SWAP": "99"})
    check("давление памяти критичное и своп 99 ГБ: выпуск ставится сразу (порога нет)",
          r.returncode == 0 and "обновлён x 1.0.0 → 1.1.0" in e.alerts(), f"{r.returncode} {e.alerts()!r}")
    e.close()
    # Каталог без known_marketplaces.json — запасной путь ~/.claude/plugins/marketplaces/agent-kit
    e = Env("1.0.0", "1.1.0", known=False)
    r = e.run()
    check("запасной путь каталога", r.returncode == 0 and "plugin update x@agent-kit" in e.argv(), r.stderr)
    e.close()

    # Выпуск сверен, а update не удался — тревога один раз, следующий проход пробует снова
    e = Env("1.0.0", "1.1.0")
    r = e.run(extra={"STUB_UPD_RC": "1"})
    check("update упал: код 76, строка в журнале", r.returncode == 76 and "установка не удалась" in e.journal(),
          f"{r.returncode} {e.journal()!r}")
    check("update упал: отметки «нужен перезапуск» нет (metis-0181)",
          not os.path.exists(os.path.join(e.state, "plugins", "respawn.json")))
    n = e.runs()
    r = e.run(extra={"STUB_UPD_RC": "1"})
    check("update упал повторно: update пробуется, тревога одна",
          r.returncode == 76 and e.runs() == n == 0 and e.argv().count("plugin update x@agent-kit") == 2
          and e.alerts().count("claude plugin update не поставил выпуск") == 1, e.alerts())
    r = e.run()
    check("update прошёл позже: обновлён",
          r.returncode == 0 and "обновлён x 1.0.0 → 1.1.0" in e.alerts() and e.runs() == n)
    e.close()

    # Каталог не обновился (нет сети) — 75, дальше не идём
    e = Env("1.0.0", "1.1.0")
    r = e.run(extra={"STUB_MKT_RC": "1"})
    check("marketplace update упал: код 75, без тревоги",
          r.returncode == 75 and e.alerts() == "" and e.runs() == 0 and "plugin list" not in e.argv())
    e.close()

    # Второй запуск при занятой блокировке — сразу 0
    e = Env("1.0.0", "1.1.0")
    os.makedirs(os.path.join(e.state, "locks"))
    with open(os.path.join(e.state, "locks", "plugins-update.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        r = e.run()
    check("блокировка занята: код 0, claude не вызван", r.returncode == 0 and e.argv() == "")
    e.close()

    # Разбор команды тиком и сравнение версий
    probe = f"""
import json, sys
sys.path.insert(0, {os.path.dirname(LIB)!r})
import pantheon as p
cmds = ["pantheon plugins update --quiet", "pantheon plugins update", "pantheon plugins foo",
        "pantheon plugins update --force", "pantheon plugins"]
print(json.dumps({{
  "cmds": {{c: p.parse_command(c) is not None for c in cmds}},
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
    check("версии: числа, равные, не разобрать", got.get("newer") == [True, False, True], got.get("newer"))
    # metis-0512: номер поднимает workflow release после слияния и пишет .claude-plugin/releases.json каталога. Новая
    # версия ставится, только если запись выпуска совпала с каталогом (версия и дерево); файла нет — не ставится
    for case in ("match", "old_version", "other_tree", "broken", "no_record", "bad_v", "link", "missing"):
        e = Env("1.0.0", "1.1.0", release=False)
        mkt = os.path.join(e.home, ".claude", "plugins", "marketplaces", "agent-kit")
        rel = os.path.join(mkt, ".claude-plugin", "releases.json")
        tree = (e.py("print(P._tree_hash(sys.argv[2]))", e.src) or ["?"])[0]
        rec = {"version": "1.1.0", "tree": tree}
        body = {"match": {"v": 1, "plugins": {"x": rec}},
                "old_version": {"v": 1, "plugins": {"x": {**rec, "version": "1.0.0"}}},
                "other_tree": {"v": 1, "plugins": {"x": {**rec, "tree": "0" * 64}}},
                "no_record": {"v": 1, "plugins": {"y": rec}},
                "bad_v": {"v": 2, "plugins": {"x": rec}}}.get(case)
        if case == "link":
            e.write(os.path.join(e.tmp, "rel.json"), json.dumps({"v": 1, "plugins": {"x": rec}}))
            os.symlink(os.path.join(e.tmp, "rel.json"), rel)
        elif case != "missing":
            e.write(rel, "{не json" if case == "broken" else json.dumps(body))
        r = e.run("plugins", "update")
        put = "plugin update" in e.argv()
        if case == "match":
            check("releases.json: запись совпала (версия и дерево) — установка без локальных тестов",
                  r.returncode == 0 and put and e.runs() == 0, f"{r.returncode} {r.stdout!r} {e.argv()!r}")
        else:
            check(f"releases.json {case}: выпуск не сверен — установки нет, причина в выводе и журнале",
                  r.returncode == 0 and not put and e.runs() == 0 and "не ставлю" in r.stdout
                  and "не ставлю" in e.journal(), f"{r.returncode} {r.stdout!r} {e.journal()!r}")
            e.run()
            check(f"releases.json {case}: второй проход — строка в журнале одна",
                  e.journal().count("не ставлю") == 1, e.journal())
        e.close()

    # metis-0587 (вариант Б): на новом выпуске тик смотрит tests на main (gh — заглушка в PATH). failure — одна тревога
    # на коммит; зелёный, нет данных, startup_failure, сбой gh — без тревоги, строка в журнале раз в день, выпуск идёт
    GH = "#!/bin/sh\necho \"$*\" >> \"$STUB_DIR/gh.log\"\n[ \"${STUB_GH_RC:-0}\" = 0 ] || { echo boom >&2; exit \"$STUB_GH_RC\"; }\ncat \"$STUB_DIR/gh.json\"\n"

    def ci_env(runs, rc=0, new=True):
        e = Env("1.0.0", "1.1.0" if new else "1.0.0")
        e.write(os.path.join(e.stub, "gh"), GH)
        os.chmod(os.path.join(e.stub, "gh"), 0o755)
        e.write(os.path.join(e.stub, "gh.json"), json.dumps(runs))
        shutil.copy(os.path.join(e.stub, "list.json"), os.path.join(e.stub, "list-before.json"))
        return e, {"STUB_GH_RC": str(rc)}

    def again(e, x):
        """Ещё один проход с новым выпуском: установленная версия снова старая (как до установки)."""
        shutil.copy(os.path.join(e.stub, "list-before.json"), os.path.join(e.stub, "list.json"))
        return e.run("plugins", "update", extra=x)

    def run_row(sha, conclusion, status="completed"):
        return {"headSha": sha, "conclusion": conclusion, "status": status, "url": f"https://github.com/r/{sha}"}

    red = [run_row("a" * 40, "failure"), run_row("b" * 40, "success")]
    e, x = ci_env(red)
    r = e.run("plugins", "update", extra=x)
    check("tests красные на main: тревога с коммитом и ссылкой, выпуск всё равно ставится",
          r.returncode == 0 and "plugin update" in e.argv() and "tests красные на main" in e.alerts()
          and "a" * 10 in e.alerts() and "https://github.com/r/" + "a" * 40 in e.alerts(), f"{r.stdout!r} {e.alerts()!r}")
    e.close()
    e, x = ci_env(red)
    e.run("plugins", "update", extra=x)
    again(e, x)
    again(e, x)
    check("tests красные на main: повторные проходы той же беды не множат тревогу (одна на коммит)",
          e.alerts().count("tests красные на main") == 1, e.alerts())
    e.close()
    e, x = ci_env(red)
    e.run("plugins", "update", extra=x)
    e.write(os.path.join(e.stub, "gh.json"), json.dumps([run_row("c" * 40, "failure")]))
    again(e, x)
    check("новый красный коммит — новая тревога", e.alerts().count("tests красные на main") == 2, e.alerts())
    ghlog = open(os.path.join(e.stub, "gh.log")).read()
    check("gh спрошен про tests.yml на ветке main репозитория latark/agent-kit",
          "--branch main" in ghlog and "--workflow tests.yml" in ghlog and "--repo latark/agent-kit" in ghlog, ghlog)
    e.close()
    e, x = ci_env([run_row("d" * 40, None, "in_progress")] + red)
    e.run("plugins", "update", extra=x)
    check("идущий прогон пропускается: берётся последний завершённый", "a" * 10 in e.alerts(), e.alerts())
    e.close()
    for name, runs, rc in (("зелёный", [run_row("a" * 40, "success")], 0), ("нет прогонов", [], 0),
                           ("startup_failure", [run_row("a" * 40, "startup_failure")], 0),
                           ("сбой gh", red, 7)):
        e, x = ci_env(runs, rc)
        r = e.run("plugins", "update", extra=x)
        again(e, x)
        quiet = "tests красные" not in e.alerts()
        if name == "зелёный":
            check("tests зелёные на main: без тревоги и без строки в журнале",
                  r.returncode == 0 and quiet and "tests на main" not in e.journal(), f"{e.alerts()!r} {e.journal()!r}")
        else:
            check(f"{name}: без тревоги, выпуск ставится, строка в журнале одна за день",
                  r.returncode == 0 and quiet and "plugin update" in e.argv() and sum(l[17:].startswith("tests на main:") for l in e.journal().splitlines()) == 1,
                  f"{r.returncode} {e.alerts()!r} {e.journal()!r}")
        e.close()
    e, x = ci_env(red, new=False)
    e.run("plugins", "update", extra=x)
    check("новых выпусков нет: gh не вызывается", not os.path.exists(os.path.join(e.stub, "gh.log")))
    e.close()
    e = Env("1.0.0", "1.1.0")  # gh нет вовсе
    r = e.run("plugins", "update", extra={"PATH": e.stub + os.pathsep + "/usr/bin:/bin"})
    check("gh не найден: тик цел, выпуск ставится", r.returncode == 0 and "plugin update" in e.argv(), r.stderr)
    e.close()

    r = subprocess.run([PY, "-I", RUN_PY, "plugins", "foo"], capture_output=True, text=True, timeout=60)
    check("pantheon plugins foo — код 2", r.returncode == 2)

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
