#!/usr/bin/env python3
"""run-tests.py <папка плагина> … — параллельный прогон файлов тестов плагинов, в духе prove (metis-0450).

  heavy python3 -I plugins/pantheon/scripts/run-tests.py plugins/guard plugins/pantheon
  -j N            воркеров (по умолчанию min(ядра // 2, 3), при load1 выше числа ядер — 1)
  --timeout С     предел одного файла, с (по умолчанию TIMEOUT; у медленных файлов свой — SLOW)
  --log-dir ПАПКА полный вывод каждого файла — в ПАПКА/<плагин>__<файл>.log
  --affected      только затронутое (metis-0451): файлы тестов, связанные с изменёнными файлами, по карте MAP
  --base REF      база для --affected (по умолчанию origin/main)

На macOS с /usr/sbin/taskpolicy каждый файл идёт через `taskpolicy -c utility` (launchd держит плановый проход в QoS
background, файл ×3 дольше, metis-0728); в начале прогона печатается строка «QoS (доля CPU)» — проба раннера и файла.
Файлам виден RUN_TESTS_RUNNER=1 (test_shell_diff по нему берёт пул из двух процессов).

Только затронутое — для агента во время правки и для PR; полный набор — без ключа (на main, в шлюзе и перед
выпуском). Изменённые файлы — `git diff --no-renames` рабочего дерева от merge-base REF и HEAD, плюс новые файлы вне
.gitignore. Карта MAP (scripts/affected-map.json) построена прогоном: какой файл тестов какой файл репозитория
загрузил, открыл или запустил (как — шапка scripts/affected-map.py). Каждый изменённый файл (путь от корня):
  - общий (FULL: lib/pantheon.py, hooks/python.sh, сам раннер, карта) — весь набор;
  - сам tests/test_*.py одной из папок — он сам; удалённый файл тестов — ничего;
  - есть в карте — его файлы тестов; пустой список — файл не задел ни один тест (AGENTS.md);
  - иначе (новый файл, карты нет или она другой версии) — весь набор: неизвестное гоняет всё.
Файлы тестов, которых карта не знает (новые после её сборки) или которые при сборке упали (broken), идут всегда.
Карта хранит sha256 каждого файла тестов (hashes): файл, изменённый после сборки (хеш другой), мог начать задевать новые
файлы — его связи не верны, и он идёт при любом изменении (в выводе: «изменены после сборки карты»); таких файлов
STALE_FULL и больше — карта устарела целиком, весь набор с причиной. Так правка теста после сборки не пропускает нужные
тесты из-за старой карты; карту пересобирают, когда таких файлов набралось.
Тесты плагинов, которых нет в аргументах, не идут. Изменений нет или ни один не ведёт к тестам — код 3 и строка
«нечего гонять», а не пустой зелёный. Ошибка git (нет базы, не репозиторий, мелкий клон без merge-base) — весь
набор и причина строкой: при сомнении раннер гоняет всё, а не ничего.

Не macOS (CI на Linux, п. 1 пачки «Скорость»): файлы из SKIP_NOT_MAC не идут, а печатаются строкой `skip … · пропущено:
нужен macOS — причина` и считаются в итоге отдельным числом — это не «ok» и не «FAIL»; нужной программы (unless) нет — файл
пропускается, есть — идёт. Команд macOS, которых на PATH нет (ioreg, pmset, scutil), файлы тестов получают как заглушки
из STUBS (папка в PATH, строка «заглушки» в начале прогона): код с ними не ходит к системе, а гоняется. Платформу для
проверки раннера подменяет RUN_TESTS_PLATFORM (по умолчанию sys.platform). Полный прогон на macOS ничего не пропускает.

Каждый tests/test_*.py — отдельный процесс `<этот python> -I tests/<файл>` в папке плагина: свой HOME и TMPDIR во
временной папке прогона, окружение без PANTHEON_*, FORCE_COLOR и CLICOLOR_FORCE, с NO_COLOR=1. Тесты идут на
Python 3.11+ (metis-0571); тот же скрипт гоняет workflow tests в GitHub Actions на 3.14 (.github/workflows/tests.yml).

Порядок: сначала медленные (SLOW, по замеру), затем остальные по имени. Файлы SERIAL идут в конце по одному, когда
больше ничего не идёт: им параллель мешает.

Процессы. Файл тестов — в своей сессии и группе процессов (start_new_session). По таймауту файла гаснет вся его
группа (killpg SIGKILL), и после обычного выхода файла — тоже: оставленные им внуки не грузят Mac. SIGTERM, SIGHUP и SIGINT раннеру гасят группы всех идущих файлов, и раннер выходит с кодом 128 +
номер сигнала. Так таймаут задачи (run_job: группе задачи SIGTERM, через 5 с SIGKILL) и heavy, который передаёт
сигнал дальше, не оставляют сирот. Границы: внук, который сам ушёл в свою сессию (setsid), из группы файла выпадает,
и killpg его не достаёт; SIGKILL самому раннеру обработать нельзя — идущие файлы тогда доживают свой таймаут.

Итог: строка на каждый файл по мере готовности (ok / FAIL, время, число проверок), затем выводы упавших файлов
(хвост) и последняя строка — файлов, ok, FAIL, сумма проверок, время. Код выхода не 0, если: нет ни одного файла
тестов, файл упал (код не 0), превысил таймаут, вышел с кодом 0 без строки итога (кроме старых файлов NO_SUMMARY)
или с итогом без проверок, или раннер прерван сигналом. Число проверок файла — из его итоговой строки, без числа в ней — по строкам `ok`.
Только stdlib.
"""
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

TIMEOUT = 600  # с на файл; медленным — свой предел в SLOW
# Медленные файлы: идут первыми (по убыванию предела), предел — свой, с. metis-0634: пределы — по 31 полному прогону
# прохода outside 30.10–01.11 (-j 3, процесс тика ProcessType Background, Mac под нагрузкой): 1.5 × наибольшего
# зелёного времени файла с округлением вверх до минуты, не меньше 180 с. Прежние (3 × последовательного замера 27.10)
# давали таймауты: test_merge_gate — 19 из 33 прогонов, test_watch — 10 из 31, test_read — 9 из 31.
# В комментарии — медиана и наибольшее зелёное время в тех прогонах, с.
SLOW = {
    "pantheon/test_watch.py": 1020,  # 516 / 666 — дольше всех: полный прогон не короче его
    "guard/test_merge_gate.py": 900,  # 458 / 458 (зелёный один); один воркер под outside — 333-358
    "guard/test_guard.py": 720,  # 336 / 442; на Linux в Docker под нагрузкой 120-240 с, на 2-ядерном ubuntu-latest дольше
    "guard/test_shell_diff.py": 600,  # 254 / 390
    "pantheon/test_plugins_update.py": 540,  # 170 / 346
    "pantheon/test_setup.py": 480,  # 109 / 303
    "pantheon/test_start.py": 480,  # 136 / 289
    "pantheon/test_board.py": 360,  # 98 / 235
    "pantheon/test_sync_quarantine.py": 360,  # 120 / 231
    "pantheon/test_read.py": 300,  # 97 / 179
    "pantheon/test_merge.py": 300,  # 86 / 171
    "pantheon/test_hooks.py": 300,  # 64 / 163
    "pantheon/test_executors.py": 240,  # 69 / 158
    "pantheon/test_tick.py": 240,  # 56 / 160
    "pantheon/test_owner_log_gap.py": 180,  # 41 / 80
    "pantheon/test_notify.py": 180,  # 35 / 88
    "pantheon/test_autoclose.py": 180,  # 22 / 69
    "pantheon/test_board_metrics.py": 180,  # 19 / 42
}
# Файлы, которым параллель мешает: идут в конце по одному.
SERIAL = ()
# Файлы, которые и на main кончаются последней строкой ok без строки итога (замер metis-0450): у них код 0 со строками
# ok и без строк FAIL — зелёный. Новый файл без итога сюда не попадает и остаётся красным; файл, получивший итог,
# из списка убрать.
NO_SUMMARY = frozenset({
    "guard/test_canaries.py",
    "guard/test_misc.py",
    "guard/test_tg_self.py",
    "pantheon/test_board_drift.py",
    "pantheon/test_merge.py",  # «все прошли» — без числа, TEST_SUMMARY его не берёт
    "pantheon/test_path_clean.py",
    "pantheon/test_read.py",  # «все прошли»
})
# Файлы, которые не идут вне macOS: метка → (причина, unless — программа, при наличии которой файл идёт, или None).
# Явный список: пропуск виден строкой в прогоне и числом в итоге, а не молчаливым выходом самого файла. Замер на Linux
# (python:3.14, не root, zip как на ubuntu-latest): остальные файлы проходят с заглушками STUBS.
SKIP_NOT_MAC = {
    "pantheon/test_setup.py": ("установщик pantheon-setup поддерживает только macOS", None),
}
# Команды macOS, которых нет на Linux: заглушка с выводом, при котором код идёт обычным путём.
STUBS = {"ioreg": "exit 0", "pmset": 'echo "Now drawing from AC Power"', "scutil": "echo linux-host"}
PLATFORM = os.environ.get("RUN_TESTS_PLATFORM") or sys.platform
# Карта для --affected (metis-0451): строит scripts/affected-map.py прогоном всех тестов, правится только им.
MAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "affected-map.json")
MAP_VERSION = 2
# Карта старше файла тестов (правка после сборки): связи этого файла по карте неверны, файл идёт всегда. Столько файлов
# и больше — карта устарела целиком: весь набор с причиной в выводе.
STALE_FULL = 8
# Общие файлы: их правка гонит весь набор, что бы ни говорила карта (их грузит почти каждый тест или они меняют
# сам выбор тестов).
FULL = frozenset({
    "plugins/pantheon/lib/pantheon.py",
    "plugins/pantheon/lib/run.py",
    "plugins/pantheon/lib/find-python.sh",
    "plugins/pantheon/hooks/python.sh",
    "plugins/guard/hooks/python.sh",
    "plugins/pantheon/scripts/run-tests.py",
    "plugins/pantheon/scripts/affected-map.py",
    "plugins/pantheon/scripts/affected-map.json",
})

# Строка итога файла — последняя непустая строка вывода. Прежде такая же копия в pantheon.py разбирала вывод локального
# прогона автоустановки; его больше нет (п. 8 страницы упрощения 27.10), раннер — единственное место.
TEST_SUMMARY = re.compile(r"(?:\d+\s*(?:из\s+\d+|/\s*\d+|команд\b)|тестов:\s*\d+|(?:OK|FAIL)\s+\d+$|ПРОВАЛ\b)")
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-_])")
_SUMMARY_TOTAL = (
    (re.compile(r"тестов:\s*(\d+)\s+прошло,\s*(\d+)\s+не\s+прошло"), lambda m: int(m[1]) + int(m[2])),
    (re.compile(r"\d+\s*из\s+(\d+)"), lambda m: int(m[1])),
    (re.compile(r"\d+\s*/\s*(\d+)"), lambda m: int(m[1])),
    (re.compile(r"тестов:\s*(\d+)"), lambda m: int(m[1])),
    (re.compile(r"(\d+)\s*команд\b"), lambda m: int(m[1])),
)
SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
TAIL = 40  # строк вывода упавшего файла в итог


class Interrupted(Exception):
    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def workers(cpus, load):
    """Сколько файлов гонять сразу: min(ядра // 2, 3), не меньше одного; Mac перегружен (load1 > ядер) — один."""
    cpus = cpus or 1
    if load is not None and load > cpus:
        return 1
    return max(1, min(cpus // 2, 3))


def load1():
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def collect(pdirs):
    """[(папка плагина, метка «плагин/файл»)] — все tests/test_*.py указанных папок."""
    items = []
    for pdir in pdirs:
        tdir = os.path.join(pdir, "tests")
        if not os.path.isdir(tdir):
            continue
        name = os.path.basename(os.path.normpath(os.path.abspath(pdir)))
        for f in sorted(os.listdir(tdir)):
            if f.startswith("test_") and f.endswith(".py"):
                items.append((os.path.abspath(pdir), f"{name}/{f}"))
    return items


class GitError(Exception):
    pass


def _git(cwd, *args):
    r = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=cwd, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GitError(f"git {' '.join(args[:2])}: {err[-1] if err else f'код {r.returncode}'}")
    return r.stdout.decode("utf-8", "replace")


def changed_files(pdir, base):
    """(корень репозитория, короткий sha merge-base, [пути от корня]) — изменённое рабочим деревом от merge-base base и
    HEAD (закоммиченное, в индексе, не в индексе, удалённое) и новые файлы вне .gitignore."""
    root = _git(pdir, "rev-parse", "--show-toplevel").strip()
    mb = _git(root, "merge-base", base, "HEAD").strip()
    names = _git(root, "diff", "--name-only", "--no-renames", "-z", mb, "--").split("\0")
    names += _git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return root, mb[:7], sorted({n for n in names if n})


def load_map(path=None):
    """(карта {"tests": {метка}, "always": {метка}, "files": {путь: {метка}}} или None, почему None)."""
    path = MAP if path is None else path
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if raw.get("version") != MAP_VERSION:
            return None, f"карта {os.path.basename(path)} версии {raw.get('version')!r}, нужна {MAP_VERSION}"
        tests = list(raw["tests"])
        files = {k: {tests[i] for i in v} for k, v in raw["files"].items()}
        hashes = {k: str(v) for k, v in raw["hashes"].items()}
        return {"tests": set(tests), "always": set(raw.get("broken") or ()), "files": files, "hashes": hashes}, None
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
        return None, f"карту {os.path.basename(path)} не прочесть — {type(e).__name__}: {e}"


def test_hash(pdir, label):
    """sha256 файла тестов (так хеши пишет affected-map.py); None — файла нет или не прочесть."""
    try:
        with open(os.path.join(pdir, "tests", label.split("/", 1)[1]), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def stale_tests(items, amap):
    """[метки] файлов тестов, которые есть в карте, но изменены после её сборки (хеш другой): связи таких файлов по
    карте неверны — они могли начать задевать новые файлы. Нет файла — не устарел (нечего гонять)."""
    old = amap.get("hashes") or {}
    out = []
    for pdir, label in items:
        if label in amap["tests"]:
            cur = test_hash(pdir, label)
            if cur is not None and cur != old.get(label):
                out.append(label)
    return sorted(out)


def select(changed, root, items, amap, stale=()):
    """(выбранные items или None — весь набор, [(путь, почему весь набор)], [метки, что идут всегда]) по карте amap
    (load_map). stale — метки из stale_tests: идут при любом изменении (любой файл мог стать их зависимостью)."""
    labels = {label for _, label in items}
    plugins = {}
    for pdir, label in items:
        plugins.setdefault(label.split("/", 1)[0], os.path.realpath(pdir))
    root = os.path.realpath(root)
    want, unknown = set(), []
    for path in changed:
        if path in FULL:
            unknown.append((path, "общий файл"))
            continue
        full = os.path.join(root, path)
        hit = None
        for name, pd in plugins.items():
            rel = os.path.relpath(full, pd)
            if re.fullmatch(r"tests/test_[^/]+\.py", rel):
                hit = f"{name}/{rel[len('tests/'):]}"
                break
        if hit is not None:
            if hit in labels:
                want.add(hit)
            continue  # удалённый файл тестов ничего не проверяет
        if path in amap["files"]:
            want.update(lb for lb in amap["files"][path] if lb in labels)
            continue
        unknown.append((path, "нет в карте"))
    if unknown:
        return None, unknown, []
    always = sorted(lb for lb in labels if lb not in amap["tests"] or lb in amap["always"])
    want.update(always)  # тесты не из карты и упавшие при её сборке идут всегда, в том числе когда файлы ничего не задели
    want.update(lb for lb in stale if lb in labels)
    return [it for it in items if it[1] in want], [], always


def split_skipped(items, platform=None, exists=os.path.exists):
    """(идут, [(метка, причина)]): вне macOS файлы SKIP_NOT_MAC не идут, если нет их unless."""
    platform = PLATFORM if platform is None else platform
    if platform == "darwin":
        return list(items), []
    run, skipped = [], []
    for it in items:
        why = SKIP_NOT_MAC.get(it[1])
        if why and not (why[1] and exists(why[1])):
            skipped.append((it[1], why[0]))
        else:
            run.append(it)
    return run, skipped


def make_stubs(root, platform=None, which=shutil.which):
    """(папка с заглушками или None, [команды]): вне macOS — только тех команд STUBS, которых нет на PATH."""
    platform = PLATFORM if platform is None else platform
    missing = sorted(c for c in STUBS if platform != "darwin" and not which(c))
    if not missing:
        return None, []
    d = os.path.join(root, "stubs")
    os.mkdir(d)
    for c in missing:
        path = os.path.join(d, c)
        with open(path, "w") as fh:
            fh.write(f"#!/bin/sh\n{STUBS[c]}\n")
        os.chmod(path, 0o755)
    return d, missing


def order(items, slow=None, serial=None):
    """(параллельные, серийные): параллельные — медленные первыми (по убыванию предела в slow), затем по имени."""
    slow = SLOW if slow is None else slow
    serial = SERIAL if serial is None else serial
    par = [it for it in items if it[1] not in serial]
    ser = [it for it in items if it[1] in serial]
    par.sort(key=lambda it: (-slow.get(it[1], 0), it[1]))
    return par, ser


def checks(out):
    """(есть ли итог, число проверок, плохой итог или None). Итог — последняя непустая строка (TEST_SUMMARY); число проверок — из итога, без числа в нём — по строкам ok."""
    lines = ANSI.sub("", out).splitlines()
    last = next((ln.strip() for ln in reversed(lines) if ln.strip()), "")
    nok = sum(1 for ln in lines if re.match(r"\s*ok\b", ln))
    if not TEST_SUMMARY.match(last):
        return False, nok, None
    total = None
    for rx, fn in _SUMMARY_TOTAL:
        m = rx.match(last)
        if m:
            total = fn(m)
            break
    passed = re.match(r"(\d+)\s*(?:из\s|/)", last)
    if passed and total is not None and int(passed[1]) < total:
        return True, total, f"итог «{last}» — прошли не все"
    if last.startswith("ПРОВАЛ"):
        return True, total if total is not None else nok, f"итог «{last}»"
    n = total if total is not None else nok
    if n == 0:
        return True, 0, f"итог «{last}» — ни одной проверки"
    return True, n, None


def verdict(rc, out, timed_out, label=None, no_summary=None):
    """(ok, почему не ok или None, число проверок). Код 0 без итога — красный, кроме файлов NO_SUMMARY со строками ok
    и без строк FAIL."""
    no_summary = NO_SUMMARY if no_summary is None else no_summary
    has, n, bad = checks(out)
    if timed_out:
        return False, "таймаут", n
    if rc != 0:
        why = f"сигнал {-rc}" if rc < 0 else f"код {rc}"
        return False, why, n
    if not has:
        if label in no_summary and n and not re.search(r"^\s*FAIL\b", ANSI.sub("", out), re.M):
            return True, None, n
        return False, "код 0 без строки итога", n
    if bad:
        return False, bad, n
    return True, None, n


def _killpg(pid, sig=signal.SIGKILL):
    """True, если в группе был кто-то живой."""
    try:
        os.killpg(pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


TASKPOLICY = "/usr/sbin/taskpolicy"
# Проба QoS: сколько тиков CPU процесс провёл в каждом классе (proc_pid_rusage, rusage_info_v4, ri_cpu_time_qos_*).
QOS_PROBE = (
    "import ctypes, struct, os\n"
    "x = 0\n"
    "for i in range(3000000): x += i % 7\n"
    "b = ctypes.create_string_buffer(2048)\n"
    "assert ctypes.CDLL('/usr/lib/libproc.dylib').proc_pid_rusage(os.getpid(), 4, b) == 0\n"
    "n = ['default', 'maintenance', 'background', 'utility', 'legacy', 'user_initiated', 'user_interactive']\n"
    "v = struct.unpack_from('7Q', b, 160)\n"
    "t = sum(v) or 1\n"
    "print(' '.join(f'{k} {100 * c // t}%' for k, c in zip(n, v) if c) or 'нет данных')\n")


def launch_cmd(py, f, platform=None, exists=os.path.exists):
    """Команда запуска одного файла. На macOS с taskpolicy — через `taskpolicy -c utility`: плановый проход идёт
    из launchd с ProcessType Background, и без этого весь набор сидит в QoS background на E-ядрах (файл ×3 дольше,
    metis-0728). На Linux и без taskpolicy — как раньше."""
    cmd = [py, "-I", os.path.join("tests", f)]
    if (sys.platform if platform is None else platform) == "darwin" and exists(TASKPOLICY):
        return [TASKPOLICY, "-c", "utility", *cmd]
    return cmd


def qos_line(py, env, platform=None, exists=os.path.exists):
    """Строка-самопроверка для лога: в каком классе QoS идёт CPU у раннера и у пробного процесса, запущенного так же,
    как файлы тестов. «файл: utility …» — клемп launchd снят; «файл: background …» — не снят."""
    if (sys.platform if platform is None else platform) != "darwin":
        return None
    def probe(cmd):
        try:
            r = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=30)
            out = r.stdout.decode("utf-8", "replace").strip()
            return out if r.returncode == 0 and out else f"проба не удалась (код {r.returncode})"
        except (OSError, subprocess.SubprocessError) as e:
            return f"проба не удалась ({type(e).__name__})"
    own = probe([py, "-I", "-c", QOS_PROBE])
    cmd = [TASKPOLICY, "-c", "utility"] if exists(TASKPOLICY) else []
    job = probe(cmd + [py, "-I", "-c", QOS_PROBE])
    return f"run-tests: QoS (доля CPU) · раннер: {own} · файл ({'taskpolicy -c utility' if cmd else 'без taskpolicy'}): {job}"


class Job:
    def __init__(self, pdir, label, py, root, env0, timeout, seq):
        self.pdir, self.label, self.timeout = pdir, label, timeout
        self.dir = tempfile.mkdtemp(prefix=f"{seq:03d}-", dir=root)
        home, tdir = os.path.join(self.dir, "home"), os.path.join(self.dir, "tmp")
        os.mkdir(home)
        os.mkdir(tdir)
        self.outpath = os.path.join(self.dir, "out.log")
        self.fh = open(self.outpath, "wb")
        f = label.split("/", 1)[1]
        self.t0 = time.monotonic()
        self.proc = subprocess.Popen(launch_cmd(py, f), cwd=pdir,
                                     env={**env0, "HOME": home, "TMPDIR": tdir}, stdin=subprocess.DEVNULL,
                                     stdout=self.fh, stderr=subprocess.STDOUT, start_new_session=True)
        self.timed_out = False

    def exited(self):
        """Вышел ли файл; вышел — гасит его группу (оставленных внуков). Лидер группы до killpg не пожимается
        (waitid WNOWAIT), чтобы номер группы не ушёл другому процессу; без waitid (macOS до Python 3.13) — poll, затем
        killpg: внуки держат группу живой, и её номер не переиспользуется, пока они есть."""
        pid = self.proc.pid
        if hasattr(os, "waitid"):
            try:
                if os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                    return False
            except ChildProcessError:
                pass
            _killpg(pid)
            self.proc.wait()
            return True
        if self.proc.poll() is None:
            return False
        _killpg(pid)
        return True

    def kill(self):
        _killpg(self.proc.pid)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    def finish(self):
        self.sec = time.monotonic() - self.t0
        self.fh.close()
        with open(self.outpath, "rb") as fh:
            self.out = fh.read().decode("utf-8", "replace")
        shutil.rmtree(self.dir, ignore_errors=True)
        self.ok, self.why, self.n = verdict(self.proc.returncode, self.out, self.timed_out, self.label)


def parse(argv):
    opts = {"jobs": None, "timeout": None, "log_dir": None, "dirs": [], "affected": False, "base": None}
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif a == "--affected":
            opts["affected"] = True
        elif a in ("-j", "--jobs", "--timeout", "--log-dir", "--base"):
            v = next(it, None)
            if v is None:
                sys.exit(f"run-tests: {a} без значения")
            if a == "--log-dir":
                opts["log_dir"] = v
            elif a == "--base":
                opts["base"] = v
            else:
                try:
                    num = int(v) if a != "--timeout" else float(v)
                except ValueError:
                    sys.exit(f"run-tests: {a} {v} — не число")
                if num <= 0:
                    sys.exit(f"run-tests: {a} {v} — нужно больше нуля")
                opts["jobs" if a != "--timeout" else "timeout"] = num
        elif a.startswith("-"):
            sys.exit(f"run-tests: неизвестный ключ {a}")
        else:
            opts["dirs"].append(a)
    if opts["base"] is not None and not opts["affected"]:
        sys.exit("run-tests: --base без --affected — полный прогон базы не требует")
    return opts


def pick_affected(items, dirs, base, map_path=None):
    """(items для прогона или None — выйти с кодом code, code). Печатает, что выбрано и почему."""
    head = f"run-tests: затронутое от {base}"
    try:
        root, mb, changed = changed_files(dirs[0], base)
    except (GitError, OSError) as e:
        print(f"{head}: изменённые файлы не получить — {e} — весь набор", flush=True)
        return items, 0
    head += f" ({mb})"
    if not changed:
        print(f"{head}: изменений нет — нечего гонять (полный прогон — без --affected)")
        return None, 3
    amap, why = load_map(map_path)
    if amap is None:
        print(f"{head}: {why} — весь набор", flush=True)
        return items, 0
    stale = stale_tests(items, amap)
    if len(stale) >= STALE_FULL:
        print(f"{head}: карта устарела — {len(stale)} файлов тестов изменены после её сборки (порог {STALE_FULL}): "
              f"{', '.join(stale[:3])}{' …' if len(stale) > 3 else ''} — весь набор; пересобрать: affected-map.py",
              flush=True)
        return items, 0
    chosen, unknown, always = select(changed, root, items, amap, stale)
    if unknown:
        path, why = unknown[0]
        more = f" и ещё {len(unknown) - 1}" if len(unknown) > 1 else ""
        print(f"{head}: изменено {len(changed)}, {path} — {why}{more} — весь набор", flush=True)
        return items, 0
    if not chosen:
        print(f"{head}: изменено {len(changed)}, ни один не проверяется тестами по карте — нечего гонять "
              f"({', '.join(changed[:5])}{' …' if len(changed) > 5 else ''})")
        return None, 3
    extra = f", из них всегда (карта их не знает или они упали при сборке): {', '.join(always)}" if always else ""
    if stale:
        extra += f"; изменены после сборки карты, идут всегда (пересобрать: affected-map.py): {', '.join(stale)}"
    print(f"{head}: изменено {len(changed)}, тестов {len(chosen)} из {len(items)}{extra}", flush=True)
    return chosen, 0


def main(argv):
    opts = parse(argv)
    if not opts["dirs"]:
        print(__doc__)
        return 2
    for d in opts["dirs"]:
        if not os.path.isdir(d):
            print(f"run-tests: нет папки {d}")
            return 2
    items = collect(opts["dirs"])
    if not items:
        print(f"run-tests: ни одного файла tests/test_*.py в {' '.join(opts['dirs'])} — нечего проверять")
        return 1
    if opts["affected"]:
        items, code = pick_affected(items, opts["dirs"], opts["base"] or "origin/main")
        if items is None:
            return code
    items, skipped = split_skipped(items)
    if not items:
        for label, why in skipped:
            print(f"skip {label} · пропущено: нужен macOS — {why}")
        print("run-tests: все выбранные файлы пропущены — нечего гонять")
        return 3
    par, ser = order(items)
    total_files = len(par) + len(ser)
    cpus, load = os.cpu_count(), load1()
    n = opts["jobs"] or workers(cpus, load)
    print(f"run-tests: {total_files} файлов, воркеров {n} (ядер {cpus}, load1 "
          f"{'—' if load is None else f'{load:.1f}'}), {sys.executable}", flush=True)
    for label, why in skipped:
        print(f"skip {label} · пропущено: нужен macOS — {why}", flush=True)
    if opts["log_dir"]:
        os.makedirs(opts["log_dir"], exist_ok=True)
    env0 = {k: v for k, v in os.environ.items()
            if not k.startswith("PANTHEON_") and k not in ("FORCE_COLOR", "CLICOLOR_FORCE")}
    env0.update({"NO_COLOR": "1", "PYTHON_COLORS": "0", "RUN_TESTS_RUNNER": "1"})
    qos = qos_line(sys.executable, env0)
    if qos:
        print(qos, flush=True)
    root = tempfile.mkdtemp(prefix="run-tests-")
    stubs, stubbed = make_stubs(root)
    if stubs:
        env0["PATH"] = stubs + os.pathsep + env0.get("PATH", "")
        print(f"run-tests: не macOS — заглушки команд в PATH файлов: {', '.join(stubbed)}", flush=True)
    state = {"spawning": False, "pending": None}

    def on_signal(signum, _frame):
        if state["spawning"]:  # Popen ещё не вернул процесс — гасим его сразу после того, как он записан
            state["pending"] = signum
            return
        raise Interrupted(signum)

    old = {s: signal.signal(s, on_signal) for s in SIGNALS}
    running, done, t_all, seq = [], [], time.monotonic(), 0
    try:
        queue = list(par)
        while queue or ser or running:
            limit = n if queue else (0 if running else 1)
            src = queue if queue else ser
            while src and len(running) < limit:
                pdir, label = src.pop(0)
                seq += 1
                state["spawning"] = True
                try:
                    job = Job(pdir, label, sys.executable, root, env0,
                              opts["timeout"] or SLOW.get(label) or TIMEOUT, seq)
                    running.append(job)
                finally:
                    state["spawning"] = False
                if state["pending"] is not None:
                    raise Interrupted(state["pending"])
            for job in list(running):
                if job.exited():
                    pass
                elif time.monotonic() - job.t0 > job.timeout:
                    job.timed_out = True
                    job.kill()
                else:
                    continue
                running.remove(job)
                job.finish()
                done.append(job)
                report(job, opts["log_dir"])
            time.sleep(0.05)
    except Interrupted as e:
        for s in SIGNALS:
            signal.signal(s, signal.SIG_IGN)
        for job in running:
            _killpg(job.proc.pid)
        for job in running:
            job.kill()
            job.fh.close()
        n_killed, running = len(running), []
        shutil.rmtree(root, ignore_errors=True)
        print(f"run-tests: прерван сигналом {e.signum} — погашено файлов: {n_killed}, "
              f"готово {len(done)} из {total_files}", flush=True)
        return 128 + e.signum
    finally:
        # любой другой обрыв раннера (сбой запуска, ошибка в коде) тоже не оставляет идущих файлов
        for job in running:
            job.kill()
            job.fh.close()
        for s, h in old.items():
            signal.signal(s, h)
        shutil.rmtree(root, ignore_errors=True)
    return summary(done, total_files, n, time.monotonic() - t_all, len(skipped))


def report(job, log_dir):
    mark = "ok  " if job.ok else "FAIL"
    why = "" if job.ok else f" · {job.why}"
    print(f"{mark} {job.label} · {job.sec:.1f} с · проверок {job.n}{why}", flush=True)
    if log_dir:
        with open(os.path.join(log_dir, job.label.replace("/", "__") + ".log"), "w") as fh:
            fh.write(job.out)


def summary(done, total_files, n, sec, skipped=0):
    bad = [j for j in done if not j.ok]
    for j in bad:
        lines = j.out.rstrip("\n").splitlines()
        print(f"\n===== {j.label} · {j.why} · последние {min(TAIL, len(lines))} строк =====")
        print("\n".join(lines[-TAIL:]))
    slow = sorted(done, key=lambda j: -j.sec)[:5]
    print("\nмедленные: " + ", ".join(f"{j.label} {j.sec:.0f} с" for j in slow))
    checks_sum = sum(j.n for j in done)
    skip = f", пропущено {skipped}" if skipped else ""
    print(f"итого: файлов {total_files}, ok {len(done) - len(bad)}, FAIL {len(bad)}{skip}; проверок {checks_sum}; "
          f"{sec:.0f} с, воркеров {n}", flush=True)
    return 1 if bad or len(done) != total_files else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
