"""Слияние PR ядра одним Touch ID (metis-0285; владелец выбрал Touch ID, Зевс 19.10).

PR ядра защит (Д3) агенты не сливают: его сливает владелец. Чтобы не набирать gh в терминале, роль ставит заявку, а
плановый проход (launchd, сессия владельца, вне песочницы окон) показывает системное окно Touch ID и после пальца
сливает ровно проверенный коммит.

  pantheon merge request <N> -R <owner/repo>   заявка: STATE/merge-queue/<owner>__<repo>__<N>.json (папка 0700,
                                                файл 0600) с head SHA PR сейчас. Репозиторий — из [merge_repos]
                                                metis-pantheon (policy.toml); шлюз проверяется сразу (кроме CI в работе)
  pantheon merge request <N1> <N2> … -R <owner/repo>   пачка (metis-0668, до MAX_BATCH PR одного репозитория):
                                                по заявке на каждый PR с полем batch — номера в порядке слияния;
                                                шлюз не пройден хоть у одного — заявок нет ни на один
  pantheon merge run [--click]   проход по заявкам: зовёт его тик (из окна Claude Code — отказ, guard ролям тоже не даёт);
                                 --click — щелчок по уведомлению запасного пути: владелец у Mac
  pantheon merge status          заявки: репозиторий#N, SHA, возраст, отметки и причина ожидания; ниже — снятые и
                                 слитые за сутки с причиной из logs/merge.jsonl (metis-0819)
  pantheon merge cancel <N> -R <owner/repo>    снять заявку (из пачки — вместе со всей пачкой)

Проход по каждой заявке (одна заявка — одно применение):
  1. Старше REQUEST_TTL (24 ч) — снята.
  2. PR сейчас (gh pr view): не OPEN, черновик или head не тот SHA, что в заявке, — снята (новый коммит — новая заявка).
  3. Репозиторий всё ещё в [merge_repos] metis-pantheon. Шлюз заново на тот же head: запись тестов шлюза на SHA; у
     каждого рецензента argus последний вердикт — «принять» с полным перечнем и на Opus (по ran и, если хук guard
     записал их, по моделям транскрипта argus — metis-0176), рецензентов-«принять» не
     меньше двух, «вернуть» нет. «Вернуть» на любом head PR в силе, пока его не сняло «принять» после него (того же
     рецензента или свежее другого argus на этот SHA, если код «вернуть» другой), а «принять», записанное раньше
     последнего неснятого «вернуть», не в счёт (held_rejects, reject_floor — правило шлюза guard, metis-0465).
     Код прошлых head проход сам не сверит — git папки слияния у него нет. Его сверяет хук guard при `pantheon merge
     request` из клона репозитория (merge_gate.request_decisions, metis-0966, 0396, 0443, вариант А): запись kind
     "decision" в carry.jsonl — head с тем же кодом, что у SHA (same), и посчитанно другим (differs). Проход берёт
     последнее решение на SHA и нынешнюю base PR, не старше REQUEST_TTL и на нынешней вершине ветки base (gh api,
     base_tip — как у шлюза; main ушёл вперёд — решение не в счёт) (code_facts): «принять» с head из same
     переносится на SHA (в счёт — последний вердикт рецензента на SHA и этих head после отсечки), а «вернуть» другой
     argus снимает, только если head «вернуть» в differs. Head из delta решения (SHA — мелкая правка поверх него вне
     ядра, metis-0784): его «принять» переносится по delta_carry — не меньше двух рецензентов с вердиктом на том
     head (полный круг) последним дали «принять», одно «принять» на SHA (дельта-круг `pantheon review delta`, в ядре тоже), и каждый,
     кто вернул тот head, принял SHA. Решения нет или код не посчитан — строго: другой коммит —
     неизвестный код, «принять» не переносится, «вернуть» не снимается; правило 3 шлюза guard (третий head) проход
     не применяет. «Принять» на другой base PR (metis-0965) и с полем «вернули», которое врёт (metis-0497), не в
     счёт. Проверки GitHub (CI) — тот же разбор ci_verdict, что у шлюза guard (metis-0633):
     обязательные из REQUIRED_CHECKS — запуск Actions от pull_request на этом SHA с SUCCESS (ci_runs_fetch, дубль —
     худший итог; PR из форка — запуск с head_repository и head_branch его форка и ветки, ci_fork, metis-0649), у
     репозитория без записи — все проверки rollup. CI ещё идёт, обязательной или любых проверок пока
     нет, запуски не получены — заявка ждёт; красная или SKIPPED — снята с тревогой, кроме CI, который не
     запускался из-за лимита минут или оплаты GitHub Actions (ci_billing по аннотациям красных и данным их job —
     job не стартовал, metis-0655): тогда вместо CI засчитывается запись тестов шлюза на SHA с командой полного
     набора FULL_TESTS (full_tests_record) или узкая `--affected` с базой и картой, сверенными с GitHub
     (narrow_gh_problem, metis-1050 — и у ядра, и у пачки) или узкая от прошлого head с записью тестов при мелкой
     дельте вне файлов шлюза (delta_gh_problem, metis-0784); нет такой — снята с тревогой. Аннотации или данные job красных не
     получены (сбой gh) — ждёт: признак лимита не проверить (ci_billing_fetch, metis-0813).
     PR не сливается с base (mergeable CONFLICTING или mergeStateStatus DIRTY) — снята с тревогой «конфликт с main»
     до окна, а при `pantheon merge request` заявки нет вовсе (metis-0987); GitHub ещё считает (UNKNOWN) или защита
     ветки не даёт слить (BLOCKED: обязательные проверки или ревью GitHub, metis-0987) — ждёт (merge_conflict,
     metis-0819). После пальца UNKNOWN не помеха:
     слияние прежнего PR пачки сдвигает base, и GitHub пересчитывает mergeable лениво; снимает только конфликт
     (check_all after, Б1 argus #381). Причину ожидания проход пишет в заявку (mark_wait) — её показывает status.
     Список файлов PR (REST pulls/N/files) полон — иначе ждёт: окно показывает задетые файлы ядра, без списка их не
     показать. PR правит version в plugin.json плагина или трогает
     .claude-plugin/releases.json — снята с тревогой (metis-0512: номер поднимает workflow release после слияния).
  4. Владелец у Mac (простой меньше PRESENT_SEC) — окно Touch ID: помощник pantheon-touchid (lib/touchid.swift,
     LocalAuthentication), в тексте — задетые файлы ядра, заголовок PR последним. После пальца, под замком
     merge-queue: заявка в очереди та же (не снята и не заменена), репозиторий в [merge_repos], шлюз заново — только
     тогда строка `<время> merge-approve <owner/repo>#<N> <sha>` в owner-log/merge-approve.log (её сверяет шлюз guard:
     PR ядра проходит только с ней, не старше суток), заявка снята, `gh pr merge <N> -R <repo> --match-head-commit
     <sha> --merge`. «Не сливать» — снята. Окно закрыто без ответа — ждёт RETRY_SEC. Окно не показать (код 2: процесс
     launchd не в сессии владельца) — запасной путь: уведомление один раз, щелчок по нему запускает
     `pantheon merge run --click` от имени владельца, и окно Touch ID показывается уже оттуда. Заявку сняли или
     заменили, пока окно открыто, — проход её не трогает: ни согласия, ни слияния, ни записи обратно.
  4а. Фраза вместо пальца (metis-0959, слово владельца 07.11): владелец вне Mac пишет в окне Claude Code с журналом
     ваших слов (Зевс, координатор, мастерская; remote-control с телефона) «слей #N <hex>». Проход берёт её из
     owner-log/*.md (find_phrase): запись хука ctx.py без пометки, фраза — целиком первая строка сообщения, hex от 7
     до 40 знаков — начало SHA заявки, не старше PHRASE_TTL (2 ч), решает последняя фраза на этот номер, в очереди нет
     другой заявки с тем же номером и началом SHA, фраза не использована (STATE/merge-phrases.json). Тогда — как
     после пальца, без окна и без проверки «у Mac»: под замком фраза и шлюз заново, фраза отмечена использованной,
     та же строка merge-approve, `gh pr merge --match-head-commit`. Способ — в merge.jsonl: событие phrase (файл
     owner-log, строка, время записи) и how у merged; в уведомлении о слиянии — «фразой из owner-log/<файл>». Пачку
     фраза не сливает: только окно Touch ID. Отозвать словами (metis-0970): «не сливай #N» или «стоп, не сливай #N»
     первой строкой — если это последняя запись на номер, фраза не в силе (заявка остаётся, ждёт окна Touch ID;
     снять её — `pantheon merge cancel`). Тревога снятой заявки называет путь: «по фразе» или «по Touch ID»
     (metis-0980). Время заголовка записи owner-log — без пояса, проход читает его в нынешнем поясе Mac: сменили пояс
     (перелёт) — возраст фраз до смены сдвинут на разницу часов, фраза старше 2 ч может ожить, свежая — погаснуть
     (остаток metis-0980 Д2: формат ctx.py не меняем).

Пачка (metis-0668, process_batch) — одно окно на все её PR: в тексте — сначала задетое ядро всех и число файлов, затем
каждый PR с SHA и вердиктом шлюза по порядку, заголовки последними. До окна пункты 1–3 — у каждого: неполна (одну заявку сняли или заменили) или
шлюз не пройден хоть у одного — сняты все с тревогой, ждёт один — ждут все. После пальца — по очереди, каждый как
одна заявка в п. 4 (шлюз заново под замком, строка согласия, `gh pr merge --match-head-commit` своего SHA). Не слит
один (шлюз, сбой gh, заявку сняли) — следующие не трогаются: ни согласия, ни слияния; их заявки сняты, тревога
с итогом по каждому. Отказ, время вышло, уведомление — сразу на всю пачку.

Управляемые настройки guard (metis-0710, «да» владельца 02.11 21:57). Тот же проход, под тем же замком: файл
P.MANAGED (/Library/…/managed-settings.json) не совпал с managed-settings.json проверенного дерева guard
(installed_dir: хеш дерева = verified.json) — владелец у Mac — системное окно прав администратора (osascript … with
administrator privileges: Touch ID или пароль) «Обновить управляемые настройки guard до версии X». После касания root
копирует файл рядом, сверяет sha256 с прочитанным проходом и переносит на место (root:wheel, 644). Отказ или
MANAGED_WAIT без касания — карточка «Руками» с командой sudo install и тревога; окно на ту же версию — не чаще
MANAGED_RETRY (STATE/managed-update.json; попытка пишется до окна, и оборванный после окна проход её не теряет).
Файл совпал (по касанию или командой) — тик закрывает карточку. Файла в
/Library нет — не отставание: первый раз его ставит владелец. Тик зовёт проход и без заявок, когда отстали
(managed_check).
Журнал — STATE/logs/merge.jsonl (репозиторий, номер, SHA, событие). Помощник — только STATE/bin/pantheon-touchid с
отметкой sha256 исходника lib/touchid.swift рядом (иначе его пересобирает /usr/bin/swiftc с чистым окружением).
В событии window — поля помощника (metis-0921): device_biometry (тип датчика Mac, не способ подтверждения —
metis-0932), la_code, shown_sec (JSON в его stdout). После слияния (gh pr merge rc 0) владельцу уходит одно
уведомление «слит repo#N (sha7)». Снятие заявки пишет причину (поле why), провал gh pr merge — тоже; `pantheon merge
status` показывает под очередью снятые и слитые за сутки (recent_done, metis-0819).

Окружение прохода (metis-0303). Его задаёт launchd, а launchd-окружение меняет любой процесс владельца (launchctl
setenv). Поэтому проход строит окружение с нуля (clean_env): HOME — realpath домашней папки учётной записи (pw_dir;
HOME окружения не она — отказ), PATH — постоянный SAFE_PATH (gh — из него), STATE, папка Пантеона и current — от HOME.
PANTHEON_STATE, PANTHEON_HOME, PANTHEON_NOTIFY_LOG, PANTHEON_FAKE_*, PANTHEON_NOW, GH_* (GH_CONFIG_DIR, GH_TOKEN),
XDG_* и всё прочее он не берёт.
Интерпретатор: тик не берёт PANTHEON_PYTHON, PANTHEON_PY_DIRS и PYTHONEXECUTABLE, а config.toml читает от домашней
папки учётной записи, не от HOME и не из PANTHEON_STATE (bin/pantheon-tick); проход тик запускает с окружением
pass_env (PANTHEON_PYTHON — найденный тиком интерпретатор, не sys.executable), щелчок — через /usr/bin/env -i с ним же.
Тестовые подмены — только атрибутом TEST, его ставит тестовая обвязка в своём процессе; из окружения он не
включается. Остальной тик PANTHEON_STATE ещё берёт, а DYLD_* и прочее launchd-окружение доходит до интерпретатора
тика: целиком это закрывает только запрет ролям launchctl setenv (metis-0298).
"""
import contextlib
import hashlib
import json
import os
import posixpath
import re
import shlex
import shutil
import stat
import subprocess
import sys
from datetime import datetime

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()

REPO_RE = re.compile(r"[a-z0-9_.-]+/[a-z0-9_.-]+")
PR_RE = re.compile(r"[1-9][0-9]{0,8}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
FILE_RE = re.compile(r"([a-z0-9_.-]+)__([a-z0-9_.-]+)__([1-9][0-9]{0,8})\.json")
MERGE_DIRECTION = "metis-pantheon"   # чьи [merge_repos] — репозитории защит
REQUEST_TTL = 24 * 3600
RETRY_SEC = 600                      # окно закрыто без ответа — следующее не раньше
PRESENT_SEC = 300                    # владелец у Mac: простой меньше 5 минут
WINDOW_WAIT = 120                    # сколько окно ждёт пальца
MIN_ACCEPTS = 2
GH_TIMEOUT = 30
MERGE_TIMEOUT = 120
APPROVE_FILE = "merge-approve.log"
SWIFTC = "/usr/bin/swiftc"           # абсолютный путь: PATH прохода подменяем (launchctl setenv)
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"   # PATH прохода, не из окружения
# Тестовые подмены прохода: {"env": {имя: значение}} — переменные, которые проход берёт поверх чистого окружения, и
# HOME без сверки с учётной записью. Ставит только тестовая обвязка в своём процессе (tests/test_merge.py, HARNESS);
# из окружения launchd не включается. В бою — None
TEST = None
# ядро защит (Д3) — как CORE_FILES и CORE_DIR шлюза guard (merge_gate.py); совпадение сверяет test_merge
CORE_FILES = ("plugins/guard/hooks/merge_gate.py", "plugins/guard/hooks/protect_config.py",
              "plugins/guard/managed-settings.json", "plugins/pantheon/lib/window_rules.py",
              "plugins/pantheon/hooks/ctx.py", "plugins/pantheon/hooks/hooks.json", "plugins/pantheon/lib/merge.py",
              "plugins/pantheon/lib/plugin_map.py", "plugins/pantheon/plugins-by-role.toml",
              "plugins/pantheon/lib/review_rules.py", "plugins/pantheon/lib/answers.py",
              ".claude-plugin/marketplace.json")
CORE_DIR = ("plugins/guard", "plugins/pantheon/roles", ".github", "plugins/pantheon/packs")
# файлы, где ядро — сборка и запуск окон по AST (BUILD_ROOTS шлюза, metis-0404, 0552): окно Touch ID называет их
# среди ядра, как только PR их правит, — шлюз уже счёл PR ядром или не смог проверить (metis-0551); совпадение
# с шлюзом сверяет test_merge_gate
BUILD_FILES = ("plugins/pantheon/lib/pantheon.py", "plugins/pantheon/lib/sessions.py")
MAX_BATCH = 5                        # PR в одной пачке: их номера, SHA и ядро — в окне не длиннее 400 знаков
# согласие фразой (metis-0959): «слей #N <hex>» — первой строкой вашего сообщения в owner-log/<окно>.md
PHRASE_TTL = 2 * 3600                # фраза старше 2 ч не действует
PHRASE_SKEW = 120                    # запись «из будущего» дальше 2 мин — не в счёт (как read_log в ctx.py)
PHRASE_RE = re.compile(r"слей\s+#([1-9][0-9]{0,8})\s+([0-9a-f]{7,40})[.!]?", re.IGNORECASE)
# отзыв фразы словами (metis-0970): «не сливай #N», «стоп, не сливай #N» — последняя запись на номер, и фраза не в силе
REVOKE_RE = re.compile(r"(?:стоп[,.!]?\s+)?не\s+сливай\s+#([1-9][0-9]{0,8})[.!]?", re.IGNORECASE)
OWNER_ENTRY_RE = re.compile(r"## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)")   # заголовок записи append_owner_line
PHRASES_FILE = "merge-phrases.json"  # STATE: использованные фразы — одна фраза, одно согласие
PHRASES_KEEP = 24 * 3600
# вердикт шлюза на запасном пути (metis-0655); в окне пачки он короче — BILLING_SHORT (argus-263a Б1)
BILLING_OK = "CI не запускался (лимит минут GitHub Actions) — засчитан местный прогон тестов на "
BILLING_SHORT = "CI: лимит, тесты ✓"
# `pantheon merge status` (metis-0819): события merge.jsonl, с которыми заявка ушла из очереди, — за сутки, последние 20
DONE_EVENTS = ("merged", "merge-failed", "gate", "gate-after", "expired", "refused", "no-window", "batch-broken",
               "batch-stopped", "error", "cancelled")
DONE_SHOW = 24 * 3600
DONE_MAX = 20
USAGE = ("pantheon merge request <N> [<N2> …] -R <owner/repo> | cancel <N> -R <owner/repo> | run [--click] | "
         "status")


def set_core(mod):
    global P
    P = mod


def err(text):
    print(text, file=sys.stderr)


# --- окружение прохода (metis-0303) -------------------------------------------------------------------------------

def clean_env():
    """Окружение прохода с нуля: HOME и SAFE_PATH, STATE и папка Пантеона — от HOME. Окружение задаёт launchd, а его
    меняет любой процесс владельца (launchctl setenv): из него проход не берёт ничего, кроме PANTHEON_PYTHON — его
    ставит bin/pantheon прохода из pass_env тика (own_python). HOME — домашняя папка учётной
    записи (pw_dir), HOME окружения только сверяется с ней: не она — отказ. Дальше идёт realpath, а не путь как есть:
    ссылку можно перевесить после сверки (argus-b 0303, п. 2) — так в окружение, gh, P.CURRENT и команду щелчка.
    → None или причина отказа."""
    if TEST is None:
        import pwd
        try:
            owner = pwd.getpwuid(os.getuid()).pw_dir
        except (KeyError, OSError):
            owner = None
        if not owner or os.path.realpath(owner) != os.path.realpath(P.HOME):
            return f"HOME ({P.HOME}) — не домашняя папка учётной записи"
        home = os.path.realpath(owner)
    else:
        home = os.path.realpath(P.HOME)
    env = {"HOME": home, "PATH": SAFE_PATH}
    py = own_python()
    if py:   # интерпретатор прохода — для команды щелчка (pass_env); его поставил bin/pantheon из pass_env тика
        env["PANTHEON_PYTHON"] = py
    if TEST is not None:
        env.update(TEST.get("env") or {})
    os.environ.clear()
    os.environ.update(env)
    P.HOME = home
    P.AI_HOME = os.path.join(home, "ai")
    P.CURRENT = os.path.join(home, ".local", "share", "pantheon", "current")
    P.STATE = os.path.realpath(os.path.join(home, ".local", "state", "pantheon"))
    P.PANTHEON = os.path.realpath(os.path.join(P.AI_HOME, "pantheon"))
    return None


def own_python():
    """Интерпретатор прохода — PANTHEON_PYTHON: в тике его ставит bin/pantheon-tick после find_python, в проходе —
    bin/pantheon из pass_env тика. Не sys.executable: на macOS его задаёт PYTHONEXECUTABLE даже при -I, а окружение
    тика — launchd (argus-b 0303c, п. 1). Не абсолютный путь — None."""
    py = os.environ.get("PANTHEON_PYTHON", "")
    return py if os.path.isabs(py) else None


def pass_env():
    """Окружение, с которым тик запускает проход, а щелчок по уведомлению — `merge run --click`: HOME, SAFE_PATH и
    свой интерпретатор (own_python; bin/pantheon берёт PANTHEON_PYTHON), без launchd-окружения. Интерпретатора
    нет — без PANTHEON_PYTHON: bin/pantheon найдёт его сам в чистом окружении."""
    env = {"HOME": P.HOME, "PATH": SAFE_PATH}
    py = own_python()
    if py:
        env["PANTHEON_PYTHON"] = py
    return env


# --- пути и файлы -------------------------------------------------------------------------------------------------

def root():
    return os.path.join(P.STATE, "merge-queue")


def _real_dir(p):
    try:
        return stat.S_ISDIR(os.lstat(p).st_mode)
    except OSError:
        return False


def ensure_dir(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.lexists(p):
        os.mkdir(p, 0o700)
    if not _real_dir(p):
        raise ValueError(f"{p} — не папка (или ссылка)")
    os.chmod(p, 0o700)
    return p


def req_file(repo, pr):
    owner, name = repo.split("/")
    return os.path.join(root(), f"{owner}__{name}__{int(pr)}.json")


def read_req(p):
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not REPO_RE.fullmatch(str(data.get("repo", ""))) \
            or not isinstance(data.get("pr"), int) or not SHA_RE.fullmatch(str(data.get("sha", ""))) \
            or not isinstance(data.get("created"), (int, float)):
        return None
    if os.path.basename(p) != os.path.basename(req_file(data["repo"], data["pr"])):
        return None
    if "batch" in data and not valid_batch(data["batch"], data["pr"]):
        return None
    return data


def valid_batch(batch, pr):
    """Пачка заявки (metis-0668): список номеров PR одного репозитория в порядке слияния, от 2 до MAX_BATCH, без
    повторов, с номером самой заявки."""
    return isinstance(batch, list) and 2 <= len(batch) <= MAX_BATCH and pr in batch \
        and all(type(n) is int and PR_RE.fullmatch(str(n)) for n in batch) and len(set(batch)) == len(batch)


def batch_key(req):
    """Чья пачка: (репозиторий, номера по порядку, время постановки) или None — заявка одна. Заявки одной пачки
    ставятся одним `merge request` под одним замком: ключ у них общий, у заявок другой постановки — свой."""
    return (req["repo"], tuple(req["batch"]), req["created"]) if req.get("batch") else None


def batch_members(req):
    """Заявки пачки req в очереди сейчас, по порядку слияния: только с тем же ключом (batch_key). Звать под замком
    merge-queue."""
    out = []
    for n in req["batch"]:
        p = req_file(req["repo"], n)
        cur = read_req(p) if os.path.lexists(p) else None
        if cur and batch_key(cur) == batch_key(req):
            out.append(cur)
    return out


def write_req(req):
    """Заявка — атомарно: временный файл без перехода по ссылке, затем rename."""
    d = ensure_dir(root())
    p = req_file(req["repo"], req["pr"])
    tmp = os.path.join(d, f".tmp.{os.getpid()}")
    with contextlib.suppress(FileNotFoundError):
        os.remove(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(req, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def same_req(req):
    """Заявка в очереди всё ещё эта: тот же SHA и то же время постановки. Звать под замком merge-queue."""
    p = req_file(req["repo"], req["pr"])
    cur = read_req(p) if os.path.lexists(p) else None
    return bool(cur) and cur["sha"] == req["sha"] and cur["created"] == req["created"]


def gone(req, rc=None):
    """Заявку сняли (cancel) или заменили новой, пока шёл проход: её не трогаем — ни согласия, ни записи обратно."""
    log(req, "gone", rc=rc)
    return "заявку сняли или заменили во время прохода — не трогаю"


def keep(req):
    """Отметку (wait_until, notified) — обратно в очередь, только если там та же заявка."""
    with P.lock("merge-queue"):
        if not same_req(req):
            return False
        write_req(req)
    return True


def mark_wait(req, state, why):
    """Ждёт ли заявка (state — итог check_all). Причина ожидания (сбой gh, CI идёт, GitHub ещё считает mergeable) —
    в файл заявки: её показывает `pantheon merge status` (Д2 argus #381); не ждёт — отметка снимается. Файл пишется,
    только когда отметка поменялась."""
    why = why if state == "wait" else None
    if req.get("waiting") != why:
        if why is None:
            req.pop("waiting", None)
        else:
            req["waiting"] = why
        keep(req)
    return why is not None


def drop(req, event, why=None, warn=False, how="по Touch ID"):
    """Снять заявку — только если в очереди та же: новую, поставленную во время прохода, не трогает. how — путь
    согласия для тревоги: «по Touch ID» или «по фразе» (metis-0980 Д3: на пути фразы окна не было)."""
    with P.lock("merge-queue"):
        if not same_req(req):
            return gone(req)
        with contextlib.suppress(FileNotFoundError):
            os.remove(req_file(req["repo"], req["pr"]))
    log(req, event, why=why)   # причина — для `pantheon merge status` (снятые за сутки, metis-0819)
    if warn:
        P.alert(f"слияние {req['repo']}#{req['pr']} ({req['sha'][:7]}) {how}: заявка снята — {why}", "pantheon-merge")
    return f"снята: {why or event}"


def log(req, event, **extra):
    rec = {"time": P.stamp(), "repo": req.get("repo"), "pr": req.get("pr"), "sha": req.get("sha"), "event": event}
    rec.update({k: v for k, v in extra.items() if isinstance(v, (int, float, bool, str)) or v is None})
    os.makedirs(P.path("logs"), exist_ok=True)
    with open(P.path("logs", "merge.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def allowed_repos():
    p = os.path.join(P.HOME, ".claude", "pantheon", "policy.toml")
    try:
        with open(p, "rb") as fh:
            pol = P.tomllib.load(fh)
    except (OSError, ValueError):
        return set()
    repos = (pol.get("merge_repos") or {}).get(MERGE_DIRECTION) if isinstance(pol.get("merge_repos"), dict) else None
    return {r.strip().lower() for r in repos if isinstance(r, str)} if isinstance(repos, list) else set()


# --- GitHub ---------------------------------------------------------------------------------------------------------

def gh_env():
    return {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}


def gh_path():
    # щелчок по уведомлению запускает проход с коротким PATH — gh из Homebrew ищется и там
    return shutil.which("gh", path=(os.environ.get("PATH") or "") + ":/opt/homebrew/bin:/usr/local/bin") or "gh"


def pr_view(repo, pr):
    """{headRefOid, state, isDraft, title, baseRefName, statusCheckRollup, changedFiles, isCrossRepository,
    headRepository, headRefName, mergeable, mergeStateStatus} или None — gh не ответил. isCrossRepository,
    headRepository, headRefName — голова PR из форка (ci_fork, metis-0649); последние два — сливается ли с base
    (merge_conflict, metis-0819)."""
    try:
        r = subprocess.run([gh_path(), "pr", "view", str(pr), "-R", repo, "--json",
                            "headRefOid,state,isDraft,title,baseRefName,statusCheckRollup,changedFiles,"
                            "isCrossRepository,headRepository,headRefName,mergeable,mergeStateStatus"],
                           capture_output=True, text=True, timeout=GH_TIMEOUT, env=gh_env())
        data = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return data if isinstance(data, dict) else None


def pr_files(repo, pr, view, raw=None):
    """Пути файлов PR (и previous_filename, как у шлюза guard) из REST pulls/N/files или None — gh не ответил или
    список неполон (не равен changedFiles). raw — список: в него кладутся сами записи файлов (для version_problem)."""
    count = view.get("changedFiles") if isinstance(view, dict) else None
    if not isinstance(count, int) or isinstance(count, bool):
        return None
    try:
        r = subprocess.run([gh_path(), "api", f"repos/{repo}/pulls/{pr}/files?per_page=100", "--paginate", "--jq",
                            ".[]"], capture_output=True, text=True, timeout=GH_TIMEOUT, env=gh_env())
        files = [json.loads(ln) for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(files, list) or len(files) != count or not all(isinstance(f, dict) for f in files):
        return None
    if raw is not None:
        raw.extend(files)
    paths = []
    for f in files:
        for k in ("filename", "previous_filename"):
            if f.get(k) is not None:
                if not isinstance(f[k], str):
                    return None
                paths.append(f[k])
    return paths


# номер версии поднимает workflow release на main после слияния (metis-0512) — как _version_problem шлюза guard:
# совпадение ответов на общих случаях сверяет test_merge. Проход сливает PR ядра мимо хука guard, поэтому сверка здесь
PLUGIN_MANIFEST_RE = re.compile(r"plugins/[^/]+/\.claude-plugin/plugin\.json")
RELEASES_FILE = ".claude-plugin/releases.json"
JSON_STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _touches_version(patch):
    for line in patch.splitlines():
        if line[:1] not in ("+", "-"):
            continue
        for m in JSON_STR_RE.finditer(line[1:]):
            try:
                val = json.loads(m.group(0))
            except ValueError:
                return True
            if isinstance(val, str) and val.strip().casefold() == "version":
                return True
    return False


def version_problem(files):
    """PR правит version в plugins/*/.claude-plugin/plugin.json (не новый и не удалённый файл; патча нет — тоже) или
    трогает .claude-plugin/releases.json — текст, иначе None."""
    hit = []
    for f in files:
        names = [n for n in (f.get("filename"), f.get("previous_filename")) if isinstance(n, str)]
        norm = [n.strip("/").casefold() for n in names]
        if not names:
            continue
        if RELEASES_FILE in norm:
            hit.append(f"{names[0]} (пишет только workflow release)")
        elif not any(PLUGIN_MANIFEST_RE.fullmatch(n) for n in norm) or f.get("status") in ("added", "removed"):
            continue
        elif not isinstance(f.get("patch"), str):
            hit.append(f"{names[0]} (патча нет — правку version не проверить)")
        elif _touches_version(f["patch"]):
            hit.append(f"{names[0]} (меняет version)")
    return f"PR трогает номер версии: {', '.join(hit)}" if hit else None


def is_core(path):
    """Ядро — как _is_core шлюза guard: папки CORE_DIR целиком и файлы CORE_FILES, без учёта регистра; ./, //, `..`
    в середине пути сводятся так же (posixpath.normpath, metis-0551 — совпадение сверяет test_merge_gate)."""
    p = posixpath.normpath(path.strip("/") or ".").strip("/").casefold()
    return p in {c.casefold() for c in CORE_FILES} or any(p == d or p.startswith(d + "/") for d in CORE_DIR)


def window_core(path):
    """Ядро для окна Touch ID: is_core или файл сборки и запуска окон BUILD_FILES (metis-0551)."""
    return is_core(path) or posixpath.normpath(path.strip("/") or ".").strip("/").casefold() in BUILD_FILES


# проверки GitHub на head PR (metis-0285, 0633, 0649, 0655): ci_verdict, ci_runs, ci_fork, ci_billing_ids,
# ci_billing, ci_job_unstarted, full_tests_record, required_checks, optional_checks, narrow_tests_record (metis-1050),
# REQUIRED_CHECKS, OPTIONAL_CHECKS, CI_RUNS_API, CI_BILLING, CI_ANNOTATIONS_API, CI_JOBS_API, FULL_TESTS, MAP_HASH_RE,
# CI_OK, CI_WAIT и CI_NONE —
# дословно те же, что в шлюзе guard (plugins/guard/hooks/merge_gate.py): плагины порознь,
# друг друга не импортируют, совпадение сверяет test_merge по AST. Правишь — правь оба
CI_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
CI_WAIT = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", ""}
CI_NONE = "проверки GitHub не получены"
# обязательные проверки (metis-0633): имя репозитория без владельца → (workflow, job, ветка base PR или None — любая).
# Имена — из .github/workflows репозитория: tests.yml гоняет на PR в main job affected (затронутое, Linux) и job full
# (полный набор на macos-15, metis-1111: репозиторий публичный, минуты бесплатны; при возврате в приватный, metis-1076,
# full снова уходит в OPTIONAL_CHECKS), check-traces.yml — job traces на любой PR (и на push: две записи traces).
# Совпадение с файлами workflows сверяет test_merge_gate. Обязательная засчитывается только по запуску Actions от
# события pull_request на этом head (ci_runs) и только с итогом SUCCESS: SKIPPED закрыл бы её job, который не
# запускался, push-запуск проверяет ветку без слияния с base, а NEUTRAL у job Actions не бывает — его ставят
# сторонние приложения проверок. Нет такого запуска — «ещё не встала», а не пропуск. Другие проверки репозитория:
# красная из OPTIONAL_CHECKS — предупреждение, красная любая другая — отказ (Д1 argus #235: новый job на PR, не
# внесённый ни в один список, не проходит шлюз молча). Репозиторий без записи — обязательна каждая проверка его rollup
# (SUCCESS/NEUTRAL/SKIPPED).
REQUIRED_CHECKS = {"agent-kit": (("tests", "affected", "main"), ("tests", "full", "main"),
                                 ("check-traces", "traces", None))}
# необязательные проверки (Д1 argus #235): имя репозитория без владельца → (workflow, job, почему необязательна — с
# номером задачи). Каждый job workflows, который идёт на pull_request, — в REQUIRED_CHECKS или здесь: сверяет
# test_merge_gate по файлам .github/workflows
OPTIONAL_CHECKS = {"agent-kit": ()}
# запуски Actions на head SHA: два GET REST (GraphQL — POST, его правило push ролям закрывает), связь — check_suite_id
CI_RUNS_API = ("repos/{repo}/actions/runs?head_sha={sha}&per_page=100",
               "repos/{repo}/commits/{sha}/check-runs?per_page=100")
# CI не запускался из-за лимита минут или оплаты GitHub Actions (metis-0655). Признак — по ответам GitHub, а не по
# памяти: в документации текста нет (docs.github.com: «usage is blocked», check-runs: conclusion и output), поэтому —
# по сохранённому ответу PR #222 (31.10, plugins/guard/tests/fixtures/ci-runs-pr222.json):
# проверка от Actions завершена с FAILURE, аннотация уровня failure на путь .github с этим текстом (запрос
# CI_ANNOTATIONS_API — только к таким проверкам).
# Текст поменяется — признака нет и отказ, как на любой красной.
# Аннотацию с тем же текстом может напечатать и сам job PR (`::error file=.github::…`), поэтому второе условие —
# job не стартовал (CI_JOBS_API, id проверки = id job): раннера не было и шагов нет. Это поле пишет GitHub, а не код
# job (docs.github.com/en/rest/actions/workflow-jobs: runner_id «integer or null», runner_name «string or null»,
# steps — массив; у заблокированных job PR #222 — 0, "" и [], у обычной красной PR #225 — номер раннера и 8 шагов)
CI_BILLING = ("The job was not started because recent account payments have failed or your spending limit needs to be "
              "increased")
CI_ANNOTATIONS_API = "repos/{repo}/check-runs/{id}/annotations?per_page=100"
CI_JOBS_API = "repos/{repo}/actions/jobs/{id}"
# полный набор тестов для записи на запасном пути (metis-0655): имя репозитория без владельца → команда после
# `pantheon review test --`. Засчитывается только запись с этой командой (full_tests_record); нет строки — запасного
# пути у репозитория нет, отказ
FULL_TESTS = {"agent-kit": ("heavy python3.14 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard "
                            "plugins/pantheon plugins/project-tools")}


def required_checks(repo, base):
    """Обязательные (workflow, job) для PR в repo (owner/name) с веткой base; base не строка — все записи."""
    got = REQUIRED_CHECKS.get(str(repo or "").rsplit("/", 1)[-1].lower(), ())
    return tuple((w, j) for w, j, b in got if b is None or not isinstance(base, str) or b == base)


def ci_fork(view):
    """Голова PR из форка по ответу gh pr view (metis-0649): None — isCrossRepository не true (PR из того же
    репозитория), иначе (owner/name форка в нижнем регистре, ветка head) из headRepository.nameWithOwner и
    headRefName; поле не строка — пустая строка на его месте, и ci_runs отвечает «не получены»."""
    if not isinstance(view, dict) or view.get("isCrossRepository") is not True:
        return None
    repo, branch = view.get("headRepository"), view.get("headRefName")
    name = repo.get("nameWithOwner") if isinstance(repo, dict) else None
    return (name.lower() if isinstance(name, str) else "", branch if isinstance(branch, str) else "")


def optional_checks(repo):
    """Необязательные (workflow, job) repo (owner/name) из OPTIONAL_CHECKS: их красная — только предупреждение."""
    return tuple((w, j) for w, j, _ in OPTIONAL_CHECKS.get(str(repo or "").rsplit("/", 1)[-1].lower(), ()))


def ci_runs(workflow_runs, check_runs, sha, pr, fork=None):
    """Запуски Actions PR pr на коммите sha с событием: [{workflowName, name, status, conclusion, event, id,
    annotations}] (id проверки и число её аннотаций — для ci_billing, metis-0655) по ответам
    CI_RUNS_API (actions/runs и check-runs). Не идут в список: проверка без запуска Actions с тем же check_suite_id
    (стороннее приложение с тем же именем), чужой head_sha и запуск, в pull_requests которого нет этого PR (запуск
    чужого PR на том же SHA). PR из форка (fork — ответ ci_fork, metis-0649): у его запусков GitHub pull_requests не
    заполняет, поэтому засчитывается запуск от pull_request, у которого head_repository.full_name и head_branch —
    форк и ветка этого PR (фильтру REST не верим, поля сверяются здесь); форк или ветка не получены — строка «не
    получены». Ответ неполон (total_count больше полученного: per_page=100 без пагинации, скрытой может быть красная
    запись) — строка «неполные данные CI»; не разобран — None."""
    if fork is not None and not all(fork):
        return f"{CI_NONE}: PR из форка, а его репозиторий или ветка head не получены (gh pr view)"
    try:
        wr, cr = workflow_runs["workflow_runs"], check_runs["check_runs"]
        if workflow_runs["total_count"] > len(wr) or check_runs["total_count"] > len(cr):
            return (f"{CI_NONE}: неполные данные CI — запусков {workflow_runs['total_count']} и проверок "
                    f"{check_runs['total_count']}, а получено {len(wr)} и {len(cr)}")
        if fork is None:
            suites = {r["check_suite_id"]: r for r in wr
                      if r["head_sha"] == sha and str(pr) in [str(p["number"]) for p in r["pull_requests"]]}
        else:
            suites = {r["check_suite_id"]: r for r in wr
                      if r["head_sha"] == sha and r["event"] == "pull_request"
                      and r["head_repository"]["full_name"].lower() == fork[0] and r["head_branch"] == fork[1]}
        out = []
        for c in cr:
            run = suites.get(c["check_suite"]["id"])
            if run is not None and c["head_sha"] == sha:
                info = c.get("output") if isinstance(c.get("output"), dict) else {}
                out.append({"workflowName": str(run.get("name") or ""), "name": str(c.get("name") or ""),
                            "status": str(c.get("status") or ""), "conclusion": str(c.get("conclusion") or ""),
                            "event": str(run.get("event") or ""), "id": c.get("id"),
                            "annotations": info.get("annotations_count")})
        return out
    except (TypeError, KeyError, AttributeError):
        return None


def ci_billing_ids(runs, required):
    """id проверок, чьи аннотации нужны для признака «CI не запускался: лимит минут или оплата» (metis-0655): каждая
    обязательная (required) есть среди runs от pull_request, у каждой её запись завершена с SUCCESS или с FAILURE,
    id — целое и аннотации есть; хоть одна FAILURE. Иначе пусто: признака нет, и запросов аннотаций шлюз не делает."""
    if not isinstance(runs, list):
        return []
    must, seen, ids = [tuple(r) for r in required], set(), []
    for c in runs:
        if not isinstance(c, dict) or c.get("event") != "pull_request":
            continue
        key = (str(c.get("workflowName") or ""), str(c.get("name") or ""))
        if key not in must:
            continue
        seen.add(key)
        status, concl = str(c.get("status") or "").upper(), str(c.get("conclusion") or "").upper()
        if status == "COMPLETED" and concl == "SUCCESS":
            continue
        n = c.get("annotations")
        if status != "COMPLETED" or concl != "FAILURE" or type(c.get("id")) is not int or type(n) is not int or n < 1:
            return []
        ids.append(c["id"])
    return ids if all(k in seen for k in must) else []


def ci_job_unstarted(job):
    """Job не стартовал (metis-0655): ответ CI_JOBS_API — словарь, где runner_id 0 или null, runner_name пусто или
    null и steps — пустой список. Ключа нет, тип другой, ответа нет — стартовал (признака лимита нет)."""
    if not isinstance(job, dict) or "runner_id" not in job or "runner_name" not in job:
        return False
    rid = job["runner_id"]
    return (rid is None or type(rid) is int and rid == 0) and job["runner_name"] in (None, "") \
        and job.get("steps") == []


def ci_billing(runs, required, notes, jobs):
    """CI не запускался из-за лимита минут или оплаты (metis-0655): ci_billing_ids не пуст и у каждой такой проверки
    в notes ({id: ответ CI_ANNOTATIONS_API — список}) есть аннотация уровня failure на путь .github, текст которой
    начинается с CI_BILLING, и её job в jobs ({id: ответ CI_JOBS_API}) не стартовал (ci_job_unstarted). Ответа нет
    (сбой gh) или он не того типа — признака нет."""
    ids = ci_billing_ids(runs, required)
    return bool(ids) and isinstance(notes, dict) and isinstance(jobs, dict) and all(
        isinstance(notes.get(i), list) and any(
            isinstance(a, dict) and a.get("annotation_level") == "failure" and a.get("path") == ".github"
            and str(a.get("message") or "").startswith(CI_BILLING) for a in notes[i])
        and ci_job_unstarted(jobs.get(i)) for i in ids)


def full_tests_record(repo, rec):
    """Запись tests — полный прогон этого репозитория (metis-0655): её команда — FULL_TESTS репозитория (имя без
    владельца, регистр не важен). Хук guard пишет всю команду `pantheon review test -- <команда>`, проход `pantheon
    outside test` — саму команду; `heavy` впереди не важен — проход ставит его сам. Комментарий — как в bash, только
    «#» в начале слова (после пробела): хвост ` # …` снимается, а `слово#…` — часть слова, и команда уже другая.
    Другая команда, лишние слова (`&& …`, `; …`), нет строки в FULL_TESTS — не засчитывается."""
    want = FULL_TESTS.get(str(repo or "").rsplit("/", 1)[-1].lower())
    cmd = rec.get("cmd") if isinstance(rec, dict) else None
    if not want or not isinstance(cmd, str):
        return False
    try:
        got, need = shlex.split(re.sub(r"\s#.*\Z", "", cmd, flags=re.S)), shlex.split(want)
    except ValueError:
        return False
    if len(got) > 3 and os.path.basename(got[0].rstrip("/")) == "pantheon" and got[1:4] == ["review", "test", "--"]:
        got = got[4:]
    got = got[1:] if got[:1] and os.path.basename(got[0]) == "heavy" else got
    need = need[1:] if need[:1] and os.path.basename(need[0]) == "heavy" else need
    return got == need


# узкая запись тестов на запасном пути (metis-0734; с metis-1050 09.11 — у любого PR, и ядра, и пачки): MAP_HASH_RE,
# narrow_tests_record и narrow_map_path — дословно те же, что в шлюзе guard (сверяет test_merge). Базу и карту шлюз guard
# сверяет git папки слияния (_narrow_problem), проход — через GitHub API (narrow_gh_problem)
MAP_HASH_RE = re.compile(r"[0-9a-f]{64}")


def narrow_tests_record(repo, rec):
    """Запись tests — узкий прогон этого репозитория (metis-0734) → (база, sha256 карты) или None. Команда — FULL_TESTS
    репозитория (full_tests_record) с одним `--affected` и одним `--base <SHA из 40 знаков>` (коммит, от которого
    раннер взял дифф: у `pantheon outside test --affected` — merge-base с base PR); files — непустой список меток, map —
    sha256 карты, по которой выбраны файлы. Другие ключи раннера (--only, --base=…), ref вместо SHA — None."""
    if not isinstance(rec, dict) or not isinstance(rec.get("cmd"), str):
        return None
    files, mp = rec.get("files"), rec.get("map")
    if not (isinstance(files, list) and files and all(isinstance(f, str) for f in files)) \
            or not (isinstance(mp, str) and MAP_HASH_RE.fullmatch(mp)):
        return None
    try:
        words = shlex.split(re.sub(r"\s#.*\Z", "", rec["cmd"], flags=re.S))
    except ValueError:
        return None
    # второй --base (или --affected) остаётся в rest — и full_tests_record его не примет
    if "--affected" not in words or "--base" not in words:
        return None
    i, j = words.index("--base"), words.index("--affected")
    base = words[i + 1] if i + 1 < len(words) else ""
    if not SHA_RE.fullmatch(base):
        return None
    rest = [w for k, w in enumerate(words) if k not in (i, i + 1, j)]
    return (base, mp) if full_tests_record(repo, {"cmd": shlex.join(rest)}) else None


def narrow_map_path(repo):
    """Путь карты affected-map.json от корня — рядом с run-tests.py команды FULL_TESTS репозитория; нет — None."""
    try:
        words = shlex.split(FULL_TESTS.get(str(repo or "").rsplit("/", 1)[-1].lower()) or "")
    except ValueError:
        return None
    script = next((w for w in words if posixpath.basename(w) == "run-tests.py"), None)
    return posixpath.join(posixpath.dirname(script), "affected-map.json") if script else None


# дельта мелкой правки проверенного PR (metis-0784, 0669): DELTA_* и delta_problem — дословно те же, что в шлюзе guard
# (сверяет test_merge). Шлюз guard считает дельту git папки слияния (_delta_link, _delta_heads), проход — тесты через
# GitHub API (delta_gh_problem), а argus — по решению шлюза guard (поле delta, code_facts)
DELTA_MAX_LINES = 200
DELTA_DEPTH = 4
# переименование в дельте — отказ (Д1 argus #420): git (-M) и GitHub compare (status renamed) находят его по-разному
DELTA_RENAME = "в дельте переименование — дельтой не засчитать (git и GitHub считают его по-разному): нужен полный круг"
DELTA_GATE_FILES = ("plugins/guard/hooks/merge_gate.py", "plugins/guard/hooks/guard_rules.py",
                    "plugins/pantheon/lib/merge.py", "plugins/pantheon/lib/review_rules.py")


def delta_problem(rows, core=None):
    """Дельта годится для узкого круга → None или почему нет. rows — [(путь, добавлено, удалено)] по файлам дельты,
    у двоичного файла числа None; rows None — дельту не посчитали. core — признак ядра (путь → bool): задан — правило
    argus (дельта не задевает ядро), не задан — правило тестов (не задевает файлы шлюза DELTA_GATE_FILES). Путь
    сводится, как в is_core: ./, //, `..`, регистр. Двоичный файл — отказ: строки не посчитать. Строк (добавлено +
    удалено) больше DELTA_MAX_LINES — отказ. Пустая дельта годится."""
    if rows is None:
        return "дельту с прошлого head не посчитать"
    total = 0
    for path, added, deleted in rows:
        p = posixpath.normpath(str(path).strip("/") or ".").strip("/").casefold()
        if core(p) if core else p in DELTA_GATE_FILES:
            return f"дельта задевает {'ядро' if core else 'файл шлюза слияния'} {path}"
        if not (isinstance(added, int) and isinstance(deleted, int)):
            return f"в дельте двоичный файл {path} — строки не посчитать"
        total += added + deleted
    if total > DELTA_MAX_LINES:
        return f"дельта {total} строк — больше {DELTA_MAX_LINES}"
    return None


def ci_verdict(rollup, required=(), runs=None, optional=()):
    """(ok|wait|fail|empty, текст, предупреждения) по statusCheckRollup head PR. CheckRun — по status и conclusion,
    StatusContext — по state; ключ проверки — (workflowName, name) или context. Итог ключа — худший из его записей:
    дубль имени (push и pull_request на одном SHA) не прячет красную запись зелёной. required — обязательные
    (workflow, job): судятся только по runs (ci_runs) от события pull_request, зелёный итог — только SUCCESS; красная
    или пропущенная — fail, нет такого запуска или идёт — wait, runs не получены или неполны (строка) — fail.
    Остальные проверки rollup: красная из optional (optional_checks) — предупреждение, красная любая другая — fail
    (Д1 argus #235). required пуст — обязательна каждая проверка rollup (SUCCESS, NEUTRAL, SKIPPED), пустой rollup —
    empty."""
    if not isinstance(rollup, list) or required and not isinstance(runs, (list, str)):
        return "fail", CI_NONE, []
    if required and isinstance(runs, str):
        return "fail", runs, []
    rank = {"ok": 0, "wait": 1, "fail": 2}
    seen, pr_runs = {}, {}  # ключ → (итог, слово итога, имя для текста)
    for c in rollup:
        if not isinstance(c, dict):
            return "fail", f"{CI_NONE}: проверка не разобрана", []
        if "conclusion" in c or "status" in c and "state" not in c:   # CheckRun
            status, concl = str(c.get("status") or "").upper(), str(c.get("conclusion") or "").upper()
            res = "wait" if status != "COMPLETED" else "ok" if concl in CI_OK else "fail"
            word = (status or "нет статуса") if res == "wait" else (concl or "нет итога")
            key = (str(c.get("workflowName") or ""), str(c.get("name") or ""))
        else:                                                            # StatusContext
            st = str(c.get("state") or "").upper()
            res = "wait" if st in CI_WAIT else "ok" if st in CI_OK else "fail"
            word = st or "нет статуса"
            key = ("", str(c.get("context") or ""))
        if key not in seen or rank[res] > rank[seen[key][0]]:
            seen[key] = (res, word, ("/".join(k for k in key if k) or "?")[:60])
    for c in runs or ():
        if not isinstance(c, dict) or c.get("event") != "pull_request":
            continue
        status, concl = str(c.get("status") or "").upper(), str(c.get("conclusion") or "").upper()
        res = "wait" if status != "COMPLETED" else "ok" if concl == "SUCCESS" else "fail"
        word = (status or "нет статуса") if res == "wait" else (concl or "нет итога")
        key = (str(c.get("workflowName") or ""), str(c.get("name") or ""))
        if key not in pr_runs or rank[res] > rank[pr_runs[key][0]]:
            pr_runs[key] = (res, word, "/".join(key)[:60])
    must = [tuple(r) for r in required] or list(seen)
    judge = pr_runs if required else seen
    if not must:
        return "empty", "", []
    opt = [tuple(r) for r in optional]
    notes = [f"необязательная проверка GitHub {v[2]} красная: {v[1]}" for k, v in seen.items()
             if k not in must and k in opt and v[0] == "fail"]
    red = [f"проверка GitHub {judge[k][2]} {'красная' if judge[k][1] not in CI_OK else 'не прошла'}: {judge[k][1]}"
           for k in must if k in judge and judge[k][0] == "fail"]
    red += [f"проверка GitHub {v[2]} красная: {v[1]} (её нет ни в обязательных, ни в необязательных — красная любая "
            "проверка на PR — отказ)" for k, v in seen.items() if k not in must and k not in opt and v[0] == "fail"]
    if red:
        return "fail", "; ".join(red), notes
    missing = ["/".join(k) for k in must if k not in judge]
    if missing:
        return ("wait", "обязательные проверки GitHub ещё не встали (засчитывается запуск от pull_request на этом "
                "коммите): " + ", ".join(missing), notes)
    going = [judge[k][2] for k in must if judge[k][0] == "wait"]
    if going:
        return "wait", "проверки GitHub ещё идут: " + ", ".join(going), notes
    return "ok", "", notes


def ci_runs_fetch(repo, pr, sha, fork=None):
    """Запуски Actions на head SHA с событием (metis-0633): два GET REST по CI_RUNS_API, список ci_runs или None —
    gh не ответил или ответ не разобран; fork — голова PR из форка (ci_fork, metis-0649)."""
    got = []
    for api in CI_RUNS_API:
        try:
            r = subprocess.run([gh_path(), "api", api.format(repo=repo, sha=sha)], capture_output=True, text=True,
                               timeout=GH_TIMEOUT, env=gh_env())
            got.append(json.loads(r.stdout) if r.returncode == 0 else None)
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        if got[-1] is None:
            return None
    return ci_runs(got[0], got[1], sha, pr, fork)


def ci_notes_fetch(repo, ids):
    """Аннотации проверок ids (metis-0655): {id: список по CI_ANNOTATIONS_API или None — gh не ответил или ответ не
    разобран}. ids — из ci_billing_ids; пусто — запросов нет."""
    out = {}
    for i in ids:
        try:
            r = subprocess.run([gh_path(), "api", CI_ANNOTATIONS_API.format(repo=repo, id=i)], capture_output=True,
                               text=True, timeout=GH_TIMEOUT, env=gh_env())
            out[i] = json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, ValueError, subprocess.SubprocessError):
            out[i] = None
    return out


def ci_jobs_fetch(repo, ids):
    """Данные job проверок ids (metis-0655): {id: ответ CI_JOBS_API или None — gh не ответил или ответ не разобран};
    id проверки = id job. ids — из ci_billing_ids; пусто — запросов нет."""
    out = {}
    for i in ids:
        try:
            r = subprocess.run([gh_path(), "api", CI_JOBS_API.format(repo=repo, id=i)], capture_output=True,
                               text=True, timeout=GH_TIMEOUT, env=gh_env())
            out[i] = json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, ValueError, subprocess.SubprocessError):
            out[i] = None
    return out


def ci_billing_fetch(repo, runs, required):
    """ci_billing с запросами аннотаций и job (metis-0655): True или False; None — ci_billing_ids не пуст, а ответ на
    аннотации или job хоть одной проверки не получен (сбой gh, metis-0813: TLS x509 из окна): признак не проверить."""
    ids = ci_billing_ids(runs, required)
    notes, jobs = ci_notes_fetch(repo, ids), ci_jobs_fetch(repo, ids)
    if any(notes.get(i) is None or jobs.get(i) is None for i in ids):
        return None
    return ci_billing(runs, required, notes, jobs)


def ci_state(rollup, required=(), runs=None, optional=()):
    """(ok|wait|fail, текст, предупреждения о красных необязательных) по ci_verdict. Проверок нет — wait: они ещё не
    встали; по 24 ч заявка всё равно гаснет. Обязательные есть, а запуски Actions не получены (runs None) — тоже wait:
    сбой gh не снимает заявку."""
    if required and runs is None:
        return "wait", "запуски Actions на head PR не получены", []
    state, why, notes = ci_verdict(rollup, required, runs, optional)
    if state == "empty":
        return "wait", "проверок GitHub пока нет", notes
    if state == "ok":
        return "ok", f"CI ✓ ({len(rollup)})", notes
    return state, why, notes


# --- шлюз -----------------------------------------------------------------------------------------------------------

def _reviewer(r):
    """Рецензент вердикта — пара (session_id, agent_id), как в шлюзе guard (metis-0158)."""
    by = r.get("by") if isinstance(r.get("by"), dict) else {}
    return by.get("session_id") or "", by.get("agent_id") or ""


# поле «вернули» (metis-0497, Д1 ревью PR #149 r2): pair_match, returned_lie, returned_lifts и base_counts
# (metis-0965) — дословно те же, что в шлюзе guard (merge_gate.py), сверяет test_merge (AST). Правишь — правь оба
def pair_match(pair, rec):
    """Пара agent8[/сессия8] из поля «вернули» или `pantheon review report` — рецензент записи rec (metis-0497):
    agent_id записи начинается с первой части, session_id — со второй (если она есть)."""
    parts = pair.lower().split("/") if isinstance(pair, str) else []
    by = rec.get("by") if isinstance(rec.get("by"), dict) else {}
    aid, sid = str(by.get("agent_id") or "").lower(), str(by.get("session_id") or "").lower()
    return (1 <= len(parts) <= 2 and all(parts) and bool(aid) and aid.startswith(parts[0])
            and (len(parts) == 1 or bool(sid) and sid.startswith(parts[1])))


def returned_lie(a, verdicts):
    """Пары поля «вернули» записи a, за которыми нет «вернуть» на этом PR, записанного раньше a (metis-0497): поле
    — слово лида, сверяется с журналом. verdicts — вердикты argus PR по порядку записи, a среди них. Поля нет — [].
    Пара самого рецензента a (agent8 — его agent_id, сессия любая) не сверяется (Д4 argus #382, вариант Б): опечатка
    лида в сессии (#286) отбросила бы «принять», которое снимает своё «вернуть» правилом 1 или 2, — лишний круг.
    Чужое «вернуть» и без неё снимает только взятый отчёт (returned_lifts)."""
    got = a.get("returned")
    if not isinstance(got, list):
        return []
    before = verdicts[:next((i for i, r in enumerate(verdicts) if r is a), len(verdicts))]
    return [p for p in got if not pair_match(str(p).split("/")[0], a)
            and not any(r.get("kind") == "reject" and pair_match(p, r) for r in before)]


def base_counts(rec, view):
    """Засчитывается ли «принять» rec для PR с view (metis-0965): base записи (baseRefName PR, когда argus записал
    вердикт) — нынешняя base PR. PR перевели на другую ветку (gh pr edit --base) — сливается другой дифф, «принять»
    было не про него. Поля base нет (запись до 0965 или gh не ответил при записи) или base PR неизвестна — не в счёт."""
    base = view.get("baseRefName") if isinstance(view, dict) else None
    return isinstance(base, str) and bool(base) and rec.get("base") == base


def returned_lifts(a, r):
    """Может ли «принять» a другого argus снять «вернуть» r (metis-0497). Без поля «вернули» — да, как раньше:
    свежий argus ведёт полный круг. С полем — повторный круг: снимает, только если a взяло отчёт вернувшего (его
    пара в reported — успешный `pantheon review report`, metis-0602). Иначе a — продолженный argus, Б вернувшего он
    не видел, и «вернуть» снимает только сам вернувший тем же вызовом (Д1 ревью PR #149 r2)."""
    if not isinstance(a.get("returned"), list):
        return True
    got = a.get("reported")
    return isinstance(got, list) and any(pair_match(p, r) for p in got)


def base_tip(repo, branch):
    """Живая вершина ветки branch (gh api …/git/ref/heads/<branch>) — SHA в нижнем регистре или None: сбой gh, не та
    ветка, не коммит. Тот же источник, что у шлюза guard (merge_gate._base_tip): с ним сверяется base_oid решения."""
    if not isinstance(branch, str) or not re.fullmatch(r"(?!.*\.\.)(?!/)(?!.*//)[A-Za-z0-9._/-]{1,200}(?<![/.])", branch):
        return None
    try:
        r = subprocess.run([gh_path(), "api", f"repos/{repo}/git/ref/heads/{branch}"], capture_output=True, text=True,
                           timeout=GH_TIMEOUT, env=gh_env())
        ref = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(ref, dict):
        return None
    obj = ref.get("object") if isinstance(ref.get("object"), dict) else {}
    sha = obj.get("sha")
    if ref.get("ref") != "refs/heads/" + branch or obj.get("type") != "commit" or not isinstance(sha, str) \
            or not re.fullmatch(r"[0-9a-f]{40}", sha.lower()):
        return None
    return sha.lower()


def code_facts(repo, pr, sha, view):
    """(same, differs, delta) — head PR, чей код шлюз guard сверил с кодом sha (metis-0966, 0396, 0443, вариант А): same
    — тот же код (отпечаток собственного диффа или слияние, merge_gate._merge_same), differs — посчитано, код другой,
    delta — sha лишь мелкая правка поверх head вне ядра (merge_gate._delta_heads, metis-0784; поле delta решения —
    список строк, иначе пусто: решения старше поля его не несут). Берётся
    последнее решение (запись kind "decision" в carry.jsonl, её пишет хук guard при `pantheon merge request`, P.
    review_decisions) на sha и нынешнюю base PR, записанное не раньше REQUEST_TTL назад и на нынешней вершине ветки
    base (base_oid решения — живая вершина base_tip: main ушёл вперёд — решение о другом слиянии). Нет решения —
    пустые множества: у прохода нет git папки слияния, другой коммит здесь — неизвестный код, и шлюз судит строго."""
    base = view.get("baseRefName") if isinstance(view, dict) else None
    tip = []
    for d in reversed(P.review_decisions(repo, pr)):
        try:
            age = P.now() - datetime.fromisoformat(str(d.get("time"))).timestamp()
        except ValueError:
            continue
        if d.get("sha") == sha and isinstance(base, str) and base and d.get("base") == base \
                and 0 <= age <= REQUEST_TTL:
            if not tip:
                tip.append(base_tip(repo, base))  # gh — только когда есть решение-кандидат, один раз
            if str(d.get("base_oid") or "").lower() != tip[0]:  # вершины нет (None) — тоже не та
                return frozenset(), frozenset(), frozenset()
            same, differs = set(d["same"]) - {sha}, set(d["differs"]) - {sha}
            delta = d.get("delta") if isinstance(d.get("delta"), list) else []
            delta = {h for h in delta if isinstance(h, str)} - same - {sha}
            return frozenset(same - differs), frozenset(differs - same), frozenset(delta)
    return frozenset(), frozenset(), frozenset()


def held_rejects(verdicts, sha, differs=frozenset()):
    """«Вернуть» argus на PR (любой head), которые в силе для слияния sha (metis-0465). verdicts — вердикты argus PR
    по порядку записи, «принять» — только засчитанные (review_accept_counts). Правило шлюза guard (merge_gate._lifts):
    снимает «принять», записанное после «вернуть», 1) того же рецензента на том же head или на sha; 2) другого argus на
    sha, если «вернуть» на head с другим кодом — head из differs решения шлюза guard (code_facts, metis-0966), — и у
    «принять» с полем «вернули» — только взявшего отчёт вернувшего (returned_lifts, metis-0497). Решения нет или код
    head «вернуть» не посчитан — второй argus «вернуть» не снимает: rebase с тем же кодом — не новый код. Третий head
    (правило 3 шлюза guard) «вернуть» не снимает: строже, на sha нужны свои «принять»."""
    def lifts(a, r):
        return a["kind"] == "accept" and (_reviewer(a) == _reviewer(r) and a["sha"] in (r["sha"], sha)
                                          or a["sha"] == sha != r["sha"] and r["sha"] in differs
                                          and returned_lifts(a, r))
    return [r for i, r in enumerate(verdicts) if r["kind"] == "reject" and not any(lifts(a, r) for a in verdicts[i + 1:])]


def reject_floor(verdicts, p=None, fresh=frozenset()):
    """Отсечка, как merge_gate._floor шлюза guard: номер последнего «вернуть», которое тот же рецензент не снял
    «принять» на том же head, или -1. «Принять», записанное до неё, не в счёт и на своём head: иначе откат force-push к
    коду, принятому до «вернуть», прошёл бы по старым «принять» (metis-0465). Для переноса дельтой (delta_carry,
    metis-0784) «вернуть» на прошлом head p снимает и «принять» того же рецензента на head кода sha (fresh): вернувший
    сам принял исправление. У шлюза guard переноса дельтой нет — там правило прежнее."""
    floor = -1
    for i, r in enumerate(verdicts):
        heads = {r["sha"], *fresh} if r["sha"] == p else {r["sha"]}
        if r["kind"] == "reject" and not any(a["kind"] == "accept" and _reviewer(a) == _reviewer(r)
                                             and a["sha"] in heads for a in verdicts[i + 1:]):
            floor = i
    return floor


def delta_carry(verdicts, sha, same, p):
    """Перенос «принять» с прошлого head p на sha дельтой (metis-0784; sha — мелкая правка поверх p вне ядра, поле
    delta решения шлюза guard) → засчитанные вердикты или None — перенос не годится. Берётся последний вердикт каждого
    рецензента на p и на head кода sha (sha и same) после отсечки reject_floor (p, fresh). Годится, если 1) не меньше
    MIN_ACCEPTS рецензентов, видевших весь код (вердикт на самом p), последним дали «принять»: вердикт только на head
    кода sha (sha или head из same — тот же код) — дельта-круг, полного круга он не заменяет (иначе вливание main
    после отказа «1 из 2» сделало бы дельта-«принять» полным, Б argus #420 r2); 2) хотя бы одно последнее «принять» —
    на head кода sha:
    дельту проверил argus; 3) каждый, кто вернул p, позже принял head кода sha. Порядок записей «принять» не важен
    (Б1 argus #420)."""
    fresh = {sha, *same}
    floor = reject_floor(verdicts, p, fresh)
    latest, full = {}, set()
    for i, r in enumerate(verdicts):
        if i > floor and (r["sha"] == p or r["sha"] in fresh):
            latest[_reviewer(r)] = r
            if r["sha"] == p:
                full.add(_reviewer(r))
    ok = [r for r in latest.values() if r["kind"] == "accept"]
    if len([r for r in ok if _reviewer(r) in full]) < MIN_ACCEPTS:
        return None
    if not any(r["sha"] in fresh for r in ok):
        return None
    if not all(any(a["kind"] == "accept" and _reviewer(a) == _reviewer(r) and a["sha"] in fresh
                   for a in verdicts[i + 1:]) for i, r in enumerate(verdicts) if r["kind"] == "reject" and r["sha"] == p):
        return None
    return ok


def _view_problem(view, sha):
    """Первые проверки gate по ответу gh pr view: (wait|fail, текст) или None — PR открыт, не черновик, на sha."""
    if not isinstance(view, dict):
        return "wait", "gh pr view не ответил"
    if str(view.get("state") or "").upper() != "OPEN":
        return "fail", f"PR не открыт ({view.get('state')})"
    if view.get("isDraft"):
        return "fail", "PR — черновик"
    if not view.get("baseRefName") or not isinstance(view.get("baseRefName"), str):
        return "wait", "gh pr view не дал base PR (baseRefName) — «принять» с base не сверить (metis-0965)"
    head = str(view.get("headRefOid") or "").lower()
    if head != sha:
        return "fail", f"у PR новый коммит {head[:7] or '?'} — нужна новая заявка"
    return None


def gate(repo, pr, sha, view):
    """Шлюз на этот head заново: (ok|wait|fail, текст). Записи шлюза пишет только хук guard (роли их не подделают)."""
    why = _view_problem(view, sha)
    if why:
        return why
    recs = P.review_records(repo)
    if not any(r.get("kind") == "tests" and r.get("sha") == sha for r in recs):
        return "fail", f"нет записи тестов шлюза на {sha[:12]}"
    verdicts = []
    for r in recs:
        by = r.get("by") if isinstance(r.get("by"), dict) else {}
        if r.get("kind") in ("accept", "reject") and by.get("agent_type") == "argus" and r.get("pr") == pr \
                and isinstance(r.get("sha"), str):
            # «принять» без перечня или не на Opus не засчитывается — как будто его нет; «вернуть» любой модели в силе.
            # Правило общее с итогом `pantheon review status` (P.review_accept_counts, metis-0393) — из
            # lib/review_rules.py, ядра защит (metis-0858)
            if r["kind"] == "accept" and not (P.review_accept_counts(r) and base_counts(r, view)):
                continue
            verdicts.append(r)
    # поле «вернули» называет рецензента без «вернуть» на PR — «принять» не в счёт, как в шлюзе guard (metis-0497)
    verdicts = [r for r in verdicts if not (r["kind"] == "accept" and returned_lie(r, verdicts))]
    # «вернуть» привязано к PR, на каком бы head оно ни было (metis-0465), как в шлюзе guard; код прошлых head — из
    # решения шлюза guard при `pantheon merge request` (code_facts, metis-0966)
    same, differs, delta = code_facts(repo, pr, sha, view)
    held = held_rejects(verdicts, sha, differs)
    if held:
        return "fail", (f"«вернуть» от argus на {', '.join(r['sha'][:12] for r in held)} в силе: оно привязано к PR, "
                        f"снимает его «принять» после него — того же рецензента или свежее на {sha[:12]} с другим "
                        "кодом (код сверяет шлюз guard при `pantheon merge request` из клона репозитория)")
    floor = reject_floor(verdicts)
    # «принять» с head того же кода переносится на sha, как в шлюзе guard (_carried, metis-0396): последний вердикт
    # каждого рецензента — на sha и этих head, в счёт — записанные после отсечки. «Принять» на head из delta (sha —
    # мелкая правка поверх вне ядра, metis-0784) — по правилу delta_carry: полный круг на нём и «принять» дельты
    latest = {}
    for i, r in enumerate(verdicts):
        if r["sha"] == sha or r["sha"] in same:
            latest[_reviewer(r)] = (i, r)
    counted = [r for i, r in latest.values() if i > floor]
    for p in delta if len(counted) < MIN_ACCEPTS else ():
        got = delta_carry(verdicts, sha, same, p)
        if got and len(got) >= MIN_ACCEPTS:
            counted = got
            break
    if len(counted) < MIN_ACCEPTS:
        cut = len(latest) - len(counted)
        moved = len({r["sha"] for r in verdicts if r["kind"] == "accept"} - {sha} - same - {r["sha"] for r in counted})
        return "fail", (f"«принять» от argus на Opus — {len(counted)} из {MIN_ACCEPTS}"
                        + (f"; ещё {cut} записано раньше «вернуть» на другом head — не в счёт (откат к принятому коду)"
                           if cut else "")
                        + (f"; «принять» на {moved} прошлых head не перенесено: код не сверен с {sha[:12]} или другой "
                           "— сверяет шлюз guard при `pantheon merge request` из клона репозитория; после мелкой правки "
                           "вне ядра переносится дельта-кругом (`pantheon review delta`): на том head полный круг — "
                           f"{MIN_ACCEPTS} argus, на этом — «принять» argus, и каждый, кто вернул тот head, принял "
                           "этот" if moved else ""))
    latest = counted
    required = required_checks(repo, view.get("baseRefName"))
    runs = ci_runs_fetch(repo, pr, sha, ci_fork(view)) if required else None
    state, why, notes = ci_state(view.get("statusCheckRollup"), required, runs, optional_checks(repo))
    # красные необязательные (OPTIONAL_CHECKS) — в тексте пропуска, и на запасном пути тоже (С1 argus #248)
    warn = "".join(f"; {n}" for n in notes)
    state, why = billing_verdict(repo, sha, recs, runs, required, state, why, view.get("baseRefName"))
    if state != "ok":
        return state, why
    return "ok", f"argus ×{len(latest)} ✓, {why}{warn}"


def billing_verdict(repo, sha, recs, runs, required, state, why, base_name=None):
    """Итог CI в gate (state, why — вердикт ci_verdict): (ok|wait|fail, текст). Зелёный — «CI ✓», идёт — как есть.
    Красный: CI не запускался из-за лимита минут или оплаты
    (metis-0655) — вместо CI засчитывается запись тестов на этот SHA с командой полного набора FULL_TESTS
    (full_tests_record), как в шлюзе guard (_billing_problem), или узкая (narrow_tests_record, metis-1050) — её база и
    карта сверены с GitHub (narrow_gh_problem); нет такой записи или FULL_TESTS у репозитория — fail по
    красной. Аннотации или job не получены (сбой gh) — wait: признак не проверить, а снять заявку по красной значило бы
    потерять запасной путь (metis-0813)."""
    if state != "fail":
        return state, "CI ✓" if state == "ok" else why
    billing = ci_billing_fetch(repo, runs, required)
    if billing is None:
        return "wait", f"аннотации CI не получены (сбой gh) — лимит минут или нет, не проверить; {why}"
    if not billing:
        return "fail", why
    mine = [r for r in recs if r.get("kind") == "tests" and r.get("sha") == sha]
    if any(full_tests_record(repo, r) for r in mine):
        return "ok", f"{BILLING_OK}{sha[:12]}"
    whys = []
    for base, mp in [got for r in mine for got in [narrow_tests_record(repo, r)] if got]:
        bad = narrow_gh_problem(repo, sha, base_name, base, mp, recs)
        if bad is None:
            return "ok", f"{BILLING_OK}{sha[:12]} (узкий прогон: затронутые PR тесты)"
        whys.append(bad)
    return "fail", (f"{why}; CI не запускался (лимит минут GitHub Actions), а записи полного набора тестов "
                    f"(FULL_TESTS) или годной узкой (--affected) на {sha[:12]} нет"
                    + (f"; узкая не засчитана: {whys[-1]}" if whys else ""))


def narrow_gh_problem(repo, sha, base_name, base, mp, recs=None, depth=DELTA_DEPTH):
    """Узкая запись (база base, sha256 карты mp) годится для head sha PR с веткой base base_name → None или почему
    нет (metis-1050). Как _narrow_problem шлюза guard, но через GitHub API — git папки слияния у прохода нет: base —
    merge-base head и живой вершины base (base_tip; GET compare), карта — sha256 файла narrow_map_path в дереве head
    (GET contents, сырой файл). recs — записи журнала репозитория: с ними база годится и как прошлый head (дельта,
    delta_gh_problem, metis-0784). Сбой gh — тоже причина: без сверки узкая запись не в счёт."""
    tip = base_tip(repo, base_name)
    if not tip:
        return "вершина ветки base не получена"
    try:
        r = subprocess.run([gh_path(), "api", f"repos/{repo}/compare/{tip}...{sha}", "--jq", ".merge_base_commit.sha"],
                           capture_output=True, text=True, timeout=GH_TIMEOUT, env=gh_env())
    except (OSError, subprocess.SubprocessError):
        return "merge-base head и base не получена (gh)"
    mb = r.stdout.strip().lower() if r.returncode == 0 else ""
    if not SHA_RE.fullmatch(mb):
        return "merge-base head и base не получена (gh)"
    if mb != base:
        delta = delta_gh_problem(repo, sha, base_name, base, recs, depth) if recs is not None else ""
        if delta is not None:
            return (f"узкий набор посчитан от {base[:12]}, а merge-base head и base — {mb[:12]}"
                    + (f"; как дельта прошлого head не засчитан: {delta}" if delta else ""))
    path = narrow_map_path(repo)
    if not path:
        return "карта affected-map.json для репозитория не задана"
    try:
        r = subprocess.run([gh_path(), "api", f"repos/{repo}/contents/{path}?ref={sha}", "-H",
                            "Accept: application/vnd.github.raw+json"], capture_output=True, timeout=GH_TIMEOUT,
                           env=gh_env())
    except (OSError, subprocess.SubprocessError):
        return f"карта {path} в дереве head не получена (gh)"
    if r.returncode != 0:
        return f"карта {path} в дереве head не получена (gh)"
    if hashlib.sha256(r.stdout).hexdigest() != mp:
        return f"карта в записи не та, что {path} в дереве head {sha[:12]}"
    return None


def delta_gh_problem(repo, sha, base_name, base, recs, depth):
    """Узкая запись на sha посчитана от прошлого head base (metis-0784), как _delta_link шлюза guard, через GitHub API
    → None или почему нет. GET compare base...sha: status ahead и merge-base — сам base (base — предок sha); файлы
    дельты — строки delta_problem без core (у переименования — оба пути; файл без patch — двоичный или большой, строки
    не в счёт; 300 файлов — предел ответа, дельту не посчитать). base покрыт: запись полного набора на base или узкая,
    годная для base сама (narrow_gh_problem), до DELTA_DEPTH звеньев."""
    try:
        r = subprocess.run([gh_path(), "api", f"repos/{repo}/compare/{base}...{sha}"], capture_output=True, text=True,
                           timeout=GH_TIMEOUT, env=gh_env())
        cmp = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        cmp = None
    if not isinstance(cmp, dict):
        return "сравнение с прошлым head не получено (gh)"
    mbc = cmp.get("merge_base_commit") if isinstance(cmp.get("merge_base_commit"), dict) else {}
    if cmp.get("status") != "ahead" or str(mbc.get("sha") or "").lower() != base:
        return "база не предок head — дельтой не засчитать (rebase между кругами: нужен полный круг)"
    files, rows = cmp.get("files"), []
    for f in files if isinstance(files, list) and len(files) < 300 else [None]:
        if not isinstance(f, dict) or not isinstance(f.get("filename"), str):
            rows = None
            break
        if f.get("status") == "renamed" or isinstance(f.get("previous_filename"), str):
            return DELTA_RENAME  # как _rename_problem шлюза guard
        n = (f.get("additions"), f.get("deletions")) if isinstance(f.get("patch"), str) else (None, None)
        rows.append((f["filename"], *n))
    why = delta_problem(rows)
    if why:
        return why
    if depth <= 0:
        return f"цепочка дельт длиннее {DELTA_DEPTH}"
    mine = [r for r in recs if r.get("kind") == "tests" and r.get("sha") == base]
    if any(full_tests_record(repo, r) for r in mine):
        return None
    whys = [narrow_gh_problem(repo, base, base_name, *got, recs, depth - 1) for r in mine
            for got in [narrow_tests_record(repo, r)] if got] or [f"на {base[:12]} нет записи тестов"]
    return None if None in whys else whys[-1]


# --- помощник Touch ID ----------------------------------------------------------------------------------------------

def helper():
    """Путь к помощнику окна или None. Только свой бинарник — STATE/bin/pantheon-touchid с отметкой sha256 исходника
    lib/touchid.swift рядом; отметка не та — пересборка. Переменной на подмену помощника нет (metis-0285, argus), а
    STATE проход берёт от HOME, не из PANTHEON_STATE (clean_env, metis-0303): окружение прохода задаёт launchd, а его
    меняет любой процесс владельца (launchctl setenv)."""
    return build_helper()


def build_helper(quiet=True):
    src = os.path.join(P.LIB, "touchid.swift")
    d = P.path("bin")
    out, mark = os.path.join(d, "pantheon-touchid"), os.path.join(d, "pantheon-touchid.sha256")
    try:
        want = hashlib.sha256(open(src, "rb").read()).hexdigest()
        ensure_dir(d)
        with contextlib.suppress(OSError):
            if open(mark).read().strip() == want and os.access(out, os.X_OK) and not os.path.islink(out):
                return out
        if not os.access(SWIFTC, os.X_OK):
            raise OSError("нет swiftc (Xcode Command Line Tools)")
        tmp, cache = out + f".new.{os.getpid()}", os.path.join(d, ".swift-cache")
        # окружение чистое: DEVELOPER_DIR, SDKROOT, TOOLCHAINS из launchctl setenv подменили бы компилятор
        r = subprocess.run([SWIFTC, "-O", "-module-cache-path", cache, "-o", tmp, src], capture_output=True,
                           text=True, timeout=300, env={"PATH": "/usr/bin:/bin", "HOME": P.HOME})
        if r.returncode != 0:
            raise OSError((r.stderr or r.stdout).strip().splitlines()[-1:] or ["swiftc упал"])
        os.chmod(tmp, 0o700)
        os.replace(tmp, out)
        with open(mark, "w") as fh:
            fh.write(want + "\n")
        return out
    except (OSError, ValueError, subprocess.SubprocessError) as e:   # ValueError: STATE/bin — ссылка или не папка
        if not quiet:
            err(f"помощник Touch ID не собран: {e}")
        return None


def window_text(req, view, why, paths):
    """Текст окна: сначала задетые файлы ядра (их владелец и подтверждает), заголовок автора PR — последним, в
    кавычках и коротко: он не перекроет список."""
    core = [p for p in dict.fromkeys(paths) if window_core(p)]
    shown, size = [], 0
    for p in core:
        if shown and size + len(p) > 200:
            break
        shown.append(p)
        size += len(p) + 2
    more = f" и ещё {len(core) - len(shown)}" if len(core) > len(shown) else ""
    hit = f"ядро: {', '.join(shown)}{more}" if core else "ядро не задето"
    title = " ".join(str(view.get("title") or "").split())[:60]
    return (f"Слить {req['repo']}#{req['pr']} ({req['sha'][:7]}), файлов {len(set(paths))}, {hit}. {why}. "
            f"Заголовок: «{title}»")[:400]


def nums(reqs):
    """«#7, #8» — номера PR заявок."""
    return ", ".join("#%d" % r["pr"] for r in reqs)


def batch_window_text(reqs, views, whys, paths):
    """Текст окна пачки (metis-0668): сначала задетые файлы ядра всех PR и число файлов — их владелец и
    подтверждает, затем номер, SHA и вердикт шлюза каждого PR в порядке слияния (его пишет проход, не автор PR),
    заголовки авторов — последними, в кавычках и коротко. Не длиннее 400 знаков — предел помощника окна. Ядро и
    номера с SHA всех PR влезают при MAX_BATCH PR и любых вердиктах (argus-263a Б1): ядру — место за вычетом номеров
    и коротких вердиктов, вердиктам — что осталось, поровну, вердикт запасного пути — коротко (BILLING_SHORT)."""
    n = len(reqs)
    head = f"Слить по очереди {n} PR {reqs[0]['repo']}, отказ шлюза у одного останавливает следующие."
    every = [x for p in paths for x in p]
    core = [x for x in dict.fromkeys(every) if window_core(x)]
    pre = [f"#{r['pr']} {r['sha'][:7]}" for r in reqs]
    fixed = len(" Вердикты: .") + sum(len(x) + 3 for x in pre)   # «#N sha7 » и «; » у каждого
    room = max(400 - len(head) - fixed - n * len(f"argus ×2 ✓, {BILLING_SHORT}") - 40, 60)
    shown, size = [], 0
    for x in core:
        if shown and size + len(x) > room:
            break
        shown.append(x)
        size += len(x) + 2
    more = f" и ещё {len(core) - len(shown)}" if len(core) > len(shown) else ""
    hit = f"ядро: {', '.join(shown)}{more}" if core else "ядро не задето"
    top = f"{head} Файлов {len(set(every))}, {hit}."
    per = min(48, max((400 - len(top) - fixed) // n, 0))
    short = [re.sub(re.escape(BILLING_OK) + r"[0-9a-f]+", BILLING_SHORT, " ".join(str(w).split()))[:per]
             for w in whys]
    items = "; ".join(f"{x} {w}".rstrip() for x, w in zip(pre, short))
    titles = "; ".join(f"#{r['pr']} «{' '.join(str(v.get('title') or '').split())[:40]}»" for r, v in zip(reqs, views))
    return f"{top} Вердикты: {items}. Заголовки: {titles}"[:400]


def window_info(out):
    """Поля из JSON-строки помощника (metis-0921): biometry, la_code, shown_sec — только эти и только с нужным типом;
    не JSON или чужие поля — пусто. Текст окна и всё лишнее в журнал не идёт. biometry помощника (LAContext.biometryType)
    — тип датчика Mac, а не способ подтверждения: при пароле и часах тоже touchID. В журнал оно идёт полем
    device_biometry (metis-0932); способ видно только косвенно — shown_sec около 0 — или в log show вне окна."""
    try:
        d = json.loads(out.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError, AttributeError):
        return {}
    if not isinstance(d, dict):
        return {}
    info = {}
    if isinstance(d.get("biometry"), str) and d["biometry"] in ("touchID", "faceID", "opticID", "none"):
        info["device_biometry"] = d["biometry"]
    if "la_code" in d and (d["la_code"] is None or type(d["la_code"]) is int):
        info["la_code"] = d["la_code"]
    if type(d.get("shown_sec")) in (int, float):
        info["shown_sec"] = d["shown_sec"]
    return info


def ask_full(text):
    """(код помощника, поля окна для журнала). Код: 0 — палец, 1 — отказ, 2 — окно не показать, 3 — время вышло;
    None — помощника нет."""
    h = helper()
    if not h:
        return None, {}
    try:
        r = subprocess.run([h, text, str(WINDOW_WAIT)], stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=WINDOW_WAIT + 60)
        return r.returncode, window_info(r.stdout)
    except (OSError, subprocess.SubprocessError):
        return 2, {}


def ask(text):
    """Только код помощника (см. ask_full); для handoff и других, кому поля окна не нужны."""
    return ask_full(text)[0]


def approve(req):
    """Строка согласия владельца — её сверяет шлюз guard. Пишет только этот проход, после пальца."""
    d = P.path("owner-log")
    if os.path.islink(d):
        raise OSError("owner-log — ссылка")
    ensure_dir(d)
    line = (f"{datetime.fromtimestamp(P.now()).astimezone().isoformat(timespec='seconds')} merge-approve "
            f"{req['repo']}#{req['pr']} {req['sha']}\n")
    fd = os.open(os.path.join(d, APPROVE_FILE), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(line)


# --- согласие фразой (metis-0959) -----------------------------------------------------------------------------------
# Слово владельца 07.11 (окно sb-gates-2, «давай»): вне Mac, без Touch ID, он пишет в окне Claude Code (remote-control
# с телефона) «слей #N <hex>». Проход находит фразу в журнале ваших слов и пишет ту же строку merge-approve, что после
# пальца: шлюз guard не меняется. Способ — в merge.jsonl (событие phrase: файл owner-log, строка, время записи; поле how
# у merged и merge-failed), а не в строке согласия: её формат сверяет APPROVE_RE шлюза.

def _owner_entries(path):
    """Записи журнала ваших слов owner-log/<окно>.md: [(время, заголовок-время, пометка, номер строки заголовка,
    первая непустая строка текста)]. Формат — append_owner_line в hooks/ctx.py: заголовок «## ГГГГ-ММ-ДД ЧЧ:ММ:СС[ ·
    пометка]» с начала строки; строки текста, которые начинаются с «##», хук сдвигает пробелом — заголовка в тексте нет.
    Ссылка, не обычный файл, сбой чтения — пусто."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return []
    try:
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return []
            lines = fh.read().decode("utf-8", "replace").split("\n")
    except OSError:
        return []
    out, cur = [], None
    for i, ln in enumerate(lines, 1):
        m = OWNER_ENTRY_RE.fullmatch(ln)
        if m:
            try:
                t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                t = None
            if t is not None:
                cur = [t, m.group(1), m.group(2).strip().removeprefix("·").strip(), i, None]
                out.append(cur)
                continue
        if cur is not None and cur[4] is None and ln.strip():
            cur[4] = ln.strip()
    return [tuple(e) for e in out]


def phrases(now):
    """Фразы «слей #N <hex>» владельца за PHRASE_TTL: [{pr, hex, t, file, line, at, key}]; отзыв «[стоп, ]не сливай
    #N» (metis-0970) — та же запись с hex None и revoke True.
    Источник — только файлы owner-log/*.md верхнего уровня: их пишет хук ctx.py owner-log из ввода, который Claude Code
    пометил вашим (origin.kind human), без обёрток NOT_OWNER — сообщений других сессий, отчётов субагентов, уведомлений
    задач, «[Пантеон: …]»; роли в owner-log не пишут. unconfirmed/ (ввод без пометки транскрипта) — не в счёт.
    Запись — без пометки: принятая подсказка Claude, окно вопросов и ответ в чате — не фраза. Фраза — целиком первая
    непустая строка сообщения (вставленный дальше текст её не даст); «да» без номера и короче 7 hex — не фраза."""
    d = P.path("owner-log")
    if os.path.islink(d) or not _real_dir(d):
        return []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    out = []
    for name in names:
        if not name.endswith(".md") or name.startswith("."):
            continue
        for t, at, note, line, first in _owner_entries(os.path.join(d, name)):
            if note or first is None or not -PHRASE_SKEW <= now - t <= PHRASE_TTL:
                continue
            m = PHRASE_RE.fullmatch(first)
            if m:
                pr, hx = int(m.group(1)), m.group(2).lower()
                out.append({"pr": pr, "hex": hx, "t": t, "file": name, "line": line, "at": at,
                            "key": f"{name}|{at}|{pr}|{hx}"})
            m = REVOKE_RE.fullmatch(first)
            if m:
                pr = int(m.group(1))
                out.append({"pr": pr, "hex": None, "revoke": True, "t": t, "file": name, "line": line, "at": at,
                            "key": f"{name}|{at}|{pr}|-"})
    return out


def queue():
    """Заявки в очереди сейчас (для однозначности фразы)."""
    r = root()
    try:
        names = sorted(os.listdir(r)) if _real_dir(r) else []
    except OSError:
        return []
    return [q for q in (read_req(os.path.join(r, f)) for f in names if FILE_RE.fullmatch(f)) if q]


def used_phrases():
    """Использованные фразы {ключ: время}; файла нет — пусто; не прочитать или битый — None (тогда фраза не в силе)."""
    try:
        fd = os.open(P.path(PHRASES_FILE), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    try:
        with os.fdopen(fd, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    used = data.get("used") if isinstance(data, dict) else None
    return used if isinstance(used, dict) else None


def find_phrase(req):
    """Фраза владельца, которая даёт согласие на эту заявку, или None. Решает последняя фраза на этот номер PR (позже
    «слей #N <другой hex>» — передумал, позже «не сливай #N» — отозвал, metis-0970); две разные в одну секунду или
    фраза и отзыв в одну секунду — неоднозначно, не в силе. Её hex — начало SHA заявки (он же
    head PR: шлюз сверяет его заново), фраза ещё не использована, и в очереди нет другой заявки с тем же номером и
    тем же началом SHA (другой репозиторий). Вызывать можно и под замком merge-queue: сама замков не берёт."""
    mine = [p for p in phrases(P.now()) if p["pr"] == req["pr"]]
    if not mine:
        return None
    last = max(p["t"] for p in mine)
    top = [p for p in mine if p["t"] == last]
    ph = top[-1]
    if len({p["hex"] for p in top}) != 1 or ph.get("revoke") or not req["sha"].startswith(ph["hex"]):
        return None
    used = used_phrases()
    if used is None or ph["key"] in used:
        return None
    if sum(1 for q in queue() if q["pr"] == ph["pr"] and q["sha"].startswith(ph["hex"])) != 1:
        return None
    return ph


def mark_phrase(ph):
    """Фраза использована — до строки согласия, под замком merge-queue: одна фраза, одно согласие. Не записать —
    исключение, и ни строки согласия, ни слияния."""
    used = used_phrases()
    if used is None:
        raise OSError(f"{PHRASES_FILE} не прочитать")
    t = P.now()
    used = {k: v for k, v in used.items() if isinstance(v, (int, float)) and t - v <= PHRASES_KEEP}
    used[ph["key"]] = t
    p = P.path(PHRASES_FILE)
    tmp = f"{p}.tmp.{os.getpid()}"
    with contextlib.suppress(FileNotFoundError):
        os.remove(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"used": used}, fh, ensure_ascii=False)
    os.replace(tmp, p)


def gh_merge(req):
    try:
        r = subprocess.run([gh_path(), "pr", "merge", str(req["pr"]), "-R", req["repo"], "--match-head-commit",
                            req["sha"], "--merge"], capture_output=True, text=True, timeout=MERGE_TIMEOUT, env=gh_env())
        return r.returncode, " ".join((r.stderr or r.stdout).split())[:200]
    except (OSError, subprocess.SubprocessError) as e:
        return 1, type(e).__name__


def fallback_notify(req, window):
    """Запасной путь: уведомление, щелчок по которому запускает `pantheon merge run --click` от имени владельца.
    window — текст окна (задетое ядро, заголовок PR)."""
    # путь программы — realpath: ссылку current после проверки не перевесить (argus-b 0303, п. 2)
    base = os.path.realpath(P.CURRENT if os.path.isdir(P.CURRENT) else P.PLUGIN)
    # щелчок запускает команду в окружении уведомления (launchd): окружение и интерпретатор — свои, через env -i
    env = " ".join(shlex.quote(f"{k}={v}") for k, v in pass_env().items())
    cmd = f"/usr/bin/env -i {env} {shlex.quote(os.path.join(base, 'bin', 'pantheon'))} merge run --click"
    text = f"{window[:300]}. Щёлкните — откроется окно Touch ID"
    return post_notice(text, cmd, f"Слияние ядра|{text}|execute:{cmd}|merge\n")


def post_notice(text, cmd, line):
    """Уведомление «Слияние ядра»: cmd — что запустит щелчок (None — ничего). Тест — строка line в файл (журнал
    PANTHEON_NOTIFY_LOG или STATE/notify-test.log), на экран владельца не идёт. True — ушло."""
    if os.environ.get("PANTHEON_NOTIFY_LOG"):   # только из TEST: clean_env окружение launchd сняла
        with open(os.environ["PANTHEON_NOTIFY_LOG"], "a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    tn = P._notifier()
    if not tn or os.environ.get("PANTHEON_NO_NOTIFY"):
        return False
    if P.notify_offscreen():   # STATE не настоящая (тест, проба) — на экран владельца не показывать
        with open(P.path("notify-test.log"), "a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    argv = [tn, "-title", "Слияние ядра", "-message", text, "-group", "pantheon-merge"]
    if cmd:
        argv += ["-execute", cmd]
    r = subprocess.run(argv, capture_output=True, timeout=15)
    return r.returncode == 0


def notify_merged(req, phrase=None):
    """После rc 0 gh pr merge — одно уведомление владельцу «слит repo#N (sha7)» (metis-0921): он не видит окон Touch ID
    и иначе о слиянии не узнаёт; слит по фразе (metis-0959) — с её местом в owner-log. Сбой уведомления слияния не
    отменяет — оно уже сделано."""
    text = f"слит {req['repo']}#{req['pr']} ({req['sha'][:7]})"
    if phrase:
        text += f" фразой из owner-log/{phrase['file']} {phrase['at']}"
    try:
        return post_notice(text, None, f"Слияние ядра|{text}||merged\n")
    except (OSError, subprocess.SubprocessError):
        return False


# --- управляемые настройки guard (metis-0710) ---------------------------------------------------------------------
# Решение владельца 02.11 (metis-managed-auto, «А — да, Touch ID»): файл /Library/…/managed-settings.json (P.MANAGED)
# отстал от проверенного дерева guard (verified.json, installed_dir) — проход показывает системное окно прав
# администратора macOS (Touch ID или пароль входа) «Обновить управляемые настройки guard до версии X». Права root даёт
# только это окно: окно LocalAuthentication (touchid.swift) подтверждает владельца, но root не даёт. Файл ставит
# скрипт root после касания: копия во временный файл рядом, сверка sha256 с проверенным файлом, chown, chmod, mv.
# Отказ, время вышло или окно не показать — карточка «Руками» с командой sudo и тревога; на ту же версию окно снова не
# раньше MANAGED_RETRY. Окно роли сюда не доходит: проход запускает только тик (cmd_run — отказ из окна Claude Code,
# `pantheon merge run` ролям закрыт guard), а песочница окна не даёт ни osascript, ни записи в /Library.
MANAGED_RETRY = 6 * 3600             # на ту же версию окно не чаще раза в 6 часов
MANAGED_WAIT = 120                   # сколько окно ждёт пальца
MANAGED_STATE = "managed-update.json"   # STATE: {sha, version, asked, result, task} и installed — что поставлено
OSASCRIPT = "/usr/bin/osascript"     # абсолютный путь: PATH прохода подменяем (launchctl setenv)
ROOT_OWNER = "0:0"                   # root:wheel; тестовая обвязка ставит свой uid:gid
ASK_ROOT = ("on run argv", "do shell script (item 1 of argv) with prompt (item 2 of argv) with administrator privileges",
            "end run")


def managed_source():
    """Проверенный файл: (путь, байты, версия) managed-settings.json из дерева guard, чей хеш совпал с verified.json
    (installed_dir). Клон маркетплейса — никогда; проверенного дерева или файла нет — None. Записи о guard в
    verified.json нет (guard не ставили) — None без тревоги installed_dir."""
    d = P.installed_dir("guard") if P.verified_record("guard") else None
    if not d:
        return None
    src = os.path.join(d, "managed-settings.json")
    try:
        with open(src, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    version = "?"
    with contextlib.suppress(OSError, ValueError, AttributeError):
        with open(os.path.join(d, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            version = str(json.load(fh).get("version") or "?")[:40]
    return src, data, version


def _managed_now():
    """(проверенный файл или None, байты поставленного или None — его нет или не прочитать). Поставленного нет — дерево
    guard не сверяется вовсе."""
    try:
        with open(P.MANAGED, "rb") as fh:
            cur = fh.read()
    except OSError:
        return None, None
    return managed_source(), cur


def _mstate():
    st = P.read_json(P.path(MANAGED_STATE), {})
    return st if isinstance(st, dict) else {}


def _close_card(tid, result):
    if tid:
        with contextlib.suppress(Exception):   # карточку закрыли или удалили руками — не беда
            P.tasks_mod().task_set(P.PANTHEON, P.now(), tid, {"status": "done", "result": result},
                                   actor="плановый проход", force=result)


def _settled(st, src, how):
    """Поставленный файл совпал с проверенным: записать версию, закрыть карточку «Руками», если она была."""
    _close_card(st.get("task"), f"управляемые настройки поставлены {how}")
    P.write_json(P.path(MANAGED_STATE), {"installed": {"version": src[2], "sha": hashlib.sha256(src[1]).hexdigest(),
                                                       "at": int(P.now()), "how": how}})


def managed_check():
    """Для тика: нужен ли проход ради управляемых настроек — поставленный файл есть, не совпадает с проверенным, и на
    эту версию окна не было последние MANAGED_RETRY. Файла в /Library нет — не отставание: первый раз его ставит
    владелец (README guard). Совпал, а карточка «Руками» открыта (поставили командой) — закрыть её.
    → проверенный файл (путь, байты, версия), если проход нужен, иначе None."""
    src, cur = _managed_now()
    if not src:   # поставленного нет или не прочитать — src тоже None (_managed_now)
        return None
    st = _mstate()
    if cur == src[1]:
        if st.get("task"):
            _settled(st, src, "командой")
        return None
    asked = st.get("asked")
    recent = isinstance(asked, (int, float)) and 0 <= P.now() - asked < MANAGED_RETRY
    return None if st.get("sha") == hashlib.sha256(src[1]).hexdigest() and recent else src


def root_script(src, dest, sha):
    """Скрипт root: копия проверенного файла во временный рядом с dest, sha256 копии — тот, что сверил проход (файл
    подменили после сверки — код 65, ничего не поставлено), владелец ROOT_OWNER, 644, замена одной операцией mv."""
    q = shlex.quote
    return (f"set -eu; umask 022; d={q(os.path.dirname(dest))}; /bin/mkdir -p \"$d\"; "
            "t=$(/usr/bin/mktemp \"$d/.managed-settings.XXXXXX\"); trap '/bin/rm -f \"$t\"' EXIT; "
            f"/bin/cat < {q(src)} > \"$t\"; "
            f"[ \"$(/usr/bin/shasum -a 256 < \"$t\" | /usr/bin/cut -c1-64)\" = {sha} ] || exit 65; "
            f"/usr/sbin/chown {ROOT_OWNER} \"$t\"; /bin/chmod 644 \"$t\"; /bin/mv -f \"$t\" {q(dest)}")


def manual_command(src, dest):
    q = shlex.quote
    return (f"sudo mkdir -p {q(os.path.dirname(dest))} && sudo install -m 644 -o root -g wheel {q(src)} {q(dest)}")


def ask_root(script, text):
    """Окно прав администратора и скрипт от root после касания → ok | refused | timeout | no-window (код N)."""
    argv = [OSASCRIPT] + [a for line in ASK_ROOT for a in ("-e", line)] + [script, text]
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=MANAGED_WAIT)
    except subprocess.TimeoutExpired:   # osascript убит — окно закрыто, касание позже не засчитывается
        return "timeout"
    except OSError as e:
        return f"no-window ({type(e).__name__})"
    if r.returncode == 0:
        return "ok"
    if "(-128)" in (r.stderr or ""):   # «Отменить» в окне: User canceled
        return "refused"
    return f"no-window (код {r.returncode}: {' '.join((r.stderr or '').split())[-120:]})"


WHY_RU = {"refused": "вы отменили окно", "timeout": f"окно {MANAGED_WAIT} с ждало касания"}


def managed_pass():
    """Шаг прохода: отставание → окно → установка; без касания — карточка «Руками» и тревога. → строка для журнала."""
    src = managed_check()
    if not src:
        return "в порядке или окно на эту версию уже было"
    if P.idle_sec() > PRESENT_SEC:
        return "отстали — ждёт: вас нет у Mac"
    path_, data, version = src
    sha = hashlib.sha256(data).hexdigest()
    st = _mstate()
    # попытка засчитана до окна (ревью argus-274b, Д1): проход оборвали после окна (срок тика, сбой карточки) — следующий
    # не покажет окно на ту же версию раньше MANAGED_RETRY, а не каждую минуту
    P.write_json(P.path(MANAGED_STATE), dict(st, sha=sha, version=version, asked=int(P.now()), result="окно показано"))
    res = ask_root(root_script(path_, P.MANAGED, sha), f"Обновить управляемые настройки guard до версии {version}")
    if res == "ok":
        try:
            with open(P.MANAGED, "rb") as fh:
                res = "ok" if fh.read() == data else "после касания файл не тот"
        except OSError as e:
            res = f"после касания файла нет ({type(e).__name__})"
    if res == "ok":
        _settled(st, src, "по касанию")
        return f"обновлены до версии {version}"
    cmd = manual_command(path_, P.MANAGED)
    why = WHY_RU.get(res, res)
    tid = st.get("task")
    if tid and st.get("sha") != sha:   # карточка прошлой версии: команда в ней уже не та
        _close_card(tid, f"заменена карточкой версии {version}")
        tid = None
    if not tid:
        with contextlib.suppress(OSError, ValueError):
            tid, _ = P.tasks_mod().task_new(
                P.PANTHEON, P.now(), MERGE_DIRECTION, f"Обновить управляемые настройки guard до {version}",
                owner="owner", actor="плановый проход", priority=1,
                text=(f"Управляемые настройки ({P.MANAGED}) отстали от проверенной версии guard {version}. Окно прав "
                      f"администратора не дало установить: {why}. Плановый проход спросит снова не раньше чем через "
                      f"{MANAGED_RETRY // 3600} ч. Или в своём терминале:\n\n    {cmd}\n\n"
                      "Карточка закроется сама, когда файл совпадёт с проверенным."))
    P.write_json(P.path(MANAGED_STATE), dict(st, sha=sha, version=version, asked=int(P.now()), result=res, task=tid))
    P.alert(f"управляемые настройки guard отстали от версии {version}: окно не дало установить ({why})"
            + (f" — карточка {tid}" if tid else "") + f"; команда: {cmd}", "pantheon-managed")
    return f"не обновлены ({why})" + (f", карточка {tid}" if tid else "")


# --- команды --------------------------------------------------------------------------------------------------------

def parse_target(args):
    """<N> -R <owner/repo> в любом порядке → (repo, pr) или None."""
    if len(args) != 3 or "-R" not in args[:2]:
        return None
    i = args.index("-R")
    repo = args[i + 1].lower() if i + 1 < len(args) else ""
    rest = [a for j, a in enumerate(args) if j not in (i, i + 1)]
    if len(rest) != 1 or not PR_RE.fullmatch(rest[0]) or not REPO_RE.fullmatch(repo):
        return None
    return repo, int(rest[0])


def parse_targets(args):
    """<N> [<N2> …] -R <owner/repo>, -R в любом месте → (repo, [номера по порядку]) или None. Номеров от 1 до
    MAX_BATCH, без повторов."""
    if args.count("-R") != 1:
        return None
    i = args.index("-R")
    repo = args[i + 1].lower() if i + 1 < len(args) else ""
    rest = [a for j, a in enumerate(args) if j not in (i, i + 1)]
    if not 1 <= len(rest) <= MAX_BATCH or not all(PR_RE.fullmatch(a) for a in rest) or len(set(rest)) != len(rest) \
            or not REPO_RE.fullmatch(repo):
        return None
    return repo, [int(a) for a in rest]


def cmd_request(args):
    """Заявка на один PR или пачку (metis-0668: одно окно Touch ID на все). Пачка ставится целиком или никак: шлюз
    не пройден хоть у одного — заявок нет ни на один."""
    target = parse_targets(args)
    if not target:
        err(USAGE)
        return 2
    repo, prs = target
    if repo not in allowed_repos():
        err(f"pantheon merge request: {repo} не из [merge_repos] {MERGE_DIRECTION} в policy.toml — заявки нет")
        return 2
    heads, bad, waits = {}, [], []
    for pr in prs:
        view = pr_view(repo, pr)
        if view is None:
            err(f"pantheon merge request: gh pr view {pr} -R {repo} не ответил — заявки нет")
            return 1
        sha = str(view.get("headRefOid") or "").lower()
        if not SHA_RE.fullmatch(sha):
            err(f"pantheon merge request: у PR #{pr} нет head SHA — заявки нет")
            return 1
        state, why = gate(repo, pr, sha, view)
        # конфликт с base — заявки нет, BLOCKED и «GitHub ещё считает» — заявка ждёт (metis-0987), как в check_all
        conflict = merge_conflict(view) if state != "fail" else None
        if conflict and (conflict[0] == "fail" or state == "ok"):
            state, why = conflict
        if state == "fail":
            bad.append(f"#{pr}: {why}" if len(prs) > 1 else why)
        elif state != "ok":
            waits.append(why.lower() if len(prs) == 1 else f"#{pr}: {why}")
        heads[pr] = sha
    if bad:
        err(f"pantheon merge request: шлюз не пройден — {'; '.join(bad)}. Заявки нет"
            + (" ни на один PR пачки" if len(prs) > 1 else ""))
        return 1
    who = " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "владелец").split())[:40]
    created = int(P.now())
    reqs = [{"repo": repo, "pr": pr, "sha": heads[pr], "by": who, "created": created} for pr in prs]
    if len(prs) > 1:
        for req in reqs:
            req["batch"] = list(prs)
    with P.lock("merge-queue"):
        olds = [read_req(req_file(repo, pr)) if os.path.lexists(req_file(repo, pr)) else None for pr in prs]
        if all(o and o["sha"] == heads[o["pr"]] and o.get("batch") == r.get("batch") for o, r in zip(olds, reqs)) \
                and len({o["created"] for o in olds}) == 1:
            what = f"заявка {repo}#{prs[0]} ({heads[prs[0]][:7]})" if len(prs) == 1 else \
                f"пачка {repo} {', '.join(f'#{n}' for n in prs)}"
            print(f"{what} уже стоит")
            return 0
        for req in reqs:
            write_req(req)
    for req in reqs:
        log(req, "request", batch=",".join(map(str, prs)) if len(prs) > 1 else None)
    later = ("" if not waits else f" и {'; '.join(waits)} закончатся" if len(prs) == 1
             else f", а у PR закончится ожидание ({'; '.join(waits)})")
    if len(prs) == 1:
        print(f"Заявка {repo}#{prs[0]} ({heads[prs[0]][:7]}) поставлена. Окно Touch ID покажет плановый проход, когда вы "
              f"у Mac{later}; без ответа за {REQUEST_TTL // 3600} ч заявка гаснет.")
    else:
        print(f"Пачка {repo}: {', '.join(f'#{n} ({heads[n][:7]})' for n in prs)} поставлена. Одно окно Touch ID на все "
              f"покажет плановый проход, когда вы у Mac{later}; сливает по очереди, отказ одного останавливает "
              f"следующие; без ответа за {REQUEST_TTL // 3600} ч пачка гаснет.")
    return 0


def merge_conflict(view):
    """Сливается ли PR с base по gh pr view (metis-0819): mergeable CONFLICTING или mergeStateStatus DIRTY — (fail,
    «конфликт с <base>»): окно не показывать, gh pr merge всё равно упадёт; GitHub ещё считает (UNKNOWN, поля нет) —
    (wait, …), проход попробует позже; защита ветки base не даёт слить (BLOCKED: обязательные проверки или ревью
    GitHub) — тоже wait (metis-0987): окно не показывать, палец на PR, который gh pr merge не сольёт, не тратить; без
    ответа заявка гаснет за REQUEST_TTL. После пальца wait не помеха (check_all), там решает gh pr merge. Сливается —
    None."""
    m, s = str(view.get("mergeable") or "").upper(), str(view.get("mergeStateStatus") or "").upper()
    base = view.get("baseRefName") or "base"
    if m == "CONFLICTING" or s == "DIRTY":
        return "fail", f"конфликт с {base} (mergeable {m or '?'}, {s or '?'}) — нужен новый коммит и новая заявка"
    if m != "MERGEABLE" or s in ("", "UNKNOWN"):
        return "wait", f"GitHub ещё не посчитал, сливается ли PR с {base} (mergeable {m or '?'}, {s or '?'})"
    if s == "BLOCKED":
        return "wait", (f"GitHub не даёт слить в {base}: защита ветки (BLOCKED — обязательные проверки или ревью "
                        "GitHub не пройдены)")
    return None


def check_all(req, after=False):
    """Все условия заново: (ok|wait|fail, текст, view, пути файлов). Репозиторий — из [merge_repos] сейчас, шлюз — на
    тот же head, PR сливается с base (merge_conflict), список файлов PR полон (окно показывает задетое ядро). after —
    сверка после пальца (finger): «GitHub ещё считает» (UNKNOWN) там не wait, а не помеха — слияние прежнего PR пачки
    или другое слияние за время окна сдвигает base, и mergeable пересчитывается лениво (Б1 argus #381); конфликтный PR
    `gh pr merge --match-head-commit` всё равно не сольёт. CONFLICTING и DIRTY — fail и после пальца."""
    if req["repo"] not in allowed_repos():
        return "fail", f"{req['repo']} больше не в [merge_repos] {MERGE_DIRECTION}", None, None
    view = pr_view(req["repo"], req["pr"])
    state, why = gate(req["repo"], req["pr"], req["sha"], view)
    # конфликт с base — до окна (metis-0819: 05.11 палец трижды тратился на PR, который gh pr merge не сливал)
    conflict = merge_conflict(view) if state != "fail" and isinstance(view, dict) else None
    if conflict and (conflict[0] == "fail" or state == "ok" and not after):
        return conflict[0], conflict[1], view, None
    if state != "ok":
        return state, why, view, None
    raw = []
    paths = pr_files(req["repo"], req["pr"], view, raw)
    if paths is None:
        return "wait", "список файлов PR не получен или неполон", view, None
    bad = version_problem(raw)
    if bad:
        return "fail", f"{bad} — номер поднимает workflow release после слияния (metis-0512)", view, None
    return "ok", why, view, paths


def finger(req, rc=0, phrase=None):
    """После пальца (или фразы phrase — find_phrase, metis-0959) — одна заявка: (слит ли, текст итога). Окно было
    открыто до двух минут, а у пачки перед этой заявкой ещё шли слияния прежних: отмена, новый «вернуть», новый коммит
    или правка [merge_repos] за это время — не сливать. Сверка шлюза (и фразы: та же, не использована), отметка
    фразы, строка согласия и снятие заявки — под замком merge-queue, как у request и cancel; слияние —
    `gh pr merge --match-head-commit` того SHA, что в заявке."""
    how, after = ("фразой", "после фразы") if phrase else ("по Touch ID", "после пальца")
    with P.lock("merge-queue"):
        if not same_req(req):
            return False, gone(req, rc)
        if phrase is not None:
            cur = find_phrase(req)
            if cur is None or cur["key"] != phrase["key"]:
                return False, "ждёт: фраза уже не в силе"
        state, why, _, _ = check_all(req, after=True)
        if state != "ok":
            os.remove(req_file(req["repo"], req["pr"]))
            bad = f"{after} условия изменились — {why}"
        else:
            bad = None
            if phrase is not None:
                mark_phrase(phrase)   # одна фраза — одно согласие: до строки согласия, сбой — ни строки, ни слияния
            approve(req)
            os.remove(req_file(req["repo"], req["pr"]))   # одно применение — до слияния, сбой gh её не вернёт
    if bad:
        log(req, "gate-after", why=bad)
        P.alert(f"слияние {req['repo']}#{req['pr']} ({req['sha'][:7]}) {how}: не слито, заявка снята — {bad}",
                "pantheon-merge")
        return False, f"снята: {bad}"
    if phrase is not None:
        log(req, "phrase", file=f"owner-log/{phrase['file']}", line=phrase["line"], at=phrase["at"],
            said=f"слей #{phrase['pr']} {phrase['hex']}")
    code, out = gh_merge(req)
    log(req, "merged" if code == 0 else "merge-failed", rc=code, how="phrase" if phrase else "touchid",
        why=None if code == 0 else f"{'фраза' if phrase else 'палец'} есть, gh pr merge упал ({code}): {out}")
    if code == 0:
        notify_merged(req, phrase)
    if code != 0:
        P.alert(f"слияние {req['repo']}#{req['pr']} ({req['sha'][:7]}) {'после фразы' if phrase else 'после Touch ID'} "
                f"не прошло: {out}. Согласие записано — шлюз guard пустит слияние этого SHA в течение суток",
                "pantheon-merge")
        return False, f"{'фраза' if phrase else 'палец'} есть, gh pr merge упал ({code})"
    return True, "слит фразой" if phrase else "слит"


def process(req, click):
    t = P.now()
    if t - req["created"] > REQUEST_TTL:
        return drop(req, "expired", f"{REQUEST_TTL // 3600} ч без ответа", warn=True)
    # фраза владельца «слей #N <hex>» (metis-0959) — согласие без окна: ни повтора окна, ни щелчка, ни Mac рядом
    phrase = find_phrase(req)
    if phrase is None and not click and req.get("wait_until", 0) > t:
        return "ждёт: окно закрыто без ответа, повтор позже"
    if phrase is None and not click and req.get("notified"):
        return "ждёт щелчка по уведомлению"
    state, why, view, paths = check_all(req)  # заново, на тот же head (Решено, бриф 0285)
    if state == "fail":
        return drop(req, "gate", why, warn=True, how="по фразе" if phrase else "по Touch ID")
    if mark_wait(req, state, why):
        return f"ждёт: {why}"
    if phrase is not None:
        return finger(req, None, phrase)[1]
    if not click and P.idle_sec() > PRESENT_SEC:
        return "ждёт: вас нет у Mac"
    text = window_text(req, view, why, paths)
    rc, info = ask_full(text)
    if rc is None:
        P.alert_once("merge-helper", "1", "слияние по Touch ID: помощник окна не собран (swiftc) — заявки ждут; "
                     "собрать: pantheon install", "pantheon-merge")
        return "ждёт: помощника окна нет"
    log(req, "window", rc=rc, click=click, **info)
    if rc == 0:
        return finger(req, rc)[1]
    if rc == 1:
        return drop(req, "refused", "вы отказали")
    if rc == 3:
        req["wait_until"] = int(t + RETRY_SEC)
        if not keep(req):
            return gone(req, rc)
        return "окно закрыто без ответа — повтор позже"
    if rc == 2 and not click:
        with P.lock("merge-queue"):
            still = same_req(req)
        if not still:   # сняли, пока помощник пробовал окно, — и уведомления нет
            return gone(req, rc)
        if fallback_notify(req, text):
            req["notified"] = int(t)
            if not keep(req):
                return gone(req, rc)
            log(req, "notified")
            return "окно из прохода не показать — уведомление, ждёт щелчка"
        return drop(req, "no-window", "окно Touch ID не показать и уведомление не ушло", warn=True)
    return drop(req, "no-window", f"окно Touch ID не показано (код {rc})", warn=True)


def drop_batch(reqs, event, why, warn=False):
    """Снять все заявки пачки (каждую — только если в очереди та же, drop) и одной тревогой, если warn."""
    out = [(r, drop(r, event, why)) for r in reqs]
    if warn:
        P.alert(f"слияние пачки {reqs[0]['repo']} {nums(reqs)} по Touch ID: заявки сняты — {why}", "pantheon-merge")
    return out


def process_batch(reqs, click):
    """Пачка заявок одной постановки (metis-0668) → [(заявка, итог)] по каждой. Как process, но окно одно на всю
    пачку: в нём ядро всех PR и список PR с SHA и вердиктами шлюза. До окна: пачка в очереди неполна (одну сняли или заменили), шлюз
    не пройден хоть у одного — сняты все с тревогой; ждёт хоть один — ждут все. После пальца — по очереди, каждый
    через finger (шлюз заново, строка согласия, gh pr merge --match-head-commit своего SHA); не слит один — следующие
    не трогаются: ни согласия, ни слияния, заявки сняты (палец был на всю пачку — нужна новая заявка)."""
    t, batch = P.now(), reqs[0]["batch"]
    if len(reqs) != len(batch):
        have = {r["pr"] for r in reqs}
        miss = ", ".join("#%d" % n for n in batch if n not in have)
        return drop_batch(reqs, "batch-broken", f"пачка неполна: заявку на {miss} сняли или заменили", warn=True)
    if t - reqs[0]["created"] > REQUEST_TTL:
        return drop_batch(reqs, "expired", f"{REQUEST_TTL // 3600} ч без ответа", warn=True)
    if not click and max(r.get("wait_until", 0) for r in reqs) > t:
        return [(r, "ждёт: окно закрыто без ответа, повтор позже") for r in reqs]
    if not click and any(r.get("notified") for r in reqs):
        return [(r, "ждёт щелчка по уведомлению") for r in reqs]
    views, whys, paths, waits = [], [], [], []
    for r in reqs:
        state, why, view, files = check_all(r)   # заново, на тот же head, у каждого PR пачки
        if state == "fail":
            return drop_batch(reqs, "gate", f"#{r['pr']}: {why}", warn=True)
        if mark_wait(r, state, why):
            waits.append(f"#{r['pr']}: {why}")
        views.append(view)
        whys.append(why)
        paths.append(files or [])
    if waits:
        return [(r, "ждёт: " + "; ".join(waits)) for r in reqs]
    if not click and P.idle_sec() > PRESENT_SEC:
        return [(r, "ждёт: вас нет у Mac") for r in reqs]
    text = batch_window_text(reqs, views, whys, paths)
    rc, info = ask_full(text)
    if rc is None:
        P.alert_once("merge-helper", "1", "слияние по Touch ID: помощник окна не собран (swiftc) — заявки ждут; "
                     "собрать: pantheon install", "pantheon-merge")
        return [(r, "ждёт: помощника окна нет") for r in reqs]
    for r in reqs:
        log(r, "window", rc=rc, click=click, batch=",".join(map(str, batch)), **info)
    if rc == 0:
        out, merged, untouched, stop = [], [], [], None
        for r in reqs:
            if stop:
                untouched.append(r)
                out.append((r, drop(r, "batch-stopped", f"не слит: пачка остановлена на {stop}")))
                continue
            ok, res = finger(r, rc)
            out.append((r, res))
            if ok:
                merged.append(r)
            else:
                stop = f"#{r['pr']} ({res})"
        if untouched:
            P.alert(f"слияние пачки {reqs[0]['repo']} по Touch ID остановлено на {stop}. Слиты: "
                    f"{nums(merged) or 'ни один'}; не тронуты — согласия и слияния нет, заявки сняты, нужна новая: "
                    f"{nums(untouched)}", "pantheon-merge")
        return out
    if rc == 1:
        return drop_batch(reqs, "refused", "вы отказали")
    if rc == 3:
        out = []
        for r in reqs:
            r["wait_until"] = int(t + RETRY_SEC)
            out.append((r, "окно закрыто без ответа — повтор позже" if keep(r) else gone(r, rc)))
        return out
    if rc == 2 and not click:
        with P.lock("merge-queue"):
            still = all(same_req(r) for r in reqs)
        if not still:   # сняли или заменили, пока помощник пробовал окно, — и уведомления нет
            return [(r, gone(r, rc)) for r in reqs]
        if fallback_notify(reqs[0], text):
            out = []
            for r in reqs:
                r["notified"] = int(t)
                if keep(r):
                    log(r, "notified")
                    out.append((r, "окно из прохода не показать — уведомление, ждёт щелчка"))
                else:
                    out.append((r, gone(r, rc)))
            return out
        return drop_batch(reqs, "no-window", "окно Touch ID не показать и уведомление не ушло", warn=True)
    return drop_batch(reqs, "no-window", f"окно Touch ID не показано (код {rc})", warn=True)


def cmd_run(click=False):
    # переменная есть, пусть и пустая, — окно Claude Code: сливает только проход или щелчок владельца
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        err("pantheon merge run: только плановый проход или щелчок по уведомлению, не из окна Claude Code")
        return 2
    why = clean_env()
    if why:
        err(f"pantheon merge run: {why} — окружение прохода подменено (launchctl setenv?), прохода нет")
        return 2
    r = root()
    with P.lock("merge-run", block=False) as got:
        if not got:
            print("pantheon merge run: идёт другой проход")
            return 0
        rc, seen = 0, set()
        for f in sorted(os.listdir(r)) if _real_dir(r) else []:
            p = os.path.join(r, f)
            # заявку пачки уже разобрали с её первой — её файла может и не быть (слита, снята): не «битая» (argus-263a)
            if not FILE_RE.fullmatch(f) or f in seen:
                continue
            with P.lock("merge-queue"):
                req = read_req(p)
                if req is None:
                    with contextlib.suppress(OSError):
                        os.remove(p)
                # пачка (metis-0668) — вся сразу, по порядку слияния, когда встретилась первая её заявка
                group = batch_members(req) if req is not None and req.get("batch") else [req]
            if req is None:
                print(f"{f}: битая заявка — удалена")
                continue
            seen.update(os.path.basename(req_file(g["repo"], g["pr"])) for g in group)
            try:
                if req.get("batch"):
                    for g, res in process_batch(group, click):
                        print(f"{g['repo']}#{g['pr']}: {res}")
                else:
                    print(f"{req['repo']}#{req['pr']}: {process(req, click)}")
            except Exception as e:  # одна заявка не останавливает другие; сбойная снимается — окно не повторяется
                rc = 1
                for g in group:
                    with contextlib.suppress(Exception):
                        drop(g, "error", f"сбой прохода ({type(e).__name__}: {e})", warn=True)
                    print(f"{g['repo']}#{g['pr']}: сбой ({type(e).__name__}) — заявка снята")
        try:   # управляемые настройки guard (metis-0710) — тем же проходом, под тем же замком
            print(f"управляемые настройки guard: {managed_pass()}")
        except Exception as e:  # сбой не роняет проход; тревога — с причиной, повтор — следующим проходом
            rc = 1
            with contextlib.suppress(Exception):
                P.alert(f"управляемые настройки guard: сбой прохода ({type(e).__name__}: {e})", "pantheon-managed")
            print(f"управляемые настройки guard: сбой ({type(e).__name__})")
        return rc


def pending():
    """Есть ли заявки — для тика: процесс прохода запускается, только когда есть что делать."""
    r = root()
    try:
        return _real_dir(r) and any(FILE_RE.fullmatch(f) for f in os.listdir(r))
    except OSError:
        return False


def cmd_status():
    r, rows, t = root(), [], P.now()
    if _real_dir(r):
        for f in sorted(os.listdir(r)):
            req = read_req(os.path.join(r, f)) if FILE_RE.fullmatch(f) else None
            if req:
                marks = (" уведомление" if req.get("notified") else "") + (" повтор позже" if req.get("wait_until", 0) > t else "")
                if req.get("batch"):
                    marks += " пачка " + ",".join("#%d" % n for n in req["batch"])
                if isinstance(req.get("waiting"), str):   # Д2 argus #381: почему ждёт — mark_wait прохода
                    marks += f" ждёт: {req['waiting']}"
                rows.append(f"{req['repo']}#{req['pr']}\t{req['sha'][:12]}\t{int((t - req['created']) // 60)} мин\t"
                            f"{req.get('by', '?')}{marks}")
    print("\n".join(rows) if rows else "заявок нет")
    done = recent_done(t)
    if done:   # metis-0819: «заявок нет» после снятия или провала gh pr merge — не «окна не было»
        print(f"за {DONE_SHOW // 3600} ч сняты и слиты:\n" + "\n".join(done))
    return 0


def recent_done(t):
    """Строки `pantheon merge status` о заявках, ушедших из очереди за DONE_SHOW (metis-0819): время, repo#N, SHA,
    событие и причина из logs/merge.jsonl. Журнал не читается — пусто; байты не в UTF-8 (порча файла) — заменой, а не
    трассировкой status (Д1 argus A #381)."""
    out = []
    try:
        with open(P.path("logs", "merge.jsonl"), encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            rec = json.loads(ln)
            at = datetime.strptime(rec["time"], "%Y-%m-%d %H:%M").timestamp()
        except (ValueError, TypeError, KeyError):
            continue
        if isinstance(rec, dict) and rec.get("event") in DONE_EVENTS and 0 <= t - at <= DONE_SHOW:
            why = rec.get("why") if isinstance(rec.get("why"), str) else ""
            out.append(f"{rec['time']}\t{rec.get('repo')}#{rec.get('pr')}\t{str(rec.get('sha') or '?')[:12]}\t"
                       f"{rec['event']}" + (f": {why}" if why else ""))
    return out[-DONE_MAX:]


def cmd_cancel(args):
    target = parse_target(args)
    if not target:
        err(USAGE)
        return 2
    repo, pr = target
    p = req_file(repo, pr)
    with P.lock("merge-queue"):
        if not os.path.lexists(p):
            print(f"заявки {repo}#{pr} нет")
            return 0
        req = read_req(p) or {"repo": repo, "pr": pr, "sha": None}
        # пачка (metis-0668) без одной заявки не сливается: снимаются и остальные заявки той же постановки
        rest = [m for m in batch_members(req) if m["pr"] != pr] if req.get("batch") else []
        os.remove(p)
        for m in rest:
            os.remove(req_file(m["repo"], m["pr"]))
    for m in [req] + rest:
        log(m, "cancelled")
    print(f"заявка {repo}#{pr} снята" + (f", с ней — вся пачка: {nums(rest)}" if rest else ""))
    return 0


def main(rest):
    sub = rest[0] if rest else ""
    if sub == "request":
        return cmd_request(rest[1:])
    if sub == "cancel":
        return cmd_cancel(rest[1:])
    if sub == "run" and rest[1:] in ([], ["--click"]):
        return cmd_run(click=rest[1:] == ["--click"])
    if sub == "status" and len(rest) == 1:
        return cmd_status()
    if sub == "build" and len(rest) == 1:   # помощник окна — pantheon install зовёт сам
        out = build_helper(quiet=False)
        print(out or "не собран")
        return 0 if out else 1
    err(USAGE)
    return 2
