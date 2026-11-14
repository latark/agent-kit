#!/usr/bin/env python3
"""revert_check.py [--base REF] [--repo DIR] [--timeout С] — ловят ли новые тесты PR откат правки (metis-1176).

  python3 -I plugins/pantheon/scripts/revert_check.py --base origin/main

Решение владельца 14.11: argus не гоняет тесты на Mac, поэтому проверку «новый тест ловит поломку» делает CI (job
revert-check в .github/workflows/tests.yml, необязательная проверка шлюза — OPTIONAL_CHECKS в merge_gate.py).

Что делает:
1. merge-base REF и HEAD; `git diff --name-status --no-renames <merge-base> HEAD` (переименование — удаление и
   добавление). Тесты — добавленные или изменённые `plugins/<плагин>/tests/test_*.py`. Исходники — любой изменённый
   путь вне `plugins/*/tests/` и не `*.md`. Поэтому PR, который правит только `*.md` и тест на их текст (линтер
   словаря, шапок), получает пропуск «нет исходников»: откат документа такой тест поймал бы, но мерить тут нечего.
2. Нет тестов или нет исходников — пропуск строкой с причиной, код 0.
3. Файлы из SKIP_NOT_MAC (вне macOS) и QUARANTINE раннера — пропуск с причиной. Списки, заглушки STUBS и платформа
   (RUN_TESTS_PLATFORM) берутся из scripts/run-tests.py загрузкой модуля, а не копией.
4. Две копии дерева (`git worktree add --detach` во временную папку, в конце убираются): на HEAD и на merge-base. В
   копию merge-base из HEAD целиком кладётся папка `tests/` каждого плагина с изменённым тестом: тесты, помощники
   `tests/_*.py` и fixtures. Исходники остаются от merge-base — это и есть откат правки.
5. Среда — как у run-tests.py: `<этот python> -I tests/<файл>` в папке плагина копии; свои HOME и TMPDIR (разные
   папки); окружение без PANTHEON_* (и PANTHEON_HOST), FORCE_COLOR и CLICOLOR_FORCE, с NO_COLOR=1, PYTHON_COLORS=0,
   RUN_TESTS_RUNNER=1; вне macOS — заглушки STUBS в PATH. Вывод — в файл, а не в трубу: внук с унаследованным stdout
   не держит ожидание до таймаута. Своя группа процессов, после выхода и по таймауту она гаснет (SIGKILL).
6. Каждый тест сначала идёт на HEAD. Упал на HEAD — «не мерило: падает и на HEAD» (среда, а не откат), в счёт не
   идёт. Остальные идут на merge-base. Хоть один упал там (код не 0, ImportError нового модуля, таймаут) — код 0 и
   строка «упал на merge-base: <файл>». Все зелёные — код 1 и последней строкой «тест не ловит откат: <файлы> зелёные на
   исходниках merge-base — нужен случай, который краснеет без правки». Мерила нет ни одного — пропуск, код 0.
   Сбой git или раннера (нет REF, нет merge-base) — код 2 и причина последней строкой.

Граница: случаи внутри файла с «пропущено: нужен macOS» на Linux зелёные и на HEAD, и на базе — такой файл даст
красную, хотя откат на macOS он поймал бы; проверка необязательная, решает argus. Только stdlib.
"""
import argparse
import importlib.util
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
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run-tests.py")


def load_runner(path=RUNNER):
    """Модуль run-tests.py (SKIP_NOT_MAC, QUARANTINE, STUBS, make_stubs, PLATFORM) — загрузкой, а не копией."""
    spec = importlib.util.spec_from_file_location("run_tests_for_revert", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def label(path):
    """plugins/<плагин>/tests/<файл> → метка раннера «<плагин>/<файл>»."""
    parts = path.split("/")
    return f"{parts[1]}/{parts[3]}"


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


def runner_skips(tests, rt, exists=os.path.exists):
    """(идут, [(файл, причина)]): SKIP_NOT_MAC вне macOS (если нет программы unless) и QUARANTINE раннера."""
    run, skipped = [], []
    for p in tests:
        lb = label(p)
        why = rt.SKIP_NOT_MAC.get(lb)
        if rt.PLATFORM != "darwin" and why and not (why[1] and exists(why[1])):
            skipped.append((p, f"нужен macOS — {why[0]}"))
        elif lb in rt.QUARANTINE:
            skipped.append((p, f"карантин раннера, задача {rt.QUARANTINE[lb]}"))
        else:
            run.append(p)
    return run, skipped


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


def base_env(rt, scratch):
    """Окружение файлов, как env0 у run-tests.py: без PANTHEON_*, с NO_COLOR; вне macOS — заглушки STUBS в PATH."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(DROP_ENV)}
    env.update(NO_COLOR="1", PYTHON_COLORS="0", RUN_TESTS_RUNNER="1")
    stubs, _ = rt.make_stubs(scratch)
    if stubs:
        env["PATH"] = stubs + os.pathsep + env.get("PATH", "")
    return env


def _killpg(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_one(copy, path, timeout, scratch, env0):
    """Один файл тестов в копии → (код или None при таймауте, хвост вывода). Вывод — в файл (не труба)."""
    _, plugin, _, name = path.split("/")
    d = tempfile.mkdtemp(prefix="job-", dir=scratch)
    home, tdir, out = os.path.join(d, "home"), os.path.join(d, "tmp"), os.path.join(d, "out.log")
    os.mkdir(home)
    os.mkdir(tdir)
    with open(out, "wb") as fh:
        proc = subprocess.Popen([sys.executable, "-I", os.path.join("tests", name)],
                                cwd=os.path.join(copy, "plugins", plugin), env={**env0, "HOME": home, "TMPDIR": tdir},
                                stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
        finally:
            _killpg(proc.pid)  # внуки файла тоже
            proc.wait()
    with open(out, encoding="utf-8", errors="replace") as fh:
        lines = [ln.rstrip() for ln in fh if ln.strip()]
    return code, lines[-TAIL:]


def _how(code):
    return "таймаут" if code is None else f"код {code}"


def verdict(results, notmeter=(), skipped=()):
    """{файл: (код | None, хвост)} на merge-base, [(файл, (код, хвост))] упавших на HEAD, [(файл, причина)] →
    (код выхода, строки итога)."""
    lines = [f"пропуск файла: {p} — {why}" for p, why in skipped]
    for p, (code, tail) in notmeter:
        lines.append(f"не мерило: падает и на HEAD — {p} ({_how(code)})")
        lines += [f"    {ln}" for ln in tail]
    failed = [p for p, (code, _) in results.items() if code != 0]
    green = [p for p, (code, _) in results.items() if code == 0]
    for p in failed:
        code, tail = results[p]
        lines.append(f"упал на merge-base: {p} ({_how(code)})")
        lines += [f"    {ln}" for ln in tail]
    lines += [f"зелёный на merge-base: {p}" for p in green]
    if not results:
        lines.append("пропуск: мерила нет — тесты PR пропущены раннером или падают и на HEAD")
        return 0, lines
    if failed:
        lines.append(f"ок: откат ловят {len(failed)} из {len(results)} тестов PR")
        return 0, lines
    lines.append(f"тест не ловит откат: {', '.join(green)} зелёные на исходниках merge-base — нужен случай, "
                 "который краснеет без правки")
    return 1, lines


def measure(repo, mb, tests, timeout, scratch, env0):
    """Прогон на HEAD, затем на merge-base для зелёных на HEAD → (результаты на базе, упавшие на HEAD)."""
    head, base = os.path.join(scratch, "head"), os.path.join(scratch, "base")
    try:
        git(repo, "worktree", "add", "--detach", "--quiet", head, "HEAD")
        on_head = {p: run_one(head, p, timeout, scratch, env0) for p in tests}
        notmeter = [(p, r) for p, r in on_head.items() if r[0] != 0]
        meter = [p for p in tests if on_head[p][0] == 0]
        results = {}
        if meter:
            git(repo, "worktree", "add", "--detach", "--quiet", base, mb)
            overlay_tests(repo, base, sorted({p.split("/")[1] for p in meter}))
            results = {p: run_one(base, p, timeout, scratch, env0) for p in meter}
        return results, notmeter
    finally:
        for c in (head, base):
            if os.path.isdir(c):
                git(repo, "worktree", "remove", "--force", c, check=False)
        git(repo, "worktree", "prune", check=False)


def check(repo, base, timeout, rt=None):
    """Главная проверка → (код выхода, строки вывода)."""
    mb = git(repo, "merge-base", base, "HEAD").strip()
    tests, sources = classify(git(repo, "diff", "--name-status", "--no-renames", mb, "HEAD"))
    if not tests:
        return 0, [f"пропуск: PR не добавляет и не меняет тестов plugins/*/tests/test_*.py (merge-base {mb[:12]})"]
    if not sources:
        return 0, [f"пропуск: PR не меняет исходников — только тесты и документы (merge-base {mb[:12]})"]
    if rt is None:
        try:
            rt = load_runner()
        except Exception as e:  # любой сбой загрузки раннера — код 2 с причиной
            raise RuntimeError(f"не загрузить {RUNNER}: {type(e).__name__}: {e}") from e
    run, skipped = runner_skips(tests, rt)
    scratch = tempfile.mkdtemp(prefix="revert-check-")
    try:
        results, notmeter = measure(repo, mb, run, timeout, scratch, base_env(rt, scratch)) if run else ({}, [])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    code, lines = verdict(results, notmeter, skipped)
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
