"""Решение guard внутри процесса теста (metis-1148, план 1.0 Т3): правила грузятся один раз, а каждый вызов хука —
fork этого процесса со своим контекстом. Запуск интерпретатора с загрузкой правил стоил 1,3–1,8 с на случай; fork —
миллисекунды.

    from _guard_inproc import call
    r = call(argv, env, stdin)               # → Result(returncode, stdout, stderr), как subprocess.run(text=True)
    r = call(argv, env, stdin, entry=True)   # вход guard.py (как _cached_main.py guard.py), без подмен шима

Два входа — те же, что у прежних подпроцессов:
- shim (по умолчанию) — как `python3 -I _guard_shim.py guard.py [argv]`: модуль правил guard_rules.py под именем
  guard и подмены шима (patch ниже, её же зовёт _guard_shim.py — текст подмен один);
- entry — как `python3 -I _cached_main.py guard.py [argv]`: вход guard.py, его решение «молчать» и guard_rules.

Изоляция. Родитель только грузит модули (и merge_gate.py заранее) и ни одного вызова не решает сам. Ребёнок получает
копию нетронутого после загрузки процесса: кэши разбора, глобальные guard и подмены у каждого вызова свои и пропадают
с ним. Контекст вызова ребёнок ставит так же, как демон хуков (hooks/daemon.py, проверка — test_context.py): sys.argv,
os.environ ровно из env, затем configure() модулей; tempfile забывает папку родителя. stdin — файл с событием,
stdout и stderr — файлы; код выхода — os._exit хука (run_hook и guard.run не возвращаются). Ребёнок, переживший
срок, гасится SIGKILL — как timeout у subprocess.run.

Нельзя: fork из процесса, где другие потоки зовут guard (пул потоков test_shell_diff в песочнице) — там call не
годится, тест берёт подпроцесс. Поток-сторож _orphan_pool (getppid и sleep) не мешает.
"""
import importlib.util
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections import namedtuple

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
GUARD = os.path.join(HOOKS, "guard.py")
SUB_TIMEOUT = 60  # как у подпроцессов тестов (metis-0634)
Result = namedtuple("Result", "returncode stdout stderr")
_mods = {}
_work = {}


def load_rules(path=GUARD):
    """guard_rules.py рядом с path — модулем guard, как в шиме (_guard_shim.py)."""
    spec = importlib.util.spec_from_file_location("guard", os.path.join(os.path.dirname(path), "guard_rules.py"))
    g = importlib.util.module_from_spec(spec)
    sys.modules["guard"] = g
    spec.loader.exec_module(g)
    return g


def _getaddrinfo(real):
    def resolve(host, port, *a, **kw):
        for fam in (socket.AF_INET, socket.AF_INET6):
            try:
                socket.inet_pton(fam, host)
                return real(host, port, *a, **kw)
            except (OSError, TypeError):
                pass
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]
    return resolve


def patch(g, path=GUARD):
    """Подмены шима (_guard_shim.py, metis-0090, 0094, 0763) поверх модуля правил g в контексте этого процесса: HOME и
    переменные GUARD_SHIM_* — из os.environ. Зовётся после configure(): MARKET_GUARD тот ставит заново.
    1. Временный HOME тестов лежит во временной папке: для путей внутри HOME корни, в которых лежит сам HOME, из
       TEMP_ROOTS не берутся (иначе guard разрешал бы запись во всё ~/ai/pantheon теста).
    2. Разрешение имён без сети: имя — публичный адрес 93.184.216.34, IP — сам в себя.
    3. GUARD_SHIM_BOOM=<имя>[,<имя>] — функция модуля (или merge_gate.record) бросает исключение; GUARD_SHIM_HANG=<имя>
       — висит 15 с, срок guard — GUARD_SHIM_DEADLINE с. Иначе сроки guard и его git/gh не короче 45/40 с: тест
       проверяет правила, а не скорость машины.
    4. GUARD_SHIM_MANAGED — файл управляемых настроек вместо настоящего."""
    socket.getaddrinfo = _getaddrinfo(socket.getaddrinfo)
    home = g._key(os.path.realpath(os.environ["HOME"]))
    orig_inside = g._inside

    def inside(p, roots):
        if g._key(p).startswith(home.rstrip("/") + "/") or g._key(p) == home:
            roots = [r for r in roots
                     if not (r in g.TEMP_ROOTS and (home + "/").startswith(g._key(r).rstrip("/") + "/"))]
        return orig_inside(p, roots)

    g._inside = inside

    def target(name):
        obj, attr = g, name
        if "." in name:
            mod, attr = name.split(".", 1)
            obj = getattr(g, mod)
        return obj, attr

    def boom(*a, **kw):
        raise RuntimeError("искусственный сбой")

    def hang(*a, **kw):
        time.sleep(15)

    for name in filter(None, os.environ.get("GUARD_SHIM_BOOM", "").split(",")):
        setattr(*target(name), boom)
    if os.environ.get("GUARD_SHIM_HANG"):
        setattr(*target(os.environ["GUARD_SHIM_HANG"]), hang)
        g.DEADLINE = float(os.environ.get("GUARD_SHIM_DEADLINE") or 1)
    else:
        g.DEADLINE = max(g.DEADLINE, 45)
        real_run = subprocess.run

        def run(*a, **kw):
            if kw.get("timeout") is not None:
                kw["timeout"] = max(kw["timeout"], 40)
            return real_run(*a, **kw)

        subprocess.run = run
    if os.environ.get("GUARD_SHIM_MANAGED"):
        g.MANAGED_FILE, g.MARKET_GUARD = os.environ["GUARD_SHIM_MANAGED"], path


def _loaded(entry):
    """Модули входа, загруженные в этом процессе один раз; merge_gate.py — тоже сразу, чтобы дети его не грузили."""
    key = "entry" if entry else "shim"
    if key not in _mods:
        if entry:
            if "guard" in sys.modules and sys.modules["guard"].__file__ != GUARD:
                raise RuntimeError("_guard_inproc: в процессе уже модуль правил под именем guard (вход shim)")
            sys.path.insert(0, HOOKS)
            import guard
            import guard_rules
            guard_rules._mg()
            _mods[key] = guard
        else:
            if "entry" in _mods:
                raise RuntimeError("_guard_inproc: в процессе уже вход guard.py (entry) — shim не смешивать")
            g = load_rules()
            g._mg()
            _mods[key] = g
    return _mods[key]


def _files():
    pid = os.getpid()
    if pid not in _work:  # своя папка у каждого процесса: _par раздаёт случаи по fork
        _work[pid] = [tempfile.mkdtemp(prefix="guard-inproc-"), 0]
    w = _work[pid]
    w[1] += 1
    return [os.path.join(w[0], f"{w[1]}.{x}") for x in ("in", "out", "err")]


def _child(mod, entry, argv, env, fin, fout, ferr):
    for fd, path, flags in ((0, fin, os.O_RDONLY), (1, fout, os.O_WRONLY | os.O_CREAT | os.O_TRUNC),
                            (2, ferr, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)):
        f = os.open(path, flags, 0o600)
        os.dup2(f, fd)
        os.close(f)
    sys.stdin = open(0, encoding="utf-8", closefd=False)
    sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
    sys.stderr = open(2, "w", encoding="utf-8", errors="backslashreplace", closefd=False)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    tempfile.tempdir = None  # как у нового процесса: папка — из TMPDIR вызова
    if entry:
        mod.set_context(list(argv), env)  # sys.argv, os.environ, configure() guard, guard_rules, taint
        mod.run(list(argv))
    else:
        sys.argv = [GUARD] + list(argv)
        os.environ.clear()
        os.environ.update(env)
        mod.configure()
        patch(mod)
        mod.run_hook()


def call(argv, env, stdin, entry=False, timeout=SUB_TIMEOUT):
    """Вызов хука с событием stdin (str) в окружении env и аргументами argv → Result. Срок вышел — SIGKILL ребёнку и
    subprocess.TimeoutExpired, как у subprocess.run."""
    mod = _loaded(entry)
    fin, fout, ferr = _files()
    with open(fin, "w", encoding="utf-8") as fh:
        fh.write(stdin)
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid == 0:
        try:
            _child(mod, entry, argv, env, fin, fout, ferr)
        finally:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            finally:
                os._exit(99)  # хук вернулся, а не вышел сам — такого быть не должно
    end, pause = time.monotonic() + timeout, 0.0005
    while True:
        done, st = os.waitpid(pid, os.WNOHANG)
        if done:
            break
        if time.monotonic() > end:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            raise subprocess.TimeoutExpired([GUARD, *argv], timeout)
        time.sleep(pause)
        pause = min(pause * 2, 0.02)
    res = Result(os.waitstatus_to_exitcode(st), *(open(f, encoding="utf-8").read() for f in (fout, ferr)))
    for f in (fin, fout, ferr):
        os.remove(f)
    return res
