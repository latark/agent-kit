#!/usr/bin/env python3
"""revert_check.py [--base REF] [--repo DIR] [--timeout С] — ловят ли новые тесты PR откат правки (metis-1176).

  python3 -I plugins/pantheon/scripts/revert_check.py --base origin/main

Решение владельца 14.11: argus не гоняет тесты на Mac, поэтому проверку «новый тест ловит поломку» делает CI (job
revert-check в .github/workflows/tests.yml, необязательная проверка шлюза — OPTIONAL_CHECKS в merge_gate.py).

Что делает:
1. merge-base REF и HEAD; `git diff --name-status --no-renames <merge-base> HEAD` (переименование — удаление и
   добавление). Тесты — добавленные или изменённые `plugins/<плагин>/tests/test_*.py`. Исходники — любой изменённый
   путь вне `plugins/*/tests/` и не `*.md`.
2. Нет тестов или нет исходников — пропуск строкой с причиной, код 0: проверять нечего.
3. Иначе — копия дерева на merge-base (`git worktree add --detach` во временную папку; в конце убирается). В неё из
   HEAD целиком кладётся папка `tests/` каждого плагина с изменённым тестом: сами тесты, помощники `tests/_*.py` и
   fixtures. Исходники остаются от merge-base — это и есть откат правки.
4. Каждый тест — отдельный процесс `<этот python> -I tests/<файл>` в папке плагина копии, как в run-tests.py: свой HOME
   и TMPDIR, окружение без PANTHEON_*, NO_COLOR=1, своя группа процессов, предел --timeout на файл (таймаут — «упал»).
5. Итог. Хоть один упал — код 0, строки «упал на merge-base: <файл> (код N)». Новый файл, который на базе падает с
   ImportError нового модуля, тоже «упал»: без правки он не проходит. Все зелёные — код 1 и последней строкой
   «тест не ловит откат: <файлы> зелёные на исходниках merge-base — нужен случай, который краснеет без правки».
   Сбой git (нет REF, нет merge-base) — код 2 и причина последней строкой.

Границы: на Linux случаи «пропущено: нужен macOS» проходят зелёными — такой тест на CI откат не поймает, и красная
проверка тогда предупреждение, а не приговор (решает argus). Тест, правка которого не связана с исходниками PR (тот
же PR чинит соседнее), тоже даёт красную — проверка необязательная. Только stdlib.
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile

TEST_PREFIX = "plugins/"
DROP_ENV = ("PANTHEON_", "FORCE_COLOR", "CLICOLOR_FORCE")
TIMEOUT = 300
TAIL = 5  # строк вывода упавшего теста в итоге


def git(repo, *args, check=True):
    """git в repo → stdout; сбой при check — RuntimeError с последней строкой stderr."""
    r = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=repo, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        err = (r.stderr.strip().splitlines() or ["без вывода"])[-1]
        raise RuntimeError(f"git {' '.join(args)}: код {r.returncode}: {err}")
    return r.stdout


def is_test(path):
    """plugins/<плагин>/tests/test_*.py прямо в tests/."""
    parts = path.split("/")
    return (len(parts) == 4 and path.startswith(TEST_PREFIX) and parts[2] == "tests"
            and parts[3].startswith("test_") and parts[3].endswith(".py"))


def in_tests(path):
    """Путь внутри plugins/<плагин>/tests/ (тесты, помощники, fixtures)."""
    parts = path.split("/")
    return len(parts) >= 4 and path.startswith(TEST_PREFIX) and parts[2] == "tests"


def classify(name_status):
    """Вывод `git diff --name-status --no-renames` → (тесты A/M, исходники). Исходник — не в tests/ и не *.md."""
    tests, sources = [], []
    for line in name_status.splitlines():
        st, _, path = line.partition("\t")
        if not path:
            continue
        if is_test(path) and st[:1] in ("A", "M"):
            tests.append(path)
        elif not in_tests(path) and not path.endswith(".md"):
            sources.append(path)
    return sorted(tests), sorted(sources)


def overlay_tests(repo, copy, plugins):
    """Папки plugins/<плагин>/tests из HEAD — поверх копии на merge-base (git archive | tar)."""
    paths = [f"plugins/{p}/tests" for p in plugins]
    proc = subprocess.Popen(["git", "archive", "--format=tar", "HEAD", "--", *paths], cwd=repo,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
        tar.extractall(copy, filter="data")
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"git archive HEAD: код {proc.returncode}: {(err.strip().splitlines() or [''])[-1]}")


def clean_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith(DROP_ENV)}
    env.update(HOME=home, TMPDIR=home, NO_COLOR="1")
    return env


def run_one(copy, path, timeout, scratch):
    """Один файл тестов в копии → (код или None при таймауте, хвост вывода)."""
    _, plugin, _, name = path.split("/")
    home = tempfile.mkdtemp(prefix="home-", dir=scratch)
    proc = subprocess.Popen([sys.executable, "-I", os.path.join("tests", name)], cwd=os.path.join(copy, "plugins", plugin),
                            env=clean_env(home), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        out, code = "", None
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # внуки файла тоже
        except (ProcessLookupError, PermissionError):
            pass
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return code, [ln for ln in (out or "").splitlines() if ln.strip()][-TAIL:]


def verdict(results):
    """{файл: (код | None, хвост)} → (код выхода, строки итога)."""
    failed = [p for p, (code, _) in results.items() if code != 0]
    green = [p for p, (code, _) in results.items() if code == 0]
    lines = []
    for p in failed:
        code, tail = results[p]
        lines.append(f"упал на merge-base: {p} ({'таймаут' if code is None else f'код {code}'})")
        lines += [f"    {ln}" for ln in tail]
    lines += [f"зелёный на merge-base: {p}" for p in green]
    if failed:
        lines.append(f"ок: откат ловят {len(failed)} из {len(results)} тестов PR")
        return 0, lines
    lines.append(f"тест не ловит откат: {', '.join(green)} зелёные на исходниках merge-base — нужен случай, "
                 "который краснеет без правки")
    return 1, lines


def check(repo, base, timeout):
    """Главная проверка → (код выхода, строки вывода)."""
    mb = git(repo, "merge-base", base, "HEAD").strip()
    tests, sources = classify(git(repo, "diff", "--name-status", "--no-renames", mb, "HEAD"))
    if not tests:
        return 0, [f"пропуск: PR не добавляет и не меняет тестов plugins/*/tests/test_*.py (merge-base {mb[:12]})"]
    if not sources:
        return 0, [f"пропуск: PR не меняет исходников — только тесты и документы (merge-base {mb[:12]})"]
    scratch = tempfile.mkdtemp(prefix="revert-check-")
    copy = os.path.join(scratch, "base")
    try:
        git(repo, "worktree", "add", "--detach", "--quiet", copy, mb)
        try:
            overlay_tests(repo, copy, sorted({p.split("/")[1] for p in tests}))
            results = {p: run_one(copy, p, timeout, scratch) for p in tests}
        finally:
            git(repo, "worktree", "remove", "--force", copy, check=False)
            git(repo, "worktree", "prune", check=False)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    code, lines = verdict(results)
    head = [f"merge-base {mb[:12]}; исходников в PR: {len(sources)}; тестов PR: {len(tests)}"]
    return code, head + lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="ловят ли новые тесты PR откат правки (metis-1176)")
    ap.add_argument("--base", default="origin/main", help="ветка base PR (по умолчанию origin/main)")
    ap.add_argument("--repo", default=".", help="корень репозитория (по умолчанию текущая папка)")
    ap.add_argument("--timeout", type=int, default=TIMEOUT, help=f"предел одного файла, с (по умолчанию {TIMEOUT})")
    a = ap.parse_args(argv)
    try:
        code, lines = check(os.path.abspath(a.repo), a.base, a.timeout)
    except (RuntimeError, OSError, tarfile.TarError) as e:
        print(f"revert-check: сбой — {e}", flush=True)
        return 2
    print("\n".join(lines), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
