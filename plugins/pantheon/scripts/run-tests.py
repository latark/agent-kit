#!/usr/bin/env python3
"""run-tests.py <папка плагина> … — параллельный прогон файлов тестов плагинов, в духе prove (metis-0450).

  heavy python3 -I plugins/pantheon/scripts/run-tests.py plugins/guard plugins/pantheon
  -j N            воркеров (по умолчанию min(ядра // 2, 3), при load1 выше числа ядер — 1)
  --timeout С     предел одного файла, с (по умолчанию TIMEOUT; у медленных файлов свой — SLOW)
  --log-dir ПАПКА полный вывод каждого файла — в ПАПКА/<плагин>__<файл>.log
  --affected      только затронутое (metis-0451): файлы тестов, связанные с изменёнными файлами, по карте MAP
  --base REF      база для --affected (по умолчанию origin/main)
  --only МЕТКИ    только эти файлы тестов, через запятую: «pantheon/test_a.py,guard/test_b.py» (метка — как в строках
                  ok/FAIL); метки нет среди файлов папок — код 2 без прогона. Дозапуск прохода outside (metis-0735):
                  упавшие в прошлом полном прогоне и затронутые диффом; с --affected — отказ
  --cache         не гонять файл, чей ключ входов совпал с его зелёным прогоном (metis-0698; ниже «Кэш»)

Файл тестов идёт в классе QoS раннера (metis-0647): `taskpolicy -c utility` из окна роли опускал его из default вдвое
(test_merge_gate 221–255 с против 115–122 с), а клемп launchd плановому проходу изнутри не снять. RUN_TESTS_QOS=utility
на macOS возвращает `taskpolicy -c utility` для каждого файла (metis-0728). В начале прогона печатается строка
«QoS (доля CPU)» — проба раннера и файла.
Файлам виден RUN_TESTS_RUNNER=1 (test_shell_diff по нему берёт пул из двух процессов).

Только затронутое — для агента во время правки и для PR; полный набор — без ключа (на main, в шлюзе и перед
выпуском). Изменённые файлы — `git diff --no-renames` рабочего дерева от merge-base REF и HEAD, плюс новые файлы вне
.gitignore. Карта MAP (scripts/affected-map.json) построена прогоном: какой файл тестов какой файл репозитория
загрузил, открыл или запустил (как — шапка scripts/affected-map.py). Каждый изменённый файл (путь от корня):
  - общий (FULL: lib/pantheon.py, hooks/python.sh, сам раннер, карта) — весь набор;
  - сам tests/test_*.py одной из папок — он сам; удалённый файл тестов — ничего;
  - есть в карте — его файлы тестов; пустой список — файл не задел ни один тест (AGENTS.md);
  - иначе (новый файл, карты нет или она другой версии) — весь набор: неизвестное гоняет всё.
Файлы тестов, которых карта не знает (новые после её сборки), которые при сборке упали (broken) или читают дерево
(readers: линтеры словаря и путей открывают десятки файлов, ничего из них не запуская, metis-0791), идут всегда — при
любой правке, но в files их связей нет, и правка, например, bin/heavy не тянет их как зависимых.
Карта хранит sha256 каждого файла тестов (hashes): файл, изменённый после сборки (хеш другой), мог начать задевать новые
файлы — его связи не верны, и он идёт при любом изменении (в выводе: «изменены после сборки карты»); таких файлов
сколько бы их ни было, они идут все, а не весь набор (metis-0782). Так правка теста после сборки не пропускает нужные
тесты из-за старой карты. Весь набор — только там, где без него нельзя, и одной строкой с причиной: общий файл (FULL),
изменённый файл вне карты (его зависимых не знаем; в строке — до 5 таких файлов), карта не читается, ошибка git.
Тесты плагинов, которых нет в аргументах, не идут. Изменений нет или ни один не ведёт к тестам — идёт дымовой файл
SMOKE (линтер словаря, секунды) и строка «нечего гонять …; дымовой файл»: код 0 даёт запись прогона, а код 3 её не давал
(metis-0692). Дымового файла среди файлов прогона нет — код 3 и строка «нечего гонять», а не пустой зелёный. Ошибка git (нет базы, не репозиторий, мелкий клон без merge-base) — весь
набор и причина строкой: при сомнении раннер гоняет всё, а не ничего.
Код 4 — зелёный прогон, но файлы окна (WINDOW_*) пропущены: для записи полного набора не годится; FAIL важнее (код 1).

Кэш (--cache, metis-0698; в духе Bazel и Pants). Ключ файла тестов — sha256 от метки, версии и реализации Python,
платформы, sha256 раннера и пар (путь, sha256) всех его входов по карте, включая сам файл. Зелёный файл пишется в папку
кэша (RUN_TESTS_CACHE, по умолчанию ${XDG_CACHE_HOME:-~/.cache}/agent-kit-run-tests, файл на ключ, старше CACHE_DAYS —
удаляется); совпал ключ — файл не идёт, а печатается строкой `кэш  <метка> · из кэша: зелёный прогон …` и числом «из
кэша» в итоге. Верить кэшу можно, только если связи файла по карте верны сейчас (cache_keys): файл в карте, не упал при
сборке и не читает дерево, не изменён после сборки, каждый вход совпадает с sums карты и в папку, которую он копирует
целиком, не лёг новый файл. Иначе он мог начать задевать файлы, которых в ключе нет, — такой файл идёт. Карта без sums,
нет git или папки кэша — кэша нет, причина строкой, всё идёт как без ключа. Прогон с --cache — не полный набор: команда
другая, и шлюз его записью полного набора не считает (засчитывать ли — решение владельца). Остаток: тест, который
перебирает файлы папки и не копирует её целиком, о новом файле в ней не узнает — как и карта; ловит полный прогон.

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

Итог: строка на каждый файл по мере готовности (ok / FAIL / карантин — файл из QUARANTINE упал, код не портит; время, число проверок), затем выводы упавших файлов
(все строки, кроме `ok` и пустых: упавшие проверки, трассировка и итог видны, где бы они ни были; больше NOT_OK_MAX —
начало и конец; не кончается последней строкой вывода — ещё TAIL последних, metis-0719) и последняя строка — файлов,
ok, FAIL, сумма проверок, время. Код выхода не 0, если: нет ни одного файла тестов, файл упал (код не 0), превысил таймаут, вышел с кодом 0 без строки итога (кроме старых файлов NO_SUMMARY)
или с итогом без проверок, или с явным провалом в выводе при коде 0 (строка с начала FAIL <имя>, НЕ ПРОШЛО,
Traceback, «FAIL K», «не прошло: K» при K>0; «FAIL 0» и «не прошло: 0» — чисто, metis-0556), или раннер прерван сигналом.
Папка плагина без tests/ — код 2 и строка «нет папки …/tests», как при «нет папки» (metis-0556). Число проверок файла — из его итоговой строки, без числа в ней — по строкам `ok`.
Храповик (metis-0854): перед тестами — scripts/lint_ratchet.py (с ним и `ruff check .`) по репозиторию первой
папки, так его держит и запасной путь слияния (запись полного набора на head PR). И при --only: дозапуск pantheon
outside (только упавшие файлы) тоже пишет запись полного набора, без храповика рост прошёл бы через него. Режим warn
(scripts/lint-ratchet-mode, сейчас так) — храповик сам отдаёт код 0 и строку «предупреждение», код тестов тот же. Красный
(режим fail) — код 1 и его причина последней строкой после итога; нет ruff закреплённой версии (код 2) — строка «skip lint_ratchet · пропущено» и код тестов;
папка не в репозитории с храповиком (временные плагины тестов раннера) — без строки.
Только stdlib.
"""
import hashlib
import json
import os
import posixpath
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

TIMEOUT = 600  # с на файл; медленным — свой предел в SLOW
# Медленные файлы: идут первыми (по убыванию предела), предел — свой, с. metis-0634: пределы — по 31 полному прогону
# прохода outside 30.10–01.11 (-j 3, тогда процесс тика шёл с ProcessType Background (с metis-0728 — Standard), Mac под нагрузкой): 1.5 × наибольшего
# зелёного времени файла с округлением вверх до минуты, не меньше 180 с. Прежние (3 × последовательного замера 27.10)
# давали таймауты: test_merge_gate — 19 из 33 прогонов, test_watch — 10 из 31, test_read — 9 из 31.
# В комментарии — медиана и наибольшее зелёное время в тех прогонах, с.
SLOW = {
    # test_watch: 575 / 791 в 27 прогонах 01-03.11 (metis-0719): 1.5 × 791 → 1200. Спящих ожиданий нет — 524 запуска
    # run.py по 0.25 с, время растёт с нагрузкой, как у test_merge_gate (0.9-1.0 его времени); 03.11 при load 17.8 —
    # test_merge_gate 1051 с, test_watch убит на 1020
    "pantheon/test_watch.py": 1200,
    "guard/test_merge_gate.py": 1200,  # 458 / 458; outside -j 3 02.11 — 766-825 с, раз 900 (таймаут), metis-0719
    "guard/test_guard.py": 720,  # 336 / 442; на Linux в Docker под нагрузкой 120-240 с, на 2-ядерном ubuntu-latest дольше
    # test_read: 97 / 259, убит на 180 с 14 раз и на 300 с 4 раза из 80 прогонов (0731, п. 5): 1.5 × 259 мало.
    # 600 ≈ 2.3 × 259 — во столько раз test_merge_gate под нагрузкой 03.11 дольше своей медианы (1051 / 458)
    "pantheon/test_read.py": 600,
    "guard/test_shell_diff.py": 600,  # 254 / 390
    # test_merge: 86 / 171 в прежних прогонах; замер 03.11 (metis-0783) на одном воркере при load 30-150: 143 с чистого
    # времени тестов, 386 с с очередью heavy. Время — ~200 запусков python3.11 с загрузкой pantheon (по 0.3-1 с под
    # нагрузкой); снов и git нет, ускорять нечем без потери изоляции. 600 ≈ 3.5 × 171, как у test_read
    "pantheon/test_merge.py": 600,
    "pantheon/test_plugins_update.py": 540,  # 170 / 346
    "pantheon/test_setup.py": 480,  # 109 / 303
    "pantheon/test_start.py": 480,  # 136 / 289
    "pantheon/test_board.py": 360,  # 98 / 235
    "pantheon/test_sync_quarantine.py": 360,  # 120 / 231
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
# Карантин (metis-1050, решение владельца 09.11): файлы, которые падают только под нагрузкой полного набора и
# зелёные отдельно. Их падение печатается строкой `карантин <метка> · <причина> · задача <id>` и выводом в итоге, но
# код прогона не портит: нестабильный тест не держит слияние. У каждого — задача на починку; починили — убрать из
# списка. Большие файлы ядра (test_guard, test_hookd, test_outside) сюда целиком не кладут: их настоящие падения
# тогда тоже прошли бы молча.
QUARANTINE = {
    "pantheon/test_outside_idle.py": "metis-0989",  # «без ps молчащий sleep гасится по тишине» под нагрузкой
}
# Окно роли (metis-0773): песочница режет запись `.claude/agents` и `.git/{config,hooks}` под папкой tmp кэша окна
# (PANTHEON_TMP), где TMPDIR раннера. Эти файлы строят в своих временных папках поддельный HOME с ролями и репозитории
# `git init`, поэтому в окне падали на пустом месте. Им раннер даёт корень в /tmp/claude-<uid> (там запись есть, сокетов
# нет — файлам они не нужны); нет и там — строка `skip … пропущено: …`. Остальные файлы идут как раньше. Проба — на
# деле: те же `mkdir .claude/agents` и `git init`, а не угадывание окна по переменной.
WINDOW_FS = {
    "guard/test_guard.py", "guard/test_merge_gate.py", "guard/test_drafts.py", "project-tools/test_project_tools.py",
    "pantheon/test_read.py", "pantheon/test_setup.py", "pantheon/test_start.py", "pantheon/test_sync_quarantine.py",
    "pantheon/test_executors.py", "pantheon/test_tick.py", "pantheon/test_watch.py", "pantheon/test_agent_allowlist.py",
    "pantheon/test_baseline.py", "pantheon/test_batch.py", "pantheon/test_check_traces.py",
    "pantheon/test_config_check.py", "pantheon/test_coord_switch.py", "pantheon/test_direction.py",
    "pantheon/test_grants.py", "pantheon/test_outside_rerun.py", "pantheon/test_outside.py",
    "pantheon/test_private_conf.py", "pantheon/test_plugin_map.py", "pantheon/test_review.py",
    "pantheon/test_role_apply.py", "pantheon/test_roles.py", "pantheon/test_sandbox_size.py",
    "pantheon/test_run_tests.py", "pantheon/test_window_ports.py", "pantheon/test_traces.py",
    "pantheon/test_workshop_sockets.py", "pantheon/test_tick_skip.py", "pantheon/test_map_cache.py",
    "pantheon/test_window_folders.py", "pantheon/test_window_pack.py",
    "pantheon/test_outside_tree.py", "pantheon/test_outside_cancel.py",   # части test_outside.py (metis-0750)
}
# Из них не годятся в запасной корень /tmp/claude-<uid>: корень HOME там — «временная папка» для guard (test_merge_gate
# уходит в /var/tmp, а он в окне закрыт). В окне, где запасной корень нужен, они пропускаются строкой.
WINDOW_NOT_TMP = {"guard/test_merge_gate.py"}
WINDOW_SKIP_CODE = 4  # не 3: 3 — «нечего гонять», CI в --affected считает его зелёным; пропуск окна зелёным быть не должен
# Файлы, чьи случаи поднимают серверы на локальных портах: в окне без bind пропускаются строкой.
WINDOW_BIND = {"pantheon/test_outside.py"}
# Команды macOS, которых нет на Linux: заглушка с выводом, при котором код идёт обычным путём.
STUBS = {"ioreg": "exit 0", "pmset": 'echo "Now drawing from AC Power"', "scutil": "echo linux-host"}
PLATFORM = os.environ.get("RUN_TESTS_PLATFORM") or sys.platform
# Карта для --affected (metis-0451): строит scripts/affected-map.py прогоном всех тестов, правится только им.
MAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "affected-map.json")
MAP_VERSION = 3  # 3 — readers (metis-0791): старый раннер новую карту не берёт и гонит всё, а не теряет их
# Карта старше файла тестов (правка после сборки): связи этого файла по карте неверны, файл идёт всегда (metis-0782:
# сколько бы таких ни было — весь набор не из-за них).
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
# строк вывода упавшего файла в итог: все, кроме ok и пустых; больше — половина с начала и половина с конца. Хвоста
# в 40 строк не хватало: test_merge_gate печатает 1662 строки, упавшая проверка — в середине (metis-0719)
NOT_OK_MAX = 200
TAIL = 5  # и последние строки вывода, если список не-ok ими не кончается


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
    """(карта {"tests": {метка}, "always": {метка}, "files": {путь: {метка}}} или None, почему None). always —
    упавшие при сборке (broken) и читающие дерево (readers, metis-0791): их связей в files нет, идут при любой правке."""
    path = MAP if path is None else path
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if raw.get("version") != MAP_VERSION:
            return None, f"карта {os.path.basename(path)} версии {raw.get('version')!r}, нужна {MAP_VERSION}"
        tests = list(raw["tests"])
        files = {k: {tests[i] for i in v} for k, v in raw["files"].items()}
        hashes = {k: str(v) for k, v in raw["hashes"].items()}
        always = set(raw.get("broken") or ()) | set(raw.get("readers") or ())
        sums = raw.get("sums")
        sums = {k: str(v) for k, v in sums.items()} if isinstance(sums, dict) else None
        return {"tests": set(tests), "always": always, "files": files, "hashes": hashes, "sums": sums,
                "broken": set(raw.get("broken") or ()), "readers": set(raw.get("readers") or ())}, None
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


def file_sha(path):
    """sha256 файла; None — нет или не прочесть."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def repo_files(root):
    """[пути от корня] — файлы git ls-files, что есть в рабочем дереве, и новые вне .gitignore (как у affected-map.py)."""
    out = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    return sorted({p for p in out if p and os.path.isfile(os.path.join(root, p))})


def map_rel(root, path=None):
    """Путь карты от корня репозитория или None (карта вне него). Сама карта — выход сборки, а не вход: в sums её нет,
    и её правка расхождением не считается."""
    rel = os.path.relpath(os.path.realpath(MAP if path is None else path), os.path.realpath(root))
    return None if rel.startswith("..") else rel.replace(os.sep, "/")


def label_path(root, pdir, label):
    """Путь файла тестов label от корня репозитория."""
    rel = os.path.relpath(os.path.join(os.path.realpath(pdir), "tests", label.split("/", 1)[1]), os.path.realpath(root))
    return rel.replace(os.sep, "/")


def map_inputs(amap):
    """{метка: {пути}} — входы каждого файла тестов по карте (обращение files)."""
    out = {}
    for path, users in amap["files"].items():
        for lb in users:
            out.setdefault(lb, set()).add(path)
    return out


def folder_users(files_map, path):
    """Тесты, что по карте задели КАЖДЫЙ файл ближайшей папки над path, где карта знает файлы: так ведёт себя тест,
    который копирует папку или плагин целиком (copytree, `cp -R`), — новый файл в ней он тоже заденет. Корень
    репозитория не берётся: его файлы целиком не копирует никто, а пересечение по всем файлам — лишняя работа."""
    d = posixpath.dirname(path)
    while d:
        pre = d + "/"
        users = None
        for f, lbs in files_map.items():
            if f.startswith(pre):
                users = set(lbs) if users is None else users & set(lbs)
                if not users:
                    break
        if users is not None:
            return users
        d = posixpath.dirname(d)
    return set()


def map_drift(amap, items, root, files_now, sums_now, ignore=()):
    """Чем дерево разошлось с картой (metis-0692) → {"new_tests", "stale", "changed", "added", "removed"} (sorted
    списки). changed — файлы, чей sha256 не тот, что в sums карты; added — файлов нет в sums; removed — есть в sums, нет
    в дереве. Карта без sums (до metis-0692) — None: по ней не понять, какие файлы менялись. ignore — пути вне счёта
    (сама карта)."""
    sums = amap.get("sums")
    if sums is None:
        return None
    labels = {lb for _, lb in items}
    ign = set(ignore)
    now = {p for p in files_now if p not in ign}
    return {"new_tests": sorted(labels - amap["tests"]),
            "stale": stale_tests(items, amap),
            "changed": sorted(p for p in now if p in sums and sums_now.get(p) != sums[p]),
            "added": sorted(p for p in now if p not in sums),
            "removed": sorted(p for p in sums if p not in now and p not in ign)}


def drift_rerun(amap, items, drift):
    """[метки] файлов тестов, чьи связи по карте могли устареть: новые, изменённые после сборки, упавшие при сборке,
    задевшие по карте изменённый или удалённый файл, и копирующие папку нового файла (folder_users). Остальные идут
    так же, как при сборке (их файл и все их входы те же), и их связи верны. Читающие дерево (readers) — только если
    задели изменённое по «m»/«o»: их чтения в карту не идут."""
    labels = {lb for _, lb in items}
    want = set(drift["new_tests"]) | set(drift["stale"]) | (amap["broken"] & labels)
    for p in drift["changed"] + drift["removed"]:
        want |= amap["files"].get(p, set())
    for p in drift["added"]:
        want |= folder_users(amap["files"], p)
    return sorted(want & labels)


# Дымовой файл (metis-0692): --affected, которому по карте нечего гонять, гонит его вместо кода 3. Код 3 запись шлюза не
# даёт (её пишут только при 0), а узкий прогон без единого файла — не проверка. Быстрый (секунды), без окна и портов,
# проверяет всё дерево (линтер словаря). Нет его среди файлов прогона (папки pantheon нет в аргументах) — код 3, как раньше.
SMOKE = "pantheon/test_glossary.py"

# Кэш результата файла тестов по хешу входов (metis-0698): --cache не гоняет файл, чей ключ совпал с зелёным прогоном.
CACHE_ENV = "RUN_TESTS_CACHE"  # папка кэша; без неё — ${XDG_CACHE_HOME:-$HOME/.cache}/agent-kit-run-tests
CACHE_DAYS = 14  # записи старше — удаляются при каждом прогоне с --cache
CACHE_V = 1


def cache_dir(env=None):
    env = os.environ if env is None else env
    if env.get(CACHE_ENV):
        return env[CACHE_ENV]
    base = env.get("XDG_CACHE_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".cache")
    return os.path.join(base, "agent-kit-run-tests")


def cache_keys(items, amap, root, files_now, sums_now, mrel=None):
    """({метка: ключ} для файлов, которым можно верить кэшу, {метка: почему нельзя}). Ключ — sha256 от метки, версии и
    реализации Python, платформы, sha256 раннера и пар (путь, sha256) всех входов файла по карте, включая сам файл.
    Файлу можно верить кэшу, только если его связи по карте верны сейчас: он в карте, не упал при сборке и не читает
    дерево (readers: их входы — всё дерево), сам не изменён после сборки, каждый его вход есть и совпадает с sums карты
    (иначе он мог начать задевать новые файлы — их в ключе не было бы), и ни один новый файл не лёг в папку, которую он
    копирует целиком (folder_users). Карта без sums — кэша нет ни у кого."""
    if amap.get("sums") is None:
        return {}, {lb: "карта без sums" for _, lb in items}
    sums = amap["sums"]
    inputs = map_inputs(amap)
    stale = set(stale_tests(items, amap))
    added = [p for p in files_now if p not in sums and p != mrel]
    copies = {}
    for p in added:
        for lb in folder_users(amap["files"], p):
            copies.setdefault(lb, p)
    runner = file_sha(os.path.abspath(__file__)) or ""
    keys, why = {}, {}
    for pdir, lb in items:
        if lb not in amap["tests"]:
            why[lb] = "нет в карте"
            continue
        if lb in amap["always"]:
            why[lb] = "упал при сборке карты или читает дерево"
            continue
        if lb in stale:
            why[lb] = "изменён после сборки карты"
            continue
        if lb in copies:
            why[lb] = f"новый файл {copies[lb]} в папке, которую он копирует"
            continue
        own = label_path(root, pdir, lb)
        pairs, bad = [], None
        for p in sorted(inputs.get(lb, set()) | {own}):
            cur = sums_now.get(p)
            if cur is None:
                bad = f"вход {p} удалён"
                break
            if p != mrel and p in sums and sums[p] != cur:
                bad = f"вход {p} изменён после сборки карты"
                break
            pairs.append([p, cur])
        if bad:
            why[lb] = bad
            continue
        blob = json.dumps({"v": CACHE_V, "label": lb, "python": sys.version.split()[0],
                           "impl": sys.implementation.name, "platform": PLATFORM, "runner": runner, "inputs": pairs},
                          ensure_ascii=False, sort_keys=True)
        keys[lb] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return keys, why


def cache_get(cdir, key, label):
    """Запись зелёного прогона по ключу или None."""
    try:
        with open(os.path.join(cdir, key + ".json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        return rec if isinstance(rec, dict) and rec.get("label") == label and rec.get("v") == CACHE_V else None
    except (OSError, ValueError):
        return None


def cache_put(cdir, key, label, sec, n):
    """Записать зелёный прогон: файл на ключ, атомарно (os.replace) — параллельные прогоны друг другу не мешают."""
    rec = {"v": CACHE_V, "label": label, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "sec": round(sec, 1), "n": n}
    try:
        fd, tmp = tempfile.mkstemp(prefix=".put-", dir=cdir)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
        os.replace(tmp, os.path.join(cdir, key + ".json"))
        return True
    except OSError:
        return False


def cache_prune(cdir, days=CACHE_DAYS, now=None):
    """Удалить записи старше days дней; → сколько удалено."""
    now = time.time() if now is None else now
    gone = 0
    try:
        names = os.listdir(cdir)
    except OSError:
        return 0
    for f in names:
        p = os.path.join(cdir, f)
        try:
            if now - os.stat(p).st_mtime > days * 86400:
                os.remove(p)
                gone += 1
        except OSError:
            pass
    return gone


def cache_plan(items, dirs, map_path=None, env=None):
    """(папка кэша или None, {метка: ключ}, {метка: запись из кэша}, строка для вывода). Папки не создать, нет git
    или карты — кэша нет, причина строкой, файлы идут как без --cache."""
    head = "run-tests: --cache"
    cdir = cache_dir(env)
    try:
        os.makedirs(cdir, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".probe-", dir=cdir)
        os.close(fd)
        os.remove(probe)
    except OSError as e:
        return None, {}, {}, f"{head}: папка кэша {cdir} недоступна ({type(e).__name__}) — кэша нет, все файлы идут"
    amap, why = load_map(map_path)
    if amap is None:
        return None, {}, {}, f"{head}: {why} — кэша нет, все файлы идут"
    try:
        root = _git(dirs[0], "rev-parse", "--show-toplevel").strip()
        files_now = repo_files(root)
    except (GitError, OSError) as e:
        return None, {}, {}, f"{head}: файлы репозитория не получить — {e} — кэша нет, все файлы идут"
    if amap.get("sums") is None:
        return None, {}, {}, f"{head}: карта собрана без sums (до metis-0692) — кэша нет, все файлы идут"
    sums_now = {p: file_sha(os.path.join(root, p)) for p in files_now}
    keys, _ = cache_keys(items, amap, root, files_now, sums_now, map_rel(root, map_path))
    pruned = cache_prune(cdir)
    hits = {}
    for lb, k in keys.items():
        rec = cache_get(cdir, k, lb)
        if rec is not None:
            hits[lb] = rec
    line = (f"{head}: {cdir} — из кэша {len(hits)}, можно кэшировать {len(keys)} из {len(items)}"
            + (f", удалено старых записей {pruned}" if pruned else ""))
    return cdir, keys, hits, line


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


# Явный провал в выводе (metis-0556): строка с начала — `FAIL <имя>`, `НЕ ПРОШЛО`, `Traceback (most recent call last)`,
# итог `FAIL K` (K>0); где угодно — «не прошло: K» и «K не прошло» при K>0 (кроме строк ok — там имя проверки). Слово FAIL внутри строки или имени теста,
# «FAIL 0», «не прошло: 0» провалом не считаются.
_EXPLICIT_LINE = (
    (re.compile(r"\s*FAIL\s+0+\s*$"), None),  # итог «FAIL 0» — чисто
    (re.compile(r"\s*FAIL\b"), "строка FAIL"),
    (re.compile(r"\s*НЕ\s+ПРОШЛО\b"), "строка НЕ ПРОШЛО"),
    (re.compile(r"Traceback \(most recent call last\)"), "Traceback"),
)
_EXPLICIT_COUNT = re.compile(r"не\s+прошло:\s*(\d+)|(\d+)\s+не\s+прошло\b", re.I)


def explicit_fail(out):
    """Почему вывод файла — явный провал, или None. Смотрит строки вывода независимо от кода выхода и итога."""
    for ln in ANSI.sub("", out).splitlines():
        for rx, why in _EXPLICIT_LINE:
            if rx.match(ln):
                if why:
                    return f"в выводе {why}: «{ln.strip()[:80]}»"
                break
        else:
            m = None if re.match(r"\s*ok\b", ln) else _EXPLICIT_COUNT.search(ln)  # строка ok — имя проверки
            if m and int(m[1] or m[2]) > 0:
                return f"в выводе «{m[0]}»: «{ln.strip()[:80]}»"
    return None


def verdict(rc, out, timed_out, label=None, no_summary=None):
    """(ok, почему не ok или None, число проверок). Код 0 без итога — красный, кроме файлов NO_SUMMARY со строками ok
    и без строк FAIL. Код 0 с явным провалом в выводе (explicit_fail) — красный."""
    no_summary = NO_SUMMARY if no_summary is None else no_summary
    has, n, bad = checks(out)
    if timed_out:
        return False, "таймаут", n
    if rc != 0:
        why = f"сигнал {-rc}" if rc < 0 else f"код {rc}"
        return False, why, n
    bad_out = explicit_fail(out)
    if bad_out:
        return False, bad_out, n
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
# RUN_TESTS_QOS=utility — файлы тестов через `taskpolicy -c utility`, как до metis-0647; без неё — в классе раннера
QOS_ENV = "RUN_TESTS_QOS"
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


def qos_prefix(platform=None, exists=os.path.exists, env=None):
    """Чем опустить класс файла тестов: `taskpolicy -c utility` только по RUN_TESTS_QOS=utility на macOS с taskpolicy,
    иначе ничего — файл идёт в классе раннера (metis-0647). Клемп launchd (ProcessType Background или Standard) из
    процесса не снять, а из окна роли `-c utility` сам опускал файл из default: test_merge_gate 221–255 с против
    115–122 с без него (замер 04.11, load1 4–17)."""
    if (os.environ if env is None else env).get(QOS_ENV) != "utility":
        return []
    if (sys.platform if platform is None else platform) == "darwin" and exists(TASKPOLICY):
        return [TASKPOLICY, "-c", "utility"]
    return []


def launch_cmd(py, f, platform=None, exists=os.path.exists, env=None):
    """Команда запуска одного файла: `py -I tests/<f>`, с RUN_TESTS_QOS=utility на macOS — через
    `taskpolicy -c utility` (qos_prefix)."""
    return [*qos_prefix(platform, exists, env), py, "-I", os.path.join("tests", f)]


def qos_line(py, env, platform=None, exists=os.path.exists):
    """Строка-самопроверка для лога: в каком классе QoS идёт CPU у раннера и у пробного процесса, запущенного так же,
    как файлы тестов (qos_prefix). «раннер: utility …» в плановом проходе — клемп launchd (ProcessType Standard)."""
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
    cmd = qos_prefix(platform, exists)
    job = probe(cmd + [py, "-I", "-c", QOS_PROBE])
    return f"run-tests: QoS (доля CPU) · раннер: {own} · файл ({'taskpolicy -c utility' if cmd else 'класс раннера'}): {job}"


def fs_probe(base):
    """Можно ли под base создать `.claude/agents` и репозиторий (`.git/config`, `.git/hooks`) → причина или None."""
    d = None
    try:
        d = tempfile.mkdtemp(prefix="probe-", dir=base)
        os.makedirs(os.path.join(d, "h", ".claude", "agents"))
        exe = shutil.which("git")
        if not exe:  # git на PATH нет — проверять нечем, файлы идут как есть
            return None
        r = subprocess.run([exe, "init", "-q", os.path.join(d, "repo")], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30)
        if r.returncode:
            return f"git init не вышел ({r.stderr.strip()[-80:]})"
        return None
    except (OSError, subprocess.SubprocessError) as e:
        return f"{type(e).__name__}: {str(e)[-80:]}"
    finally:
        if d:
            shutil.rmtree(d, ignore_errors=True)


def window_roots(root, labels, probe=None):
    """(корень для файлов WINDOW_FS, причина пропуска или None, строка для вывода или None)."""
    probe = probe or fs_probe
    if not any(lb in WINDOW_FS for lb in labels):
        return root, None, None
    bad = probe(root)
    if not bad:
        return root, None, None
    alt = os.path.join("/tmp", f"claude-{os.getuid()}")
    alt_bad = probe(alt) if os.path.isdir(alt) else "папки нет"
    if not alt_bad:
        return (tempfile.mkdtemp(prefix="run-tests-", dir=alt), None,
                f"run-tests: окно режет запись под {root} ({bad}) — файлы WINDOW_FS идут в {alt}")
    return None, f"окно режет запись `.claude/agents` и `.git/config`: {bad}; {alt}: {alt_bad}", None


def bind_probe():
    """Можно ли занять локальный порт → причина или None."""
    try:
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
        return None
    except OSError as e:
        return str(e)


def window_plan(root, labels, probe=None, bind=None):
    """Что делать с файлами, зависящими от окна → (корень для WINDOW_FS, множество пропускаемых файлов, причина, строка).
    Вне окна обе пробы проходят: корень прежний, пропускаемых нет, строк нет (набор идёт как раньше)."""
    probe, bind = probe or fs_probe, bind or bind_probe
    labels = set(labels)
    froot, why, line = window_roots(root, labels, probe)
    drop, reasons = set(), []
    if why:
        drop |= WINDOW_FS
        reasons.append(why)
    elif froot != root:
        drop |= WINDOW_NOT_TMP
        reasons.append("окно режет `.git/config` под tmp кэша окна, а файлу нужен репозиторий вне /tmp "
                       "(guard считает /tmp временной папкой)")
    if labels & WINDOW_BIND:
        bad = bind()
        if bad:
            drop |= WINDOW_BIND
            reasons.append(f"окно не даёт занять локальный порт ({bad})")
    return froot, drop, "; ".join(reasons), line


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
    opts = {"jobs": None, "timeout": None, "log_dir": None, "dirs": [], "affected": False, "base": None, "only": None,
            "cache": False}
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif a == "--affected":
            opts["affected"] = True
        elif a == "--cache":
            opts["cache"] = True
        elif a in ("-j", "--jobs", "--timeout", "--log-dir", "--base", "--only"):
            v = next(it, None)
            if v is None:
                sys.exit(f"run-tests: {a} без значения")
            if a == "--only":
                labels = [x.strip() for x in v.split(",")]
                if not all(labels):
                    sys.exit(f"run-tests: --only {v!r} — пустая метка")
                opts["only"] = (opts["only"] or []) + labels
            elif a == "--log-dir":
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
    if opts["only"] is not None and opts["affected"]:
        sys.exit("run-tests: --only с --affected — выбирает что-то одно")
    return opts


def smoke(items, line):
    """Нечего гонять по карте → (дымовой файл SMOKE, 0), если он среди items: прогон с кодом 0 даёт запись шлюза и
    записи прохода (metis-0692). Нет его — (None, 3), «нечего гонять», как раньше. Строка с причиной — последней."""
    pick = [it for it in items if it[1] == SMOKE]
    if not pick:
        print(line)
        return None, 3
    print(f"{line}; дымовой файл {SMOKE} — чтобы узкий прогон был проверкой и дал запись, а не код 3", flush=True)
    return pick, 0


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
        return smoke(items, f"{head}: изменений нет — нечего гонять (полный прогон — без --affected)")
    amap, why = load_map(map_path)
    if amap is None:
        print(f"{head}: {why} — весь набор", flush=True)
        return items, 0
    stale = stale_tests(items, amap)
    chosen, unknown, always = select(changed, root, items, amap, stale)
    if unknown:
        paths = ", ".join(f"{p} — {w}" for p, w in unknown[:5])
        more = f" и ещё {len(unknown) - 5}" if len(unknown) > 5 else ""
        print(f"{head}: изменено {len(changed)}, {paths}{more} — весь набор", flush=True)
        return items, 0
    if not chosen:
        return smoke(items, f"{head}: изменено {len(changed)}, ни один не проверяется тестами по карте — нечего гонять "
                     f"({', '.join(changed[:5])}{' …' if len(changed) > 5 else ''})")
    extra = (f", из них всегда (карта их не знает, упали при её сборке или читают дерево): {', '.join(always)}"
             if always else "")
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
        if not os.path.isdir(os.path.join(d, "tests")):
            print(f"run-tests: нет папки {os.path.join(d, 'tests')} — в {d} тестов нет, молча не пропускаю")
            return 2
    items = collect(opts["dirs"])
    if not items:
        print(f"run-tests: ни одного файла tests/test_*.py в {' '.join(opts['dirs'])} — нечего проверять")
        return 1
    if opts["only"] is not None:
        have = {label for _, label in items}
        missing = sorted(set(opts["only"]) - have)
        if missing:
            print(f"run-tests: --only: нет файлов тестов {', '.join(missing)} в {' '.join(opts['dirs'])} — "
                  "нечего гонять")
            return 2
        items = [it for it in items if it[1] in set(opts["only"])]
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
    cdir, ckeys, cached = None, {}, {}
    if opts["cache"]:
        cdir, ckeys, cached, cline = cache_plan(items, opts["dirs"])
        print(cline, flush=True)
        for _, lb in items:
            if lb in cached:
                rec = cached[lb]
                print(f"кэш  {lb} · из кэша: зелёный прогон {rec.get('time', '?')}, проверок {rec.get('n', '?')}, "
                      f"ключ {ckeys[lb][:12]}", flush=True)
        items = [it for it in items if it[1] not in cached]
        if not items:
            print(f"итого: файлов 0, ok 0, FAIL 0, из кэша {len(cached)}; проверок 0; 0 с", flush=True)
            return 0
    par, ser = order(items)
    total_files = len(par) + len(ser)
    window_skipped = 0
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
    froot, drop, fskip, fline = window_plan(root, [lb for _, lb in par + ser])
    if fline:
        print(fline, flush=True)
    if drop:
        gone = sorted({lb for _, lb in par + ser} & drop)
        for lb in gone:
            print(f"skip {lb} · пропущено: {fskip}", flush=True)
        par = [x for x in par if x[1] not in drop]
        ser = [x for x in ser if x[1] not in drop]
        skipped = skipped + [(lb, fskip) for lb in gone]
        window_skipped = len(gone)
        total_files = len(par) + len(ser)  # как SKIP_NOT_MAC: пропущенные в «готово N из M» и в сверке итога не входят

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
                    job = Job(pdir, label, sys.executable, froot if label in WINDOW_FS else root, env0,
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
                if cdir and job.ok and job.label in ckeys:
                    cache_put(cdir, ckeys[job.label], job.label, job.sec, job.n)
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
        shutil.rmtree(froot or root, ignore_errors=True)
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
        shutil.rmtree(froot or root, ignore_errors=True)
    return summary(done, total_files, n, time.monotonic() - t_all, len(skipped), window_skipped, len(cached))


def report(job, log_dir):
    task = None if job.ok else QUARANTINE.get(job.label)
    mark = "ok  " if job.ok else "карантин" if task else "FAIL"
    why = "" if job.ok else f" · {job.why}" + (f" · задача {task}" if task else "")
    print(f"{mark} {job.label} · {job.sec:.1f} с · проверок {job.n}{why}", flush=True)
    if log_dir:
        with open(os.path.join(log_dir, job.label.replace("/", "__") + ".log"), "w") as fh:
            fh.write(job.out)


def not_ok(out, limit=NOT_OK_MAX):
    """Строки вывода упавшего файла для итога: все, кроме `ok` и пустых, по порядку; больше limit — первые и последние
    limit // 2 со строкой о пропуске между ними. → (строки, сколько всего не-ok)."""
    lines = [ln.rstrip() for ln in ANSI.sub("", out).splitlines() if ln.strip() and not re.match(r"\s*ok\b", ln)]
    if len(lines) <= limit:
        return lines, len(lines)
    half = limit // 2
    return lines[:half] + [f"… пропущено {len(lines) - 2 * half} строк …"] + lines[-half:], len(lines)


def summary(done, total_files, n, sec, skipped=0, window_skipped=0, cached=0):
    bad = [j for j in done if not j.ok and j.label not in QUARANTINE]
    quar = [j for j in done if not j.ok and j.label in QUARANTINE]
    for j in bad + quar:
        lines, total = not_ok(j.out)
        tag = f"карантин, задача {QUARANTINE[j.label]} · " if j in quar else ""
        print(f"\n===== {j.label} · {tag}{j.why} · строки не ok: {total} =====")
        print("\n".join(lines))
        # где файл остановился (таймаут, гибель посреди строк ok) — последние строки, если ими список не кончается
        tail = [ln.rstrip() for ln in ANSI.sub("", j.out).splitlines() if ln.strip()][-TAIL:]
        if tail and (not lines or lines[-1] != tail[-1]):
            print(f"----- последние {len(tail)} строк -----")
            print("\n".join(tail))
    slow = sorted(done, key=lambda j: -j.sec)[:5]
    print("\nмедленные: " + ", ".join(f"{j.label} {j.sec:.0f} с" for j in slow))
    checks_sum = sum(j.n for j in done)
    skip = (f", карантин {len(quar)}" if quar else "") + (f", из кэша {cached}" if cached else "") \
        + (f", пропущено {skipped}" if skipped else "")
    print(f"итого: файлов {total_files}, ok {len(done) - len(bad) - len(quar)}, FAIL {len(bad)}{skip}; проверок {checks_sum}; "
          f"{sec:.0f} с, воркеров {n}", flush=True)
    if bad or len(done) != total_files:
        return 1
    if window_skipped:  # зелёный прогон без файлов окна не полный набор: код 0 шлюз принял бы за FULL_TESTS (metis-0773)
        print(f"run-tests: пропущены файлы окна — для записи полного набора не годится (код {WINDOW_SKIP_CODE})", flush=True)
        return WINDOW_SKIP_CODE
    return 0


RATCHET = os.path.join("plugins", "pantheon", "scripts", "lint_ratchet.py")
RATCHET_TIMEOUT = 300


def ratchet(dirs):
    """Храповик по репозиторию первой папки: (код, строки вывода) или None — папка не в репозитории с храповиком."""
    try:
        root = _git(dirs[0], "rev-parse", "--show-toplevel").strip()
    except (GitError, OSError):
        return None
    script = os.path.join(root, RATCHET)
    if not os.path.isfile(script):
        return None
    try:
        r = subprocess.run([sys.executable, "-I", script, "--root", root], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=RATCHET_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 1, [f"храповик не уложился в {RATCHET_TIMEOUT} с"]
    return r.returncode, (r.stdout + r.stderr).strip().splitlines() or [f"храповик: код {r.returncode} без вывода"]


def run_all(argv):
    """main и храповик до него (и при --only: дозапуск outside пишет запись полного набора): красный храповик — код 1
    и причина последней строкой после итога."""
    opts = parse(argv)
    res = ratchet(opts["dirs"]) if opts["dirs"] else None
    if res is not None:
        rc, lines = res
        if rc == 2:
            print(f"skip lint_ratchet · пропущено: {lines[-1]}", flush=True)
        else:
            print("\n".join(lines), flush=True)
    code = main(argv)
    if res is None or res[0] in (0, 2) or code >= 128:
        return code
    print(f"run-tests: храповик красный — {res[1][-1]}", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(run_all(sys.argv[1:]))
