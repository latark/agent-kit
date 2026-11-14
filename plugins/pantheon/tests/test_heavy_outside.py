#!/usr/bin/env python3
"""metis-1188: heavy в окне роли — проверка проекта уходит вне окна (`pantheon outside test --sha <HEAD> --wait`).

Запуск: python3 -I plugins/pantheon/tests/test_heavy_outside.py  (код выхода 0 — все прошли)
Копия heavy лежит в своём «плагине» (bin/heavy, lib/fullsuite.py) рядом с заглушкой bin/pantheon: заглушка пишет argv
и cwd в файл и выходит с кодом STUB_CODE. Проекты — вымышленные репозитории во временной папке.
- окно роли (PANTHEON_TMP или XDG_CACHE_HOME=<кэши окон>/<окно>/xdg), команда — первая строка .pantheon-verify или
  `pnpm [run] check|test` скрипта package.json: outside позван с --sha HEAD (и --script), из корня, код проброшен,
  вывод заглушки в stdout; 75 — строка «pantheon outside status <ID>»; HEAVY_OUTSIDE_WAIT уменьшает --wait;
- строка ci: (metis-1174): команда тестов — прежний отказ с подсказкой CI, прочая проверка — в окне, без outside;
- грязное дерево (правка, неотслеживаемый файл) — отказ, код 2, «закоммить» в последней строке; .claude/worktrees/ — не
  грязь; нет коммитов — код 2;
- вне окна, HEAVY_IN_WINDOW=1, --server, --probe, подпапка, скрипт с аргументами, скрипт не проверки — как раньше.
"""
import json
import os
import shutil
import stat
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEAVY = os.path.join(PLUGIN, "bin", "heavy")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import mkroot  # noqa: E402

fails, total = [], []
RID = "20261114-120000-abcdef"
STUB = f"""#!/bin/sh
printf '%s\\n' "$(pwd -P)" "$@" > "$STUB_LOG"
echo "заявка {RID}: test в $PWD — её исполнит плановый проход (раз в минуту)"
echo "--- хвост журнала ---"
echo "stub tail"
exit "${{STUB_CODE:-0}}"
"""
PM = """#!/bin/sh
echo "local-pnpm $*"
"""


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f" {extra}" if not cond else ""))
    total.append(name)
    if not cond:
        fails.append(name)


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)


def git(d, *args):
    env = {"PATH": os.environ["PATH"], "HOME": d, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", "-C", d, "-c", "commit.gpgsign=false", *args], env=env, capture_output=True,
                          text=True, timeout=30, check=True).stdout


def repo(tmp, name, verify, scripts=None, commit=True):
    d = os.path.join(tmp, name)
    os.makedirs(os.path.join(d, "sub"))
    write(os.path.join(d, ".pantheon-verify"), verify)
    write(os.path.join(d, "package.json"), json.dumps({"name": name, "scripts": scripts or {}}))
    write(os.path.join(d, "sub", "keep.txt"), "x\n")
    write(os.path.join(d, ".claude", "settings.json"), "{}\n")  # .claude/ отслеживается, как в проектах
    git(d, "init", "-q")
    if commit:
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "init")
    return os.path.realpath(d)


class Kit:
    def __init__(self, tmp):
        self.tmp = tmp
        kit = os.path.join(tmp, "kit")
        os.makedirs(os.path.join(kit, "bin"))
        os.makedirs(os.path.join(kit, "lib"))
        shutil.copy(HEAVY, os.path.join(kit, "bin", "heavy"))
        shutil.copy(os.path.join(PLUGIN, "lib", "fullsuite.py"), os.path.join(kit, "lib", "fullsuite.py"))
        write(os.path.join(kit, "bin", "pantheon"), STUB, stat.S_IRWXU)
        write(os.path.join(tmp, "pmbin", "pnpm"), PM, stat.S_IRWXU)
        self.heavy = os.path.join(kit, "bin", "heavy")
        self.log = os.path.join(tmp, "stub.log")
        self.home = os.path.join(tmp, "home")
        self.wtmp = os.path.join(self.home, "Library", "Caches", "pantheon-sandbox", "dev-x", "tmp")
        os.makedirs(self.wtmp)

    def run(self, cwd, *cmd, window=True, extra=None):
        if os.path.exists(self.log):
            os.unlink(self.log)
        env = {"PATH": os.path.join(self.tmp, "pmbin") + os.pathsep + os.environ["PATH"], "HOME": self.home,
               "PANTHEON_STATE": os.path.join(self.tmp, "state"), "STUB_LOG": self.log}
        if window:
            env["PANTHEON_TMP"] = self.wtmp
        env.update(extra or {})
        return subprocess.run([sys.executable, "-I", self.heavy, *cmd], env=env, capture_output=True, text=True,
                              timeout=60, cwd=cwd)

    def called(self):
        try:
            with open(self.log, encoding="utf-8") as fh:
                return fh.read().splitlines()
        except OSError:
            return None


def last(r):
    lines = r.stderr.strip().splitlines()
    return lines[-1] if lines else ""


def window_checks(k, app):
    head = git(app, "rev-parse", "HEAD").strip()
    r = k.run(app, "/bin/sh", "-c", "echo local-ran", extra={"STUB_CODE": "3"})
    c = k.called()
    check("окно: первая строка .pantheon-verify — outside test --sha HEAD --wait 590 из корня, код проброшен",
          r.returncode == 3 and c == [app, "outside", "test", "--sha", head, "--wait", "590"]
          and "stub tail" in r.stdout and "local-ran" not in r.stdout, f"{r.returncode} {c} {r.stdout!r} {r.stderr!r}")
    r = k.run(app, "pnpm", "run", "check")
    c = k.called()
    check("окно: pnpm run check (скрипт package.json) — outside с --script check, код 0",
          r.returncode == 0 and c == [app, "outside", "test", "--sha", head, "--script", "check", "--wait", "590"]
          and "local-pnpm" not in r.stdout, f"{r.returncode} {c} {r.stdout!r}")
    r = k.run(app, "pnpm", "test", extra={"HEAVY_OUTSIDE_WAIT": "30", "STUB_CODE": "1"})
    c = k.called()
    check("окно: pnpm test — --script test, HEAVY_OUTSIDE_WAIT=30 → --wait 30, красный код 1 проброшен",
          r.returncode == 1 and c == [app, "outside", "test", "--sha", head, "--script", "test", "--wait", "30"],
          f"{r.returncode} {c}")
    r = k.run(app, "pnpm", "check", extra={"HEAVY_OUTSIDE_WAIT": "9999"})
    c = k.called()
    check("окно: HEAVY_OUTSIDE_WAIT больше предела — --wait 590", c is not None and c[-1] == "590", f"{c}")
    r = k.run(app, "pnpm", "run", "check", extra={"STUB_CODE": "75"})
    check("окно: код 75 — проброшен, последняя строка — как ждать (pantheon outside status <ID>)",
          r.returncode == 75 and f"pantheon outside status {RID}" in last(r), f"{r.returncode} {r.stderr!r}")
    xdg = os.path.join(k.home, "Library", "Caches", "pantheon-sandbox", "hq", "xdg")
    os.makedirs(xdg)
    r = k.run(app, "pnpm", "run", "check", window=False, extra={"XDG_CACHE_HOME": xdg})
    check("окно hq (XDG_CACHE_HOME внутри кэшей окон) — тоже outside", k.called() is not None, f"{r.stderr!r}")
    r = k.run(app, "pnpm", "run", "check", window=False, extra={"XDG_CACHE_HOME": os.path.join(k.tmp, "other", "xdg")})
    check("XDG_CACHE_HOME вне кэшей окон — не окно, в окне как раньше",
          k.called() is None and "local-pnpm run check" in r.stdout, f"{r.stdout!r}")
    write(os.path.join(app, ".claude", "worktrees", "w1", "x.txt"), "x\n")
    r = k.run(app, "pnpm", "run", "check")
    check("окно: неотслеживаемый .claude/worktrees/ — не грязь, outside позван", k.called() is not None,
          f"{r.returncode} {r.stderr!r}")
    os.makedirs(os.path.join(k.tmp, "nm"))
    os.symlink(os.path.join(k.tmp, "nm"), os.path.join(app, "node_modules"))
    r = k.run(app, "pnpm", "run", "check")
    check("окно: неотслеживаемая ссылка node_modules в корне — не грязь, outside позван", k.called() is not None,
          f"{r.returncode} {r.stderr!r}")
    os.rename(os.path.join(os.path.dirname(k.heavy), "pantheon"), os.path.join(k.tmp, "pantheon.off"))
    r = k.run(app, "pnpm", "run", "check")
    os.rename(os.path.join(k.tmp, "pantheon.off"), os.path.join(os.path.dirname(k.heavy), "pantheon"))
    check("окно: pantheon не запустился — код 1, причина последней строкой", r.returncode == 1
          and "pantheon outside не запустился" in last(r), f"{r.returncode} {r.stderr!r}")


def local_checks(k, app):
    cases = [("вне окна роли", ("pnpm", "run", "check"), {"window": False}),
             ("HEAVY_IN_WINDOW=1", ("pnpm", "run", "check"), {"extra": {"HEAVY_IN_WINDOW": "1"}}),
             ("--server", ("--server", "pnpm", "run", "check"), {}),
             ("--probe", ("--probe", "pnpm", "run", "check"), {}),
             ("скрипт с аргументами", ("pnpm", "run", "check", "--watch"), {}),
             ("скрипт не проверки (build)", ("pnpm", "run", "build"), {}),
             ("скрипта нет в package.json", ("pnpm", "run", "check:none"), {})]
    for name, cmd, kw in cases:
        r = k.run(app, *cmd, **kw)
        words = cmd[1:] if cmd[0].startswith("--") else cmd
        check(f"как раньше: {name} — в окне, outside не позван",
              r.returncode == 0 and k.called() is None and "local-pnpm " + " ".join(words[1:]) in r.stdout,
              f"{r.returncode} {k.called()} {r.stdout!r} {r.stderr!r}")
    r = k.run(app, "/bin/sh", "-c", "echo local-ran", window=False)
    check("вне окна: строка .pantheon-verify идёт как раньше", r.returncode == 0 and "local-ran" in r.stdout
          and k.called() is None, f"{r.returncode} {r.stdout!r}")
    r = k.run(app, "/bin/echo", "check")
    check("как раньше: не менеджер пакетов (echo check) — в окне, outside не позван",
          r.returncode == 0 and k.called() is None and r.stdout.strip() == "check", f"{r.stdout!r} {k.called()}")
    r = k.run(os.path.join(app, "sub"), "pnpm", "run", "check")
    check("подпапка репозитория — как раньше, outside не позван", k.called() is None and "local-pnpm" in r.stdout,
          f"{r.stdout!r}")


def refusal_checks(k, tmp, app):
    ci = repo(tmp, "ciproj", "python3 -I tests/test_x.py\nci: echo lint\n", {"check": "echo c"})
    r = k.run(ci, sys.executable, "-I", "tests/test_x.py")
    check("ci: команда тестов в окне — прежний отказ metis-1174, outside не позван",
          r.returncode == 2 and k.called() is None and last(r).endswith("запасной путь — pantheon outside test"),
          f"{r.returncode} {r.stderr!r}")
    r = k.run(ci, "pnpm", "run", "check")
    check("ci: проверка не тестами — в окне как раньше, outside не позван",
          k.called() is None and "local-pnpm run check" in r.stdout, f"{k.called()} {r.stdout!r}")
    write(os.path.join(app, "sub", "keep.txt"), "changed\n")
    r = k.run(app, "pnpm", "run", "check")
    check("грязное дерево (правка) — отказ, код 2, «закоммить» в последней строке, outside не позван",
          r.returncode == 2 and k.called() is None and "закоммить" in last(r) and "sub/keep.txt" in last(r),
          f"{r.returncode} {r.stderr!r}")
    git(app, "checkout", "-q", "--", "sub/keep.txt")
    write(os.path.join(app, "new_test.txt"), "n\n")
    r = k.run(app, "pnpm", "run", "check")
    check("неотслеживаемый файл — тоже отказ, код 2", r.returncode == 2 and k.called() is None
          and "закоммить" in last(r), f"{r.returncode} {r.stderr!r}")
    os.unlink(os.path.join(app, "new_test.txt"))
    r = k.run(app, "pnpm", "run", "check")
    check("дерево снова чистое — outside позван", k.called() is not None, f"{r.returncode} {r.stderr!r}")
    empty = repo(tmp, "empty", "pnpm run check\n", {"check": "echo c"}, commit=False)
    r = k.run(empty, "pnpm", "run", "check")
    check("нет коммитов — код 2, outside не позван", r.returncode == 2 and k.called() is None
          and "нет коммитов" in last(r), f"{r.returncode} {r.stderr!r}")


def main():
    tmp = mkroot("tmp-heavyout-")
    try:
        k = Kit(tmp)
        app = repo(tmp, "app", "# проверка проекта\ndev: pnpm run lint\nheavy /bin/sh -c 'echo local-ran'\n",
                   {"check": "tsc && vitest run", "test": "vitest run", "build": "next build", "lint": "eslint ."})
        window_checks(k, app)
        local_checks(k, app)
        refusal_checks(k, tmp, app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("упали: " + "; ".join(fails))
    print(f"\n{len(total) - len(fails)} из {len(total)} прошли")  # итог с числом — последней строкой (run-tests.py)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
