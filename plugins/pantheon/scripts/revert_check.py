#!/usr/bin/env python3
"""revert_check.py [--base REF] [--repo DIR] [--timeout С] [-j N] [--budget С] — ловят ли тесты PR откат (metis-1176).

  python3 -I plugins/pantheon/scripts/revert_check.py --base origin/main

Решение владельца 14.11: argus не гоняет тесты на Mac, поэтому проверку «новый тест ловит поломку» делает CI (job
revert-check в .github/workflows/tests.yml, необязательная проверка шлюза — OPTIONAL_CHECKS в merge_gate.py).

Итог — последняя строка вывода, всегда вида «итог: <статус> — <почему>» (metis-1182). Статус и код выхода:
  ловит      0  хоть один тест PR упал на исходниках merge-base;
  пропуск    0  мерить нечего: PR не меняет исходников, или тесты PR пропущены раннером либо падают и на HEAD;
  не ловит   1  все тесты-мерила зелёные на merge-base;
  сбой       2  git, раннер, копия дерева;
  не мерили  3  PR меняет исходники, а тестов не добавляет и не меняет, или прогон не уложился в --budget;
  прервано   4  job отменён (SIGTERM или SIGINT): итога нет — это не «не ловит».
Красная проверка в `gh pr checks` бывает любой из 1–4: класс находки — по этой строке. В CI она же идёт в сводку шага
($GITHUB_STEP_SUMMARY) и аннотацией (::warning, у «ловит» и «пропуск» — ::notice), их видно в `gh run view`.

Что делает:
1. merge-base REF и HEAD; `git diff --name-status --no-renames <merge-base> HEAD` (переименование — удаление и
   добавление). Тесты — добавленные или изменённые `plugins/<плагин>/tests/test_*.py`. Исходники — любой изменённый
   путь вне `plugins/*/tests/` и не `*.md`. Поэтому PR, который правит только `*.md` и тест на их текст (линтер
   словаря, шапок), получает пропуск «нет исходников»: откат документа такой тест поймал бы, но мерить тут нечего.
2. Нет исходников — «пропуск», код 0. Исходники без тестов — «не мерили», код 3: зелёный пропуск скрыл бы PR, который
   добавляет код без ловящего теста (Д1 argus #462).
3. Файлы из SKIP_NOT_MAC (вне macOS) и QUARANTINE раннера — пропуск с причиной. Списки, пределы SLOW и TIMEOUT,
   заглушки STUBS и платформа (RUN_TESTS_PLATFORM) берутся из scripts/run-tests.py загрузкой модуля, а не копией
   (`--runner` — другой файл раннера, для тестов).
4. Две копии дерева (`git worktree add --detach` во временную папку, в конце убираются): на HEAD и на merge-base. В
   копию merge-base из HEAD целиком кладётся папка `tests/` каждого плагина с изменённым тестом: тесты, помощники
   `tests/_*.py` и fixtures. Исходники остаются от merge-base — это и есть откат правки.
5. Среда — как у run-tests.py: `<этот python> -I tests/<файл>` в папке плагина копии; свои HOME и TMPDIR (разные
   папки); окружение без PANTHEON_* (и PANTHEON_HOST), FORCE_COLOR и CLICOLOR_FORCE, с NO_COLOR=1, PYTHON_COLORS=0,
   RUN_TESTS_RUNNER=1; вне macOS — заглушки STUBS в PATH. Вывод — в файл, а не в трубу: внук с унаследованным stdout
   не держит ожидание до таймаута. Своя группа процессов, после выхода и по таймауту она гаснет (SIGKILL).
   Предел файла — `--timeout`, без него SLOW раннера для этой метки, иначе его TIMEOUT: тяжёлый тест не уходит
   в «не мерило» по чужому пределу.
6. Файлы идут по -j штук сразу (по умолчанию как у раннера: min(ядра // 2, 3)), сначала все на HEAD. Упал на HEAD —
   «не мерило: падает и на HEAD» (среда, а не откат), в счёт не идёт. Остальные идут на merge-base. Весь прогон —
   не дольше --budget (по умолчанию 25 мин при пределе job 30 мин): файл, который не начат или оборван пределом
   прогона, — «не успел», а не таймаут и не «упал». Хоть один упал на merge-base (код не 0, ImportError нового
   модуля, свой таймаут) — «ловит». Иначе есть «не успел» — «не мерили». Иначе все зелёные — «не ловит».
   В выводе упавшего — строки с «НЕ ПРОШЁЛ», FAIL, Traceback, Error (до MARK_CAP) и последние TAIL строк.

Граница: случаи внутри файла с «пропущено: нужен macOS» на Linux зелёные и на HEAD, и на базе — такой файл даст
«не ловит», хотя откат на macOS он поймал бы; проверка необязательная, решает argus. Только stdlib.
"""
import argparse
import concurrent.futures
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

TEST_PREFIX = "plugins/"
DROP_ENV = ("PANTHEON_", "FORCE_COLOR", "CLICOLOR_FORCE")
BUDGET = 25 * 60  # с на весь прогон: job revert-check — timeout-minutes 30, остальное — checkout и setup-python
TAIL = 5  # последних строк вывода упавшего теста в итоге
MARKS = ("НЕ ПРОШЁЛ", "FAIL", "Traceback", "Error")  # строки причины падения — в итог, где бы они ни стояли
MARK_CAP = 10  # строк причины на файл, не больше
LINE_CAP = 300  # знаков на строку итога
LATE = "late"  # код файла, который не начат или оборван пределом прогона
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run-tests.py")
CODES = {"ловит": 0, "пропуск": 0, "не ловит": 1, "сбой": 2, "не мерили": 3, "прервано": 4}


class Interrupted(BaseException):
    """job отменён: SIGTERM или SIGINT (BaseException: `except Exception` его не глотает)."""


class Pool:
    """Запущенные группы процессов: по отмене гаснут все, новые не стартуют."""

    def __init__(self):
        self.lock = threading.Lock()
        self.pids = set()
        self.stop = False

    def add(self, pid):
        with self.lock:
            self.pids.add(pid)
            stop = self.stop
        if stop:
            _killpg(pid)

    def done(self, pid):
        with self.lock:
            self.pids.discard(pid)

    def kill_all(self):
        with self.lock:
            self.stop = True
            pids = list(self.pids)
        for pid in pids:
            _killpg(pid)


POOL = Pool()


def load_runner(path=RUNNER):
    """Модуль run-tests.py (SKIP_NOT_MAC, QUARANTINE, SLOW, TIMEOUT, STUBS, make_stubs, PLATFORM) — загрузкой."""
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


def file_limit(path, rt, override=None):
    """Предел файла, с: --timeout, иначе SLOW раннера для метки, иначе TIMEOUT раннера."""
    return override or rt.SLOW.get(label(path)) or rt.TIMEOUT


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


def pick_lines(lines, n=TAIL):
    """Строки итога упавшего файла: с MARKS (до MARK_CAP) и последние n; пропуск между ними — «…»."""
    hit = [i for i, ln in enumerate(lines) if any(m in ln for m in MARKS)][:MARK_CAP]
    idx = sorted(set(hit) | set(range(max(0, len(lines) - n), len(lines))))
    out, prev = [], None
    for i in idx:
        if prev is not None and i != prev + 1:
            out.append("…")
        out.append(lines[i][:LINE_CAP])
        prev = i
    return out


def run_one(copy, path, timeout, scratch, env0, deadline):
    """Один файл тестов в копии → (код | None при своём таймауте | LATE, строки вывода). Вывод — в файл."""
    left = deadline - time.monotonic()
    if left <= 0 or POOL.stop:
        return LATE, []
    limit = min(timeout, left)
    _, plugin, _, name = path.split("/")
    d = tempfile.mkdtemp(prefix="job-", dir=scratch)
    home, tdir, out = os.path.join(d, "home"), os.path.join(d, "tmp"), os.path.join(d, "out.log")
    os.mkdir(home)
    os.mkdir(tdir)
    with open(out, "wb") as fh:
        proc = subprocess.Popen([sys.executable, "-I", os.path.join("tests", name)],
                                cwd=os.path.join(copy, "plugins", plugin), env={**env0, "HOME": home, "TMPDIR": tdir},
                                stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        POOL.add(proc.pid)
        try:
            code = proc.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            code = LATE if limit < timeout else None
        finally:
            _killpg(proc.pid)  # внуки файла тоже
            proc.wait()
            POOL.done(proc.pid)
    with open(out, encoding="utf-8", errors="replace") as fh:
        lines = [ln.rstrip() for ln in fh if ln.strip()]
    return code, pick_lines(lines)


def run_many(copy, paths, ctx):
    """Файлы по ctx["jobs"] штук сразу → {файл: (код, строки)}; отмена гасит запущенные и не ждёт остальных."""
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, ctx["jobs"]))
    try:
        futs = {p: ex.submit(run_one, copy, p, ctx["limit"](p), ctx["scratch"], ctx["env"], ctx["deadline"])
                for p in paths}
        return {p: f.result() for p, f in futs.items()}
    except BaseException:
        POOL.kill_all()
        raise
    finally:
        ex.shutdown(wait=True, cancel_futures=True)


def _how(code):
    return {None: "таймаут", LATE: "не успел"}.get(code, f"код {code}")


def _block(head, tail):
    return [head] + [f"    {ln}" for ln in tail]


def verdict(results, notmeter=(), skipped=(), late=()):
    """{файл: (код, строки)} на merge-base, [(файл, (код, строки))] упавших на HEAD, [(файл, причина)] пропущенных,
    [файл] не успевших на HEAD → (статус, строки итога без последней, текст последней)."""
    lines = [f"пропуск файла: {p} — {why}" for p, why in skipped]
    for p, (code, tail) in notmeter:
        lines += _block(f"не мерило: падает и на HEAD — {p} ({_how(code)})", tail)
    late = list(late) + [p for p, (code, _) in results.items() if code == LATE]
    failed = [p for p, (code, _) in results.items() if code not in (0, LATE)]
    green = [p for p, (code, _) in results.items() if code == 0]
    for p in failed:
        lines += _block(f"упал на merge-base: {p} ({_how(results[p][0])})", results[p][1])
    lines += [f"зелёный на merge-base: {p}" for p in green]
    lines += [f"не успел: {p} — предел прогона --budget" for p in late]
    if failed:
        return "ловит", lines, f"откат ловят {len(failed)} из {len(failed) + len(green) + len(late)} тестов PR"
    if late:
        return "не мерили", lines, (f"не успели {len(late)} тестов PR за предел прогона — итога по откату нет; "
                                    "поднять --budget или -j")
    if not green:
        return "пропуск", lines, "мерила нет — тесты PR пропущены раннером или падают и на HEAD"
    return "не ловит", lines, (f"{', '.join(green)} зелёные на исходниках merge-base — нужен случай, который "
                               "краснеет без правки")


def measure(repo, mb, tests, ctx):
    """Прогон на HEAD, затем на merge-base для зелёных на HEAD → (результаты на базе, упавшие на HEAD, не успевшие)."""
    head, base = os.path.join(ctx["scratch"], "head"), os.path.join(ctx["scratch"], "base")
    try:
        git(repo, "worktree", "add", "--detach", "--quiet", head, "HEAD")
        on_head = run_many(head, tests, ctx)
        late = [p for p in tests if on_head[p][0] == LATE]
        notmeter = [(p, r) for p, r in on_head.items() if r[0] not in (0, LATE)]
        meter = [p for p in tests if on_head[p][0] == 0]
        results = {}
        if meter:
            git(repo, "worktree", "add", "--detach", "--quiet", base, mb)
            overlay_tests(repo, base, sorted({p.split("/")[1] for p in meter}))
            results = run_many(base, meter, ctx)
        return results, notmeter, late
    finally:
        for c in (head, base):
            if os.path.isdir(c):
                git(repo, "worktree", "remove", "--force", c, check=False)
        git(repo, "worktree", "prune", check=False)


def check(repo, base, opts):
    """Главная проверка → (статус, строки вывода без итога, текст итога)."""
    mb = git(repo, "merge-base", base, "HEAD").strip()
    tests, sources = classify(git(repo, "diff", "--name-status", "--no-renames", mb, "HEAD"))
    if not sources:
        return "пропуск", [], f"PR не меняет исходников — только тесты и документы (merge-base {mb[:12]})"
    if not tests:
        return "не мерили", [f"исходники PR: {', '.join(sources[:10])}" + (" …" if len(sources) > 10 else "")], (
            f"PR меняет исходники ({len(sources)}), но не добавляет и не меняет тестов plugins/*/tests/test_*.py — "
            f"откат не проверен (merge-base {mb[:12]})")
    try:
        rt = load_runner(opts["runner"])
    except Exception as e:  # любой сбой загрузки раннера — «сбой» с причиной
        raise RuntimeError(f"не загрузить {opts['runner']}: {type(e).__name__}: {e}") from e
    run, skipped = runner_skips(tests, rt)
    scratch = tempfile.mkdtemp(prefix="revert-check-")
    try:
        ctx = {"jobs": opts["jobs"], "scratch": scratch, "deadline": opts["deadline"], "env": base_env(rt, scratch),
               "limit": lambda p: file_limit(p, rt, opts["timeout"])}
        results, notmeter, late = measure(repo, mb, run, ctx) if run else ({}, [], [])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    status, lines, final = verdict(results, notmeter, skipped, late)
    head = [f"merge-base {mb[:12]}; исходников в PR: {len(sources)}; тестов PR: {len(tests)}; -j {opts['jobs']}"]
    return status, head + lines, final


def report_ci(final, status, env=None):
    """В CI — итог в сводку шага ($GITHUB_STEP_SUMMARY) и аннотацией: argus видит его в `gh run view`."""
    env = os.environ if env is None else env
    if env.get("GITHUB_ACTIONS") == "true":
        kind = "notice" if CODES[status] == 0 else "warning"
        print(f"::{kind} title=revert-check: {status}::{final}", flush=True)
    path = env.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"### revert-check: {status}\n\n{final}\n")
        except OSError as e:
            print(f"revert-check: сводка шага не записана — {e}", flush=True)


def _interrupt(signum, _frame):
    for s in (signal.SIGTERM, signal.SIGINT):  # второй сигнал не рвёт уборку копий дерева
        signal.signal(s, signal.SIG_IGN)
    raise Interrupted(signal.Signals(signum).name)


def default_jobs():
    return max(1, min((os.cpu_count() or 2) // 2, 3))


def main(argv=None):
    ap = argparse.ArgumentParser(description="ловят ли новые тесты PR откат правки (metis-1176)")
    ap.add_argument("--base", default="origin/main", help="ветка base PR (по умолчанию origin/main)")
    ap.add_argument("--repo", default=".", help="корень репозитория (по умолчанию текущая папка)")
    ap.add_argument("--timeout", type=int, default=None, help="предел одного файла, с (по умолчанию SLOW/TIMEOUT раннера)")
    ap.add_argument("-j", "--jobs", type=int, default=default_jobs(), help="файлов сразу (по умолчанию как у раннера)")
    ap.add_argument("--budget", type=int, default=BUDGET, help=f"предел всего прогона, с (по умолчанию {BUDGET})")
    ap.add_argument("--runner", default=RUNNER, help="файл run-tests.py (по умолчанию соседний)")
    a = ap.parse_args(argv)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, _interrupt)
    opts = {"timeout": a.timeout, "jobs": a.jobs, "deadline": time.monotonic() + a.budget, "runner": a.runner}
    try:
        status, lines, final = check(os.path.abspath(a.repo), a.base, opts)
    except Interrupted as e:
        POOL.kill_all()
        status, lines, final = "прервано", [], f"job отменён ({e}) — итога нет; это не «не ловит», нужен перезапуск"
    except (RuntimeError, OSError, tarfile.TarError) as e:
        status, lines, final = "сбой", [], f"{e}"
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, signal.SIG_DFL)
    if lines:
        print("\n".join(lines), flush=True)
    report_ci(final, status)
    print(f"итог: {status} — {final}", flush=True)
    return CODES[status]


if __name__ == "__main__":
    sys.exit(main())
