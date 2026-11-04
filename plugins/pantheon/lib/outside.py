"""Проверки вне окна роли ([sb-simplify] п. 7, «да» владельца 27.10): тесты и dev-сервер без модели и без СБ.

Окну роли песочница Claude Code не даёт местных портов (allowLocalBinding открыл бы весь localhost — местный прокси и
порты браузеров), поэтому dev-сервер и тесты, которым нужен порт, роль сама не запустит. Она пишет одну команду, а
плановый проход (launchd, вне песочницы окон) запускает проверку проекта под своим профилем sandbox-exec и отдаёт
результат. Образец — `pantheon merge request|run`: заявка роли → проход тика отдельным процессом.

  pantheon outside test [--script ИМЯ] [--wait С]    проверка проекта на HEAD этой папки (дерево чистое; неотслеживаемый .claude/worktrees/ не в счёт): команда —
                                         первая строка .pantheon-verify (из origin/HEAD, иначе из HEAD), иначе скрипт
                                         test/check package.json, иначе pytest; --script — скрипт package.json
                                         Тот же HEAD и та же папка, а прежняя заявка test (без --script) ещё в очереди или идёт —
                                         новой не будет: команда печатает ID прежней и с --wait ждёт её итог (metis-0706)
  pantheon outside test --sha SHA [--script ИМЯ] [--wait С]
                                         та же проверка на коммите SHA (7–40 знаков, есть в клоне) в своей копии, а не
                                         в этой папке: ветку PR не переключить в worktree окна, если .claude/ проекта
                                         отличается (запись туда закрыта, metis-0779); запись tests — на полный SHA
  pantheon outside serve [--sha SHA] [--app ИМЯ] [--script ИМЯ] [--minutes N] [--wait С]
                                         dev-сервер на коммите SHA (по умолчанию HEAD этой папки) из своей копии →
                                         адрес http://127.0.0.1:<порт 4300–4399>; гаснет сам через N минут (30, ≤120)
  pantheon outside status [ID]           итог заявки: состояние, код, адрес, хвост журнала (без ID — последние)
  pantheon outside stop ID [--wait С]    погасить сервер раньше срока (из любого окна) и дождаться итога (20 с)
                                         тест, ещё лежащий заявкой в очереди своего окна, снимается: итог stopped; идущий тест
                                         не гасится — идёт до конца
  pantheon outside run [--serve]         проход по заявкам — только плановый проход (из окна Claude Code — отказ):
                                         без флага — тесты, --serve — серверы и сторож
--wait С — ждать итога до С секунд (не больше 590: у Bash окна предел 10 минут) и напечатать его; код выхода — код
команды тестов, у сервера 0 — адрес готов, отказ — 1, отказ «занято» (два сервера, давление памяти) — 75, снятый дубль — 75 (итог у первой заявки), итога не
дождался — 75. Без --wait — номер заявки, итог — `pantheon outside status ID`.

Сервер (metis-0614, решения владельца 01.11). Одна заявка — один сервер — своя папка — свой порт:
  - папка — своя копия на коммите заявки: `git worktree add --detach` в ~/Library/Caches/pantheon-outside/work/<ID>
    (не STATE: профиль закрывает запись в STATE, а серверу нужны node_modules и .next). Коммит — --sha (7–40 знаков,
    должен быть в клоне: talos даёт head PR, не входя в чужую worktree) или HEAD папки при заявке; незакоммиченные
    правки в копию не попадают. Зависимости — `<pm> install --frozen-lockfile` (npm ci) под профилем, без heavy;
  - монорепо (workspaces в package.json или pnpm-workspace.yaml): PORT получает одно приложение — --app ИМЯ (имя
    пакета или папки), его скрипт идёт в папке приложения; одно приложение со скриптом — берётся само; `--app .` —
    корневой скрипт; иначе отказ со списком. turbo.json проекта не правится;
  - порт — из ряда 4300–4399, не 3000, 3100–3199 (разработчики) и 3200–3299 (показ владельцу, прежний ряд);
  - не больше MAX_SERVERS (2) серверов сразу; давление памяти критичное — отказ любому, предупреждение — второму;
    отказ сразу, с причиной и кодом 75, без очереди heavy. У каждого сервера лимит памяти SERVER_MEM_MB (4 ГБ,
    решение владельца 01.11): RSS группы сервера и её потомков в своих группах больше — сторож гасит его с причиной
    «память»;
  - ключи — только dev-ключи из STATE/outside/env/<owner>__<repo>.env и <owner>__<repo>__<app>.env (KEY=VALUE),
    проход читает их сам и передаёт окружением процесса; в итоге — только имена. Профиль закрывает чтение .env* в
    дереве и самой папки STATE/outside/env (серверы и тесты не читают ключи чужих проектов). <owner>__<repo> — из
    origin клона реестра, а не из конфига папки роли. Остаток: окружение процесса читает процесс того же пользователя
    (KERN_PROCARGS2); deny process-info* этого не закрывает (проба 01.11) — потому только dev-ключи;
  - опора — клон реестра (metis-0614, проверка безопасности): .git-файл папки заявки принимается, только если ведёт в
    <клон>/.git/worktrees/<имя> клона из папок окна (trusted_clone, без запуска git); конфиг клона с include*,
    filter.*, extensions.worktreeConfig, командой в core.fsmonitor или ключом-командой (*.command, *.textconv,
    *.driver, *.helper, *.program, pager.*, alias.*) — отказ (unsafe_config); git прохода — с GIT_SAFE (без
    fsmonitor, хуков, сети, подмодулей; status — --ignore-submodules=all: конфиг подмодуля окну открыт), копия —
    git --git-dir=<клон>/.git без ~/.gitconfig. Клон,
    common и gitdir проверяются один раз (resolve_dir; commondir у common, ссылки — отказ; подтверждает сам git), дальше
    папка — Repo, и git по ней идёт через --git-dir/--work-tree, а не через .git-файл. Остаток: commondir в
    <клон>/.git/worktrees/<имя>/ роль может переписать между проверкой и git теста — намеренный обход, граница — песочница;
  - тест на коммите (test --sha, metis-0779, run_test_at) — такая же копия <work>/test-<ID>: полное дерево, вместе с
    .claude/ проекта; зависимости — `<pm> install` под профилем с heavy, остатки установки гаснут (reap), дальше run_test
    в копии: HEAD не SHA заявки или дерево не чистое при любой проверке — ни прогона, ни записи; запись и перенос по
    дереву (tree_record) — только на SHA заявки. Копия снимается после
    прогона (reap, git worktree remove), брошенная (проход упал) — следующим проходом тестов под его замком. Запись
    tests — на полный SHA, cwd — копия; бывший head открытого PR (stale_head) — отказ, как у test без --sha. Заявка
    несёт pin: true; дубли (drop_dupes) её не снимают;
  - состояния: queued (заявка записана) → preparing (копия и зависимости) → starting (ждём порт) → serving →
    stopping → stopped; failed — с причиной, и при любом сбое прохода посреди заявки (копия снята, а не preparing
    до суток); копия без сервера старше WORK_ORPHAN_AGE (проход упал, Mac перезагрузился) снимается в конце круга;
  - «стоп» — файл <ID>.stop в папке заявок вызвавшего окна; проход ищет его во всех папках заявок, а не только в
    папке сервера (стоп из окна координатора доходит). Нет такой заявки — `stop` так и говорит, код 1.

Куда пишет заявка. В окне роли (есть PANTHEON_TMP — папка tmp кэша окна ~/Library/Caches/pantheon-sandbox/<окно>) —
в соседнюю папку outside/ кэша: туда окно пишет само, а итог проход кладёт туда же, окно его читает. Вне окна — в
STATE/outside/queue. Имя окна проход берёт из места папки, а не из текста заявки: окну направления можно только его
папки из реестра (domains.json ← ~/ai/pantheon/directions.toml), очереди STATE — любые папки реестра; кэш окна не
направления (мастерская, задачи) — отказ. Папка заявки — корень репозитория git внутри этих папок, с remote.

Два прохода, оба запускает тик, когда у них есть дело; у каждого свой замок — сервер не ждёт тестов (metis-0614):
  `outside run --serve` (замок outside-serve) — серверы и сторож. Живёт, пока есть серверы или заявки serve (не дольше
  RESIDENT_MAX, потом тик зовёт заново), и каждые SWEEP_EVERY (2 с):
  1. Сторож: срок вышел (аренда — until), есть «стоп» из любой папки заявок, процесс умер или дерево сервера больше
     лимита памяти — состояние stopping,
     группа процессов гаснет (SIGTERM, через 5 с SIGKILL) вместе с потомками, ушедшими в свою группу (turbo ставит её
     каждой задаче), и с любым своим процессом, у которого текущая папка — копия заявки (сирота next dev, ушедший к
     launchd до гашения); итог stopped, копия снимается. Порт после этого ещё отвечает — пометка в итоге. Номер
     процесса сервера занял чужой (время старта по ps не то) — его не гасим, только своих по папке.
  2. Заявки serve — по времени: «стоп» до запуска — stopped без запуска; заявка старше REQ_TTL (15 мин) — failed.
     Во время копии, установки и ожидания порта сторож продолжает смотреть серверы, «стоп» своей заявки прерывает.
  3. «Стоп» без живого сервера и заявки старше минуты — убирается.
  `outside run` (замок outside-run) — тесты:
  -1. Сторож (watchdog, до замка, metis-0723; тик будит и его): running дольше WATCH_RUNNING (TEST_TIMEOUT + 30 мин)
     при живом заходе — заход (SIGKILL) и его группы процессов гаснут, итог failed «сторож: дольше N мин — снято»,
     тревога; держателя замка не определить — только тревога. queued с лежащей .req.json дольше WATCH_QUEUED (4 ч) —
     одна тревога на заявку (метка runs/<ID>.alerted), без снятия. outside status показывает итог.
  0. На старте итоги test: queued без .req.json старше 5 мин — failed «заявка потеряна»; running, записанный самим
     заходом в STATE/outside/runs, — failed «заход прерван» (захода под замком больше нет; итог — минимальный объект,
     подложенное окном не копируется; metis-0716). Порядок заявок — по времени из id, по кругу между окнами.
  1. Заявки test — по времени, по одной (metis-0716): снимается с диска только запускаемая, очередь перечитывается
     после каждого дела — убитый заход не теряет остальные; не снявшаяся заявка не запускается. Одна заявка — один
     запуск; битые и подложенные — отказ. Кругов не больше MAX_ROUNDS.
     Перед стартом (before_test, metis-0726): HEAD папки — бывший head ещё открытого PR по кэшу autoclose-prs.json
     (old_heads, его пишет `autoclose fetch`), а у PR сейчас другой head — failed «head устарел, подай на текущий» без
     прогона (у --script — прогон; нет кэша, он старше часа — прогон как раньше); ждущие заявки на ту же проверку (тот
     же --script, та же папка или папка того же репозитория на том же чистом HEAD) — failed «дубль <id>».
  2. Автопрогонов нет (решение владельца 03.11, metis-0733): тесты идут только по заявке роли, одна на итоговый head.
     Дежурный лишь тревожит: «принять» argus старше часа (ALERT_AFTER) и не старше суток (AUTO_TTL) на (repo, SHA), где SHA —
     head открытого PR по кэшу autoclose-prs.json (нет кэша, он старше часа или gh не ответил по репозиторию — тревоги нет),
     а записи tests на этот SHA в журнале шлюза (STATE/merge-gate/records.jsonl) нет → P.alert с repo@sha12 и номером PR.
     Одна тревога на (repo, SHA): метка в STATE/outside/auto.json alerted. Тик будится, пока есть неотправленная тревога.
  3. Уборка: итоги <ID>.result.json и брошенные <ID>.stop в папках заявок (кэш окна, STATE/outside/queue) старше
     суток (RESULT_TTL, по mtime) удаляются; файлы живого сервера — нет. Журналы в STATE/outside/runs не трогаются.
Запуск: тесты — heavy sandbox-exec -f STATE/outside/profile.sb <команда> в папке репозитория, сервер — то же без heavy
(лимит серверов держит проход) в папке копии; окружение с нуля (HOME, PATH с node из nvm, TMPDIR — своя временная
папка, у тестов CI=1, у сервера PORT и dev-ключи проекта). Тесты — не дольше TEST_TIMEOUT. Сторож тишины (metis-0770): лог прогона не
растёт IDLE_TIMEOUT (900 с) и CPU дерева процессов (user+sys: на macOS по libproc, без setuid /bin/ps, который под
sandbox-exec не запускается; на Linux по ps) за окно вырос меньше IDLE_CPU (1 % ядра) → группа
гасится SIGKILL, итог failed «тишина N мин, последний вывод: <строка>» (меньше минуты — «N с»), в журнал — запись test-silent; считающий без
вывода прогон не гасится. CPU не узнать (ни libproc, ни ps) — не гасим, одна запись test-silent-nocpu за прогон. Профиль:
всё разрешено, кроме чтения ключей (.env*, кроме шаблонов .env.example, .env.sample, .env.template — они открыты
на чтение, на запись нет; STATE/outside/env; secrets/, ~/.ssh, ~/.config/cdp-daemon, ~/.config/gh, ~/.gnupg, ~/.aws,
~/.netrc, ~/.git-credentials, ~/.npmrc, ~/Library/Keychains и служба Связки ключей com.apple.SecurityServer), записи в
состояние и ядро (STATE, ~/ai/pantheon, ~/.claude, ~/.local/bin, ~/.local/share/pantheon, ~/Library/LaunchAgents,
профили оболочки, ~/.gitconfig, ~/.nvm, кэши окон ~/Library/Caches/pantheon-sandbox, .git/config и
.git/hooks папок реестра) и сети к портам браузеров (9222, 9333–9339) и
местного прокси (6152, 6153) на любом адресе.

Запись tests для шлюза слияния — только у проверки проекта (без --script; у serve её нет никогда): тесты кончились
кодом 0, HEAD и дерево до и после те же, команда не пустая (true, echo… — отказ; у скрипта package.json — по его
телу). Команда видна в записи (cmd), argus её сверяет: у скрипта package.json — с телом («pnpm run test  # package.json:
vitest run»), строка .pantheon-verify из файла ветки (в клоне нет origin/HEAD, origin/main, origin/master с этим
файлом) — с пометкой «# .pantheon-verify ветки (HEAD)»: эти файлы PR меняет сам, остаток — README guard. Проход дописывает в STATE/merge-gate/records.jsonl строку того же формата, что пишет хук guard
(kind tests, repo — remote папки, pr null, sha), by.agent_type = "pantheon-outside". Пишет только проход: роль в
своём окне STATE не пишет, а команда под профилем — тоже (deny file-write STATE). Хук guard на `pantheon review test`
по-прежнему пишет свою запись; шлюз принимает любую из двух.
Запись по дереву (metis-0732, tree_record): запись прохода несёт ещё tree (дерево коммита) и env (настоящий путь python
команды и версия macOS). Зелёный полный набор (команда — FULL_TESTS репозитория) на коммите с тем же деревом, тем же
env и той же командой засчитывается новому HEAD без прогона — запись той же формы с отметкой by_tree (коммит, чей
прогон перенесён): rebase без конфликтов, правка сообщения. На тот же коммит запись уже есть — итог без прогона.
Красный прогон записи не даёт, переносить нечего; записи хука guard (без tree) не переносятся.
Дозапуск после красного полного набора (metis-0735, rerun_plan; «да» владельца 03.11). Каждый прогон полного набора
(команда — FULL_TESTS, дерево чистое, HEAD тот же, без таймаута) проход пишет строкой в STATE/outside/full.jsonl:
  {"v": 1, "time", "rid": id заявки, "repo": [owner/repo], "sha", "tree", "branch": ветка папки или null, "dir",
   "cmd", "env", "code", "failed": [«плагин/test_x.py»] или null — итог run-tests не разобран (run_failed),
   у дозапуска ещё "rerun_of", "files", "map"}.
Красный прогон в журнал шлюза не идёт: там любая запись kind tests — «тесты прошли», поэтому список упавших — здесь.
Следующая заявка полного набора на той же ветке гонит не весь набор, а `<команда> --only <файлы>`: упавшие в последнем
полном прогоне ветки и затронутые диффом его коммит → HEAD (`git diff` двух коммитов: предок или после rebase — как
есть) по карте affected-map.json рядом с раннером; выбор — select установленного run-tests.py, как у --affected. Опора
— ветка папки, а не кэш autoclose (old_heads): кэш пишет fetch по расписанию, и только что закоммиченного HEAD в нём
ещё нет; а связь с PR для верности не нужна — дифф считается от коммита опоры, каким бы он ни был. Опора — только
прогон всего набора (без rerun_of): дозапуск гонял часть файлов, остальные на его коммите не шли, и цепочка
накапливала бы ошибки карты от звена к звену; от настоящего прогона дифф покрывает всё после него за один шаг.
Весь набор вместо дозапуска (причина — full_why итога), если: HEAD без ветки; полного прогона ветки нет, он зелёный,
у него другая команда или env, нет списка упавших (старая запись, прерванный прогон), его коммита нет в клоне; дифф
задевает файл вне карты или общий (FULL раннера), раннер, карту, bin/heavy, tests/_*.py любого плагина или
.pantheon-verify; карта не читается или устарела (stale хоть один файл); упавших больше половины; выбор — весь набор;
run-tests.py в HEAD не знает --only; опоре больше RERUN_MAX_AGE (24 ч) или время не разобрать; сбой расчёта. Дозапуск зелёный и строки ok его вывода — ровно его файлы — запись
tests на HEAD тем же путём append_tests с cmd = FULL_TESTS и полями rerun_of (id заявки опоры), files (прогнанные
метки), map (sha256 affected-map.json HEAD). Шлюз guard её засчитывает как полный набор (merge_gate.py не менялся).
Остаток: test_hash раннера читает файл тестов целиком, без предела размера (и по ссылке) — файл-гигант в плагине растит
память прохода; ссылки и размеры файлов дозапуск не проверяет.
Журналы: STATE/outside/runs/<ID>.log (вывод команды) и <ID>.json (итог), STATE/logs/outside.jsonl (в том числе
test-silent — прогон погашен сторожем тишины, test-silent-nocpu — лог молчит, а CPU дерева не узнать).
"""
import contextlib
import ctypes
import errno
import glob
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()

ID_RE = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
SCRIPT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,59}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
SHORT_SHA_RE = re.compile(r"[0-9a-f]{7,40}")
# --app: имя пакета (@scope/имя) или папки приложения монорепо; «.» — корневой скрипт
APP_RE = re.compile(r"\.|@?[A-Za-z0-9][A-Za-z0-9._-]{0,80}(/[A-Za-z0-9][A-Za-z0-9._-]{0,80})?")
KINDS = ("test", "serve")
FINAL = ("done", "failed", "serving", "stopped")
DENY_PORTS = (9222,) + tuple(range(9333, 9340)) + (6152, 6153)   # браузеры с входами и местный прокси
# порты владельца: 3000 (next по умолчанию), 3100–3199 (разработчики в своих worktree), 3200–3299 (показ владельцу)
OWNER_PORTS = frozenset((3000,) + tuple(range(3100, 3300)))
SERVER_PORTS = range(4300, 4400)    # ряд серверов прохода (metis-0614): не пересекается с портами владельца
MAX_SERVERS = 2                     # решение владельца 01.11: не больше двух серверов сразу
SERVER_MEM_MB = 4096                # и у каждого лимит 4 ГБ (владелец 01.11): RSS дерева сервера больше — сторож гасит
SERVE_MIN, SERVE_MAX = 30, 120      # срок сервера, минуты
TEST_TIMEOUT = 7200                 # с
IDLE_TIMEOUT = 900                  # с: лог прогона не растёт, а дерево процессов почти не тратит CPU — завис, гасим (metis-0770)
IDLE_CPU = 0.01                     # доля ядра: прирост user+sys дерева за окно меньше этого — «почти не тратит»
INSTALL_TIMEOUT = 900               # с: установка зависимостей копии сервера
READY_SEC = 90                      # сервер должен открыть порт за это время
KILL_WAIT = 5
SWEEP_EVERY = 2                     # с: так часто сторож смотрит «стоп» и срок серверов (metis-0606, 0614)
REQ_TTL = 15 * 60                   # с: заявка serve, пролежавшая дольше, не запускается
STOP_ORPHAN_AGE = 60                # с: «стоп» без сервера и заявки старше — убирается
WORK_ORPHAN_AGE = 600               # с: копия серверов без записи в servers.json старше — брошена, снимается
PREPARE_SPAWN_TRIES = 3             # запусков установки при временном отказе fork/exec
SPAWN_RETRY_ERRNO = {errno.EAGAIN, errno.ETXTBSY, errno.ENOMEM}
STOP_WAIT = 20                      # с: `outside stop` ждёт итог по умолчанию
RESIDENT_MAX = 3600                 # с: проход серверов живёт не дольше, потом его зовёт тик (новая версия кода)
AUTO_TTL = 24 * 3600                # «принять» старше суток дежурному уже не напоминается
ALERT_AFTER = 3600                  # с: «принять» без записи tests дольше этого — тревога дежурному (03.11)
RERUN_MAX_AGE = 24 * 3600          # с: опора дозапуска (полный прогон) старше суток — весь набор (metis-0735)
RESULT_TTL = 24 * 3600              # итоги <ID>.result.json и брошенные <ID>.stop в папках заявок — сутки
WAIT_MAX = 590
TAIL_LINES, TAIL_CHARS = 40, 4000
REQ_MAX = 64 * 1024
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
HEAVY = "default"                   # путь heavy; "default" — PLUGIN/bin/heavy; None — без heavy (тесты)
# пустые команды тестов (как EMPTY_TEST_PROGRAMS шлюза guard): записи tests не дают
EMPTY = {"true", ":", "echo", "printf", "exit", "test", "[", "sleep", "yes", "false"}
SAFE_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
# имена из файла dev-ключей, которые окружение сервера не отдаёт: их ставит проход или они меняют загрузку кода
RESERVED_ENV = {"HOME", "PATH", "TMPDIR", "PORT", "CI", "LANG", "SHELL", "USER", "LOGNAME", "PWD"}
RESERVED_ENV_PREFIX = ("PANTHEON_", "DYLD_", "LD_")
ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
USAGE = ("pantheon outside test [--sha SHA] [--script ИМЯ] [--wait С] | "
         "serve [--sha SHA] [--app ИМЯ] [--script ИМЯ] [--minutes N] [--wait С] | "
         "status [ID] | stop ID [--wait С] | run [--serve]")


def set_core(mod):
    global P
    P = mod


def err(text):
    print(text, file=sys.stderr)


# --- пути ---------------------------------------------------------------------------------------------------------

def root(*parts):
    return os.path.join(P.STATE, "outside", *parts)


def caches():
    return os.path.join(P.HOME, "Library", "Caches", "pantheon-sandbox")


def work_root():
    """Копии серверов (metis-0614): своя папка на заявку, вне STATE: профиль запрещает запись в STATE, а серверу нужна запись в свою папку."""
    return os.path.join(os.path.realpath(P.HOME), "Library", "Caches", "pantheon-outside", "work")


def env_dir():
    """Dev-ключи серверов по проектам (решение владельца 01.11): читает только проход, профиль их закрывает."""
    return root("env")


def heavy_bin():
    return os.path.join(P.PLUGIN, "bin", "heavy") if HEAVY == "default" else HEAVY


def pass_env():
    """Окружение прохода, который запускает тик: с нуля, как у merge run (metis-0303) — HOME, PATH тика (git, node),
    интерпретатор, своё STATE; без launchd-окружения и ключей."""
    env = {"HOME": P.HOME, "PATH": P.run_env()["PATH"], "PANTHEON_PYTHON": sys.executable}
    for k in ("PANTHEON_STATE", "PANTHEON_HOME", "AI_HOME", "PANTHEON_NO_NOTIFY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def own_qdir():
    """Папка заявок этого вызова: в окне роли — outside/ рядом с PANTHEON_TMP (кэш окна), иначе STATE/outside/queue."""
    tmp = os.environ.get("PANTHEON_TMP")
    if tmp:
        return os.path.join(os.path.dirname(os.path.realpath(tmp)), "outside")
    return root("queue")


def queue_dirs():
    """[(папка заявок, окно)]: окно None — очередь STATE (ваши сессии), иначе имя окна по папке кэша."""
    out = [(root("queue"), None)]
    try:
        names = sorted(os.listdir(caches()))
    except OSError:
        names = []
    for name in names:
        d = os.path.join(caches(), name, "outside")
        if _is_dir(d):
            out.append((d, name))
    return out


def _is_dir(p):
    try:
        return stat.S_ISDIR(os.lstat(p).st_mode)
    except OSError:
        return False


def _open_dir(d, create=False):
    """Дескриптор настоящей папки d (не ссылки); None — нет или подложено."""
    if create and not os.path.lexists(d):
        os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return None
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        os.close(fd)
        return None
    return fd


def _read_in(dfd, name, limit=REQ_MAX):
    """Обычный файл name в папке dfd (без ссылок, одна жёсткая ссылка) → текст; иначе None."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
            return None
        return os.read(fd, limit + 1).decode("utf-8", "replace")
    finally:
        os.close(fd)


def _write_in(dfd, name, text):
    """Файл name в папке dfd: новый временный (O_EXCL, без ссылок) и rename — подложенная ссылка на месте имени
    заменяется, а не пишется насквозь."""
    tmp = f".{name}.{os.getpid()}.{secrets.token_hex(3)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)


def _unlink_in(dfd, name):
    with contextlib.suppress(OSError):
        os.unlink(name, dir_fd=dfd)


def _take_in(dfd, name):
    """Снять файл name; True — снят этим вызовом (другой проход его уже не возьмёт), False — его уже нет."""
    try:
        os.unlink(name, dir_fd=dfd)
    except OSError:
        return False
    return True


def log_event(**kw):
    with contextlib.suppress(OSError):
        os.makedirs(os.path.join(P.STATE, "logs"), exist_ok=True)
        with open(os.path.join(P.STATE, "logs", "outside.jsonl"), "a") as fh:
            fh.write(json.dumps({"time": P.stamp(), **kw}, ensure_ascii=False) + "\n")


# --- реестр и git -------------------------------------------------------------------------------------------------

def registry(window=None):
    """Папки реестра (настоящие пути): окно направления — только его, None — все. Окно не направление — []."""
    domains = P.read_json(P.path("domains.json"), {}).get("domains") or {}
    out = []
    for name, folders in domains.items():
        if window is not None and name != window:
            continue
        for f in folders if isinstance(folders, list) else []:
            if isinstance(f, str):
                r = os.path.realpath(os.path.expanduser(f))
                if os.path.isdir(r) and r not in out:
                    out.append(r)
    return out


def inside(p, roots):
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)


# git вне песочницы в папках, которые пишет роль: ни монитора файлов, ни хуков, ни сети, ни подмодулей (metis-0614).
# -c перекрывает значения из конфига репозитория; фильтры и include так не снять — их отсекает unsafe_config.
# --no-replace-objects (и GIT_NO_REPLACE_OBJECTS в окружении, как у шлюза) — refs/replace в клоне не подменяют содержимое
# копии при том же HEAD и чистом status (metis-0796, Д1); attributes и alternates клона на дерево копии не влияют
GIT_SAFE = ("--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "protocol.allow=never",
            "-c", "submodule.recurse=false")


class Repo(str):
    """Папка заявки после trusted_clone (resolve_dir): клон, его .git (common) и gitdir папки проверены один раз, git по
    ней идёт с --git-dir=<gitdir> --work-tree=<папка> — .git-файл, который пишет роль, больше не читается."""
    clone = common = gitdir = None


def checked(d, clone, common, gitdir):
    r = Repo(d)
    r.clone, r.common, r.gitdir = clone, common, gitdir
    return r


def git(d, *args, timeout=30):
    """Вывод git в папке d (без GIT_* окружения, с GIT_SAFE; Repo — через проверенный gitdir); None — сбой."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    loc = ["-C", d] + ([f"--git-dir={d.gitdir}", f"--work-tree={d}"] if isinstance(d, Repo) else [])
    try:
        r = subprocess.run(["git", *loc, *GIT_SAFE, *args], capture_output=True, text=True, timeout=timeout,
                           env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def remote_id(url):
    """Адрес remote → owner/repo в нижнем регистре, как _remote_id + _repo_tail шлюза guard."""
    u = (url or "").strip()
    m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::\d*)?/+(.+)$", u, re.I) or \
        re.match(r"^(?:[^@/:]+@)?([^/:]+):(?!/)(.+)$", u)
    if not m:
        return "/".join(u.lower().split("/")[-2:])
    path = re.sub(r"(?:\.git)?/*$", "", m.group(2).lower()).strip("/")
    return "/".join(path.split("/")[-2:])


def remotes(d):
    out = git(d, "remote", "-v")
    if out is None:
        return []
    return sorted({remote_id(ln.split()[1]) for ln in out.splitlines() if len(ln.split()) >= 2})


# Живые worktree субагентов Claude Code лежат в .claude/worktrees/ и для git неотслеживаемые; грязью их не считаем.
# Только строка `?? ` с этим путём от корня репозитория: `.claude/worktrees-x/` и `a/.claude/worktrees/` не подходят.
WORKTREES_UNTRACKED = "?? .claude/worktrees/"


def head_state(d):
    """(HEAD, дерево чистое) папки d; HEAD None — не git или нет коммитов."""
    h = (git(d, "rev-parse", "HEAD") or "").strip().lower()
    # без подмодулей: git status зашёл бы в каждый и прочёл его конфиг (<клон>/.git/modules/<имя>/config окну роли
    # открыт на запись) — filter.* оттуда исполнился бы вне песочницы (metis-0614)
    st = git(d, "status", "--porcelain", "--ignore-submodules=all")
    top = (git(d, "rev-parse", "--show-toplevel") or "").strip()
    clean = P.tree_clean(st, top, (WORKTREES_UNTRACKED,))  # + ссылка node_modules (metis-0721)
    return (h if SHA_RE.fullmatch(h) else None), clean


def toplevel(d):
    t = (git(d, "rev-parse", "--show-toplevel") or "").strip()
    return os.path.realpath(t) if t else None


# --- команда проверки ---------------------------------------------------------------------------------------------

def _show(d, rev, name):
    return git(d, "show", f"{rev}:{name}")


def base_rev(d):
    """Ветка по умолчанию клона (origin/HEAD, origin/main, origin/master) — откуда брать .pantheon-verify: PR не
    ослабит проверку своей же правкой. Нет — HEAD."""
    for ref in ("refs/remotes/origin/HEAD", "refs/remotes/origin/main", "refs/remotes/origin/master"):
        if git(d, "rev-parse", "--verify", "-q", ref) is not None:
            return ref
    return "HEAD"


def _pkg(d):
    try:
        with open(os.path.join(d, "package.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def package_manager(d, pkg):
    pm = str(pkg.get("packageManager") or "").split("@")[0]
    if pm in ("pnpm", "npm", "yarn", "bun"):
        return pm
    for lock, name in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun")):
        if os.path.exists(os.path.join(d, lock)):
            return name
    return "npm"


def command(d, kind, script=None):
    """→ (argv для запуска, строка для журнала) или (None, причина)."""
    if kind == "serve":
        return serve_command(d, script)[:2]
    pkg = _pkg(d)
    if script:
        name = script
        scripts = (pkg or {}).get("scripts") or {}
        if not isinstance(scripts, dict) or name not in scripts:
            return None, f"в package.json папки нет скрипта «{name}»"
        pm = package_manager(d, pkg)
        return [pm, "run", name], f"{pm} run {name}"
    base = base_rev(d)
    text, own = _show(d, base, ".pantheon-verify"), base == "HEAD"
    if not text and not own:
        text, own = _show(d, "HEAD", ".pantheon-verify"), True
    if text:
        # строка `dev:` — узкая проверка исполнителя для Stop-хука (metis-0653), здесь не команда проверки проекта
        line = next((x.strip() for x in text.splitlines()
                     if x.strip() and not x.lstrip().startswith("#") and not x.lstrip().startswith("dev:")), "")
        if line:
            words = line.split()
            while words and words[0] in ("heavy", "--server"):   # heavy проход ставит сам, снаружи профиля
                words = words[1:]
            line = line.split(None, len(line.split()) - len(words))[-1] if words else ""
            if not line:
                return None, ".pantheon-verify без команды"
            # строка из файла ветки (нет origin/HEAD, origin/main, origin/master или там файла нет) — видна в записи tests
            return ["/bin/sh", "-c", line], line + ("  # .pantheon-verify ветки (HEAD)" if own else "")
    if pkg:
        scripts = pkg.get("scripts") or {}
        name = "test" if "test" in scripts else "check" if "check" in scripts else None
        if name:
            pm = package_manager(d, pkg)
            # тело скрипта — в строке записи tests: package.json ветки PR меняет сам, argus сверяет команду
            body = " ".join(str(scripts[name]).split())[:300]
            return [pm, "run", name], f"{pm} run {name}  # package.json: {body}"
    try:
        with open(os.path.join(d, "pyproject.toml"), encoding="utf-8") as fh:
            py = fh.read()
    except OSError:
        py = ""
    if re.search(r"^\[tool\.pytest", py, re.M):
        argv = ["uv", "run", "pytest"] if os.path.exists(os.path.join(d, "uv.lock")) else ["python3", "-m", "pytest"]
        return argv, " ".join(argv)
    return None, "нечем проверить: нет .pantheon-verify, скрипта test/check в package.json и pytest в pyproject.toml"


def workspaces(d, pkg):
    """{папка от корня: package.json} пакетов монорепо: workspaces в package.json (список или {packages}) и packages в
    pnpm-workspace.yaml (шаблоны вида apps/*, «!» — исключение не поддержано, такие строки пропускаются)."""
    pats = []
    ws = (pkg or {}).get("workspaces")
    if isinstance(ws, dict):
        ws = ws.get("packages")
    if isinstance(ws, list):
        pats += [x for x in ws if isinstance(x, str)]
    try:
        with open(os.path.join(d, "pnpm-workspace.yaml"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    inpk = False
    for ln in text.splitlines():
        if re.match(r"^packages\s*:", ln):
            inpk = True
            continue
        if inpk:
            m = re.match(r"""^\s+-\s*['"]?([^'"#]+?)['"]?\s*(#.*)?$""", ln)
            if m:
                pats.append(m.group(1).strip())
            elif ln.strip() and not ln[:1].isspace():
                inpk = False
    out = {}
    for pat in pats:
        if pat.startswith("!") or os.path.isabs(pat) or ".." in pat.split("/"):
            continue
        for p in sorted(glob.glob(os.path.join(d, pat), recursive=True)):
            rel = os.path.relpath(p, d)
            if rel == "." or "node_modules" in rel.split(os.sep) or not inside(os.path.realpath(p), [d]):
                continue
            pj = _pkg(p)
            if pj is not None:
                out[rel] = pj
    return out


def _scripts(pkg):
    s = (pkg or {}).get("scripts")
    return s if isinstance(s, dict) else {}


def serve_command(d, script=None, app=None):
    """Команда сервера в папке d → (argv, строка для журнала, папка запуска) или (None, причина, None).
    Монорепо: PORT получает одно приложение (metis-0614: в BA turbo пускал все, landing брал PORT, web — 3000) —
    --app или единственное приложение со скриптом; `--app .` — корневой скрипт."""
    name = script or "dev"
    pkg = _pkg(d)
    if pkg is None:
        return None, "в папке нет package.json — серверу нечего запускать", None
    pm = package_manager(d, pkg)
    ws = workspaces(d, pkg)
    if app == "." or (not app and not ws):
        if name not in _scripts(pkg):
            return None, f"в package.json папки нет скрипта «{name}»", None
        return [pm, "run", name], f"{pm} run {name}", d
    if not ws:
        return None, f"--app {app}: папка не монорепо (нет workspaces в package.json и pnpm-workspace.yaml)", None
    label = {rel: str(p.get("name") or os.path.basename(rel)) for rel, p in ws.items()}
    if app:
        hits = [rel for rel, p in ws.items() if p.get("name") == app or os.path.basename(rel) == app]
        if not hits:
            return None, f"в монорепо нет приложения «{app}» (есть: {', '.join(sorted(label.values()))})", None
        rel = hits[0]
        if name not in _scripts(ws[rel]):
            return None, f"у приложения «{app}» ({rel}) нет скрипта «{name}»", None
    else:
        cands = sorted(rel for rel, p in ws.items() if name in _scripts(p))
        if len(cands) != 1:
            have = ", ".join(label[r] for r in cands) or "ни у одного"
            return None, (f"монорепо: укажи --app ИМЯ — PORT получит одно приложение (скрипт «{name}»: {have}); "
                          "корневой скрипт — --app ."), None
        rel = cands[0]
    return [pm, "run", name], f"{pm} run {name}  (приложение {rel})", os.path.join(d, rel)


def empty_command(line):
    """Пустая команда тестов (true, echo ok, CI=1 true): записи tests не будет. У скрипта package.json — его тело."""
    line, _, note = line.partition("  # ")
    if note.startswith("package.json: "):
        line = note[len("package.json: "):]
    try:
        words = shlex.split(line)
    except ValueError:
        return False
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    return not words or os.path.basename(words[0]) in EMPTY


# --- профиль и окружение ------------------------------------------------------------------------------------------

def _q(p):
    return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'


def profile_text(roots=()):
    """Профиль sandbox-exec: всё, кроме ключей, записи в состояние и ядро и портов браузеров и прокси."""
    h = os.path.realpath(P.HOME)
    secret_dirs = [".ssh", ".config/cdp-daemon", ".config/gh", ".gnupg", ".aws", "Library/Keychains"]
    # ~/.npmrc — ключи реестров (_authToken); npm и pnpm без него работают: проба 28.10, metis-0573
    secret_files = [".netrc", ".git-credentials", ".npmrc"]
    read = [f"(subpath {_q(os.path.join(h, x))})" for x in secret_dirs] + \
           [f"(literal {_q(os.path.join(h, x))})" for x in secret_files] + \
           ['(regex #"/\\.env[^/]*$")', '(regex #"/secrets(/|$)")'] + \
           [f"(subpath {_q(os.path.realpath(env_dir()))})"]   # dev-ключи проектов: их отдаёт окружением проход
    wdirs = [P.STATE, P.PANTHEON, os.path.join(h, ".claude"), os.path.join(h, ".local", "bin"),
             os.path.join(h, ".local", "share", "pantheon"), os.path.join(h, "Library", "LaunchAgents"),
             os.path.join(h, ".config", "git"), os.path.join(h, ".nvm"),
             os.path.join(h, "Library", "Caches", "pantheon-sandbox")]   # node владельца и кэши окон ролей
    wfiles = [os.path.join(h, x) for x in (".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc", ".bash_profile",
                                          ".profile", ".gitconfig")]
    write = [f"(subpath {_q(os.path.realpath(x))})" for x in wdirs] + [f"(literal {_q(x)})" for x in wfiles]
    for r in roots:
        write.append(f'(regex #"^{re.escape(r)}/(.*/)?\\.git/(config|hooks)(/|$)")')
    net = [f'(remote ip "*:{p}")' for p in DENY_PORTS]
    return "\n".join([
        "(version 1)",
        "(allow default)",
        "(deny file-read* file-write*\n  " + "\n  ".join(read) + ")",
        # шаблоны без секретов читаются (metis-0578); поздние правила сильнее; запись в них закрыта deny выше
        '(allow file-read* (regex #"/\\.env\\.(example|sample|template)$"))',
        '(deny file-read* (regex #"/secrets(/|$)"))',   # secrets/ закрыта целиком, и шаблон в ней тоже
        '(deny mach-lookup (global-name "com.apple.SecurityServer"))',
        "(deny file-write*\n  " + "\n  ".join(write) + ")",
        "(deny network-outbound\n  " + "\n  ".join(net) + ")",
    ]) + "\n"


def write_profile(roots):
    os.makedirs(root(), mode=0o700, exist_ok=True)
    p = root("profile.sb")
    tmp = f"{p}.{os.getpid()}"
    with open(tmp, "w") as fh:
        fh.write(profile_text(roots))
    os.replace(tmp, p)
    return p


def sandbox_env(tmpdir, kind, port=None, keys=None):
    """Окружение команды с нуля: ни ключей окружения тика, ни GH_*, ни переменных launchd. keys — dev-ключи проекта
    (только у сервера), служебные имена ими не перекрываются."""
    path = [x for x in [P.nvm_bin(), os.path.join(P.PLUGIN, "bin"), os.path.join(P.HOME, ".local", "bin")] if x]
    env = dict(keys or {})
    env.update({"HOME": os.path.realpath(P.HOME), "PATH": ":".join(path + SAFE_PATH), "LANG": "en_US.UTF-8",
                "TMPDIR": tmpdir, "PANTHEON_STATE": P.STATE, "NEXT_TELEMETRY_DISABLED": "1", "DO_NOT_TRACK": "1"})
    if kind == "test":
        env["CI"] = "1"
    if port:
        env["PORT"] = str(port)
    return env


def wrap(argv, profile, heavy=True):
    """[heavy] sandbox-exec -f профиль argv; сервер — без heavy: лимит серверов и памяти держит проход (metis-0614)."""
    hv = heavy_bin() if heavy else None
    return ([hv] if hv else []) + [SANDBOX_EXEC, "-f", profile] + argv


def tail(log):
    try:
        with open(log, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 64 * 1024))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-TAIL_LINES:])[-TAIL_CHARS:]


PS = "/bin/ps"   # setuid: под sandbox-exec не запускается — test_outside, идущий через `outside test`, ставит свой


def _ps_table_libproc():
    """{pid: (ppid, pgid, rss в КБ)} по libproc (proc_listallpids, proc_pidinfo PROC_PIDTBSDINFO и PROC_PIDTASKINFO)
    или None: не macOS, библиотеки нет или список процессов не получен."""
    lp = _libproc()
    if lp is None:
        return None
    lib = lp[0]
    n = lib.proc_listallpids(None, 0)
    if n <= 0:
        return None
    buf = (ctypes.c_int * (n + 256))()
    got = lib.proc_listallpids(buf, ctypes.sizeof(buf))   # число pid, а не байт
    if got <= 0:
        return None
    table = {}
    for p in buf[:min(got, len(buf))]:
        if p <= 0:
            continue
        b = _BSDInfo()
        if lib.proc_pidinfo(p, 3, ctypes.c_uint64(0), ctypes.byref(b), ctypes.sizeof(b)) != ctypes.sizeof(b):
            continue                 # ушёл за время обхода или чужой
        t = (ctypes.c_uint64 * 12)()   # proc_taskinfo: pti_virtual_size, pti_resident_size, ...
        ok = lib.proc_pidinfo(p, 4, ctypes.c_uint64(0), ctypes.byref(t), ctypes.sizeof(t)) == ctypes.sizeof(t)
        table[p] = (b.ppid, b.pgid, t[1] // 1024 if ok else 0)
    return table or None


def ps_table():
    """{pid: (ppid, pgid, rss в КБ)} всех процессов: на macOS по libproc (setuid /bin/ps под sandbox-exec не
    запускается, и strays() иначе вернул бы [] — metis-0786), ps — запасной путь (Linux, нет libproc); сбой — {}."""
    table = _ps_table_libproc()
    if table is not None:
        return table
    try:
        out = subprocess.run([PS, "-axo", "pid=,ppid=,pgid=,rss="], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    table = {}
    for ln in out.splitlines():
        try:
            p, pp, g, rss = (int(x) for x in ln.split())
        except ValueError:
            continue
        table[p] = (pp, g, rss)
    return table


def _tree(pid, table):
    """Члены группы pid и все их потомки (в том числе в своих группах)."""
    kids = {}
    for p, (pp, _g, _r) in table.items():
        kids.setdefault(pp, []).append(p)
    seen, todo = set(), [p for p, (_pp, g, _r) in table.items() if g == pid]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        todo.extend(kids.get(p, ()))
    return seen


def strays(pid, table=None):
    """[(pid, pgid)] потомков группы pid, ушедших в свою группу процессов: turbo ставит каждой задаче свою, и next dev
    в ней переживал killpg группы сервера (metis-0606). Собирать до сигнала: после него сироты уходят к launchd.
    Начало обхода — только члены группы pid: pid не глава (номер достался чужому процессу) и группы нет — [], как у
    killpg, который такой группе ничего не шлёт."""
    table = ps_table() if table is None else table
    return [(p, table[p][1]) for p in sorted(_tree(pid, table)) if table[p][1] != pid]


def tree_mb(pid, table):
    """Память сервера, МБ: сумма RSS группы pid и её потомков, ушедших в свои группы (next dev под turbo)."""
    return sum(table[p][2] for p in _tree(pid, table)) // 1024


def _signal(pid, extra, sig):
    """sig группе pid и ушедшим потомкам: группе, если её глава — наш потомок, иначе самому процессу."""
    own = {p for p, _ in extra} | {pid}
    for target, group in [(pid, True)] + [(g, True) if g in own else (p, False) for p, g in extra]:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            (os.killpg if group else os.kill)(target, sig)


def _any_alive(pid, extra):
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, os.WNOHANG)
    for target, fn in [(pid, os.killpg)] + [(p, os.kill) for p, _ in extra]:
        try:
            fn(target, 0)
            return True
        except (ProcessLookupError, PermissionError):
            continue
    return False


def kill_group(pid):
    """SIGTERM группе процессов и её потомкам в своих группах (strays), через KILL_WAIT с — SIGKILL."""
    extra = strays(pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _any_alive(pid, extra):
            return
        _signal(pid, extra, sig)
        deadline = time.monotonic() + (KILL_WAIT if sig == signal.SIGTERM else 1)
        while time.monotonic() < deadline:
            if not _any_alive(pid, extra):
                return
            time.sleep(0.1)


LSOF = "/usr/sbin/lsof"


def work_procs(work):
    """[pid] своих процессов, у которых текущая папка — копия заявки work или внутри неё (metis-0614): сирота next dev,
    ушедший к launchd до гашения, не попадает ни в группу, ни в strays, а папку держит. Папка копии — только наша."""
    work = os.path.realpath(work)
    try:
        out = subprocess.run([LSOF, "-nP", "-d", "cwd", "-Fpn"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids, cur = set(), None
    for ln in out.splitlines():
        if ln.startswith("p"):
            cur = int(ln[1:]) if ln[1:].isdigit() else None
        elif ln.startswith("n") and cur and cur != os.getpid() and inside(ln[1:], [work]):
            pids.add(cur)
    return sorted(pids)


def reap(work):
    """SIGTERM процессам с текущей папкой в копии, через KILL_WAIT с — SIGKILL. → число найденных."""
    if not work or not inside(os.path.realpath(work), [work_root()]):
        return 0
    pids = work_procs(work)
    found = len(pids)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        left = []
        for p in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(p, sig)
                left.append(p)
        deadline = time.monotonic() + (KILL_WAIT if sig == signal.SIGTERM else 1)
        while left and time.monotonic() < deadline:
            left = [p for p in left if _pid_alive(p)]
            if left:
                time.sleep(0.1)
        pids = left
        if not pids:
            break
    return found


def _pid_alive(p):
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(p, os.WNOHANG)
    try:
        os.kill(p, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


class Silent(Exception):
    """Лог молчал IDLE_TIMEOUT с при почти нулевом CPU дерева: группа убита (SIGKILL), why — для итога."""

    def __init__(self, secs, last):
        self.secs, self.last = secs, last
        mins = f"{round(secs / 60)} мин" if secs >= 60 else f"{round(secs)} с"
        self.why = f"тишина {mins}, последний вывод: {last or '(пусто)'}"
        super().__init__(self.why)


def _cpu_secs(text):
    """Время процессора ps («MM:SS.ss», «H:MM:SS», «D-HH:MM:SS») → секунды или None."""
    try:
        days, _, rest = text.rpartition("-")
        total = 0.0
        for part in rest.split(":"):
            total = total * 60 + float(part)
        return total + (int(days) * 86400 if days else 0)
    except ValueError:
        return None


LIBPROC = "/usr/lib/libproc.dylib"   # macOS: дерево и CPU без ps (metis-0770); нет файла — запасной путь по ps


def _libproc():
    """(libproc, секунд в тике mach) или None: не macOS или библиотеки нет. ri_user_time и ri_system_time —
    в тиках mach_absolute_time (на Apple Silicon тик ≠ нс: 125/3 нс), поэтому множитель — mach_timebase_info."""
    if sys.platform != "darwin":
        return None
    try:
        lib = ctypes.CDLL(LIBPROC)
        tb = (ctypes.c_uint32 * 2)()
        if ctypes.CDLL(None).mach_timebase_info(tb) != 0 or not tb[1]:
            return None
        return lib, tb[0] / tb[1] / 1e9
    except (OSError, AttributeError):
        return None


class _BSDInfo(ctypes.Structure):
    """struct proc_bsdinfo (sys/proc_info.h), PROC_PIDTBSDINFO = 3."""
    _fields_ = [(n, ctypes.c_uint32) for n in ("flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
                                               "rgid", "svuid", "svgid", "rfu")] + \
               [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)] + \
               [(n, ctypes.c_uint32) for n in ("nfiles", "pgid", "pjobc", "tdev", "tpgid")] + \
               [("nice", ctypes.c_int32), ("start", ctypes.c_uint64), ("ustart", ctypes.c_uint64)]


def _lp_pids(fn, arg):
    """[pid] из proc_listpgrppids или proc_listchildpids (они возвращают число pid, а не байт); сбой — []."""
    n = 256
    while True:
        buf = (ctypes.c_int * n)()
        got = fn(int(arg), buf, ctypes.sizeof(buf))
        if got < 0:
            return []
        if got < n or n >= 1 << 16:
            return [p for p in buf[:min(got, n)] if p > 0]
        n *= 4                       # буфер полон — список мог не влезть, берём больше


def _tree_cpu_libproc(pid):
    """CPU-секунды группы pid и её потомков по libproc (proc_listpgrppids, proc_listchildpids, proc_pid_rusage
    rusage_info_v0: ri_user_time + ri_system_time) или None: не macOS, группы нет или ни одного ответа."""
    lp = _libproc()
    if lp is None:
        return None
    lib, scale = lp
    seen, todo = set(), _lp_pids(lib.proc_listpgrppids, pid)
    while todo:                      # то же дерево, что _tree: члены группы и все их потомки в любых группах
        p = todo.pop()
        if p not in seen:
            seen.add(p)
            todo.extend(_lp_pids(lib.proc_listchildpids, p))
    buf = ctypes.create_string_buffer(256)   # rusage_info_v0 — 96 байт: uuid[16], ri_user_time, ri_system_time, …
    total, got = 0, False
    for p in seen:
        if lib.proc_pid_rusage(p, 0, buf) == 0:
            user, sys_ = struct.unpack_from("2Q", buf, 16)
            total, got = total + user + sys_, True
    return total * scale if got else None


def _tree_cpu_ps(pid):
    """CPU-секунды группы pid и её потомков по ps (Linux; на macOS — если libproc не ответил) или None."""
    table = ps_table()
    pids = _tree(pid, table) if table else set()
    if not pids:
        return None
    try:
        out = subprocess.run([PS, "-axo", "pid=,time="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    total, seen = 0.0, False
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) in pids:
            c = _cpu_secs(parts[1])
            if c is not None:
                total, seen = total + c, True
    return total if seen else None


def tree_cpu(pid):
    """Сумма CPU-секунд группы pid и её потомков (в своих группах тоже) или None — CPU не узнать, тогда судим только
    по тишине лога и не гасим (metis-0770). На macOS — libproc: setuid /bin/ps под sandbox-exec не запускается, и
    сторож в прогоне под песочницей иначе не гасил бы никогда; ps — запасной путь (Linux, нет libproc). Ушедшие за
    время опроса процессы счёт занижают — не страшно."""
    cpu = _tree_cpu_libproc(pid)
    return cpu if cpu is not None else _tree_cpu_ps(pid)


def last_line(log):
    """Последняя непустая строка лога (до 200 знаков) или ''."""
    for ln in reversed(tail(log).splitlines()):
        if ln.strip():
            return ln.strip()[:200]
    return ""


def wait_proc(proc, timeout, tick=None, idle_log=None):
    """proc.wait(timeout), а каждые SWEEP_EVERY с — tick(): у прохода серверов это сторож (sweep_quiet) и проверка
    «стопа» своей заявки — tick() вернул True — группа гаснет, ждём её конца (metis-0606, 0614). Тесты идут в своём
    проходе и серверы не смотрят. TimeoutExpired — как у proc.wait.
    idle_log — сторож тишины (metis-0770): файл не растёт IDLE_TIMEOUT с И прирост CPU-времени дерева (user+sys, tree_cpu: libproc или ps)
    за окно меньше IDLE_CPU от окна → SIGKILL группе и её потомкам, исключение Silent. Считающий без вывода (под
    нагрузкой «0 % CPU» по ps — не зависание) не гасится; CPU не узнать — не гасим, предупреждение в журнал."""
    deadline = time.monotonic() + timeout
    step = min(SWEEP_EVERY, max(0.1, IDLE_TIMEOUT / 4)) if idle_log else SWEEP_EVERY
    size, grew = None, time.monotonic()
    base = None                      # (время, CPU дерева) на первом тихом шаге после роста лога
    warned = False
    while True:
        try:
            return proc.wait(timeout=max(0.01, min(step, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                raise
        if tick and tick():
            kill_group(proc.pid)
            return proc.wait()
        if idle_log:
            now = time.monotonic()
            try:
                cur_size = os.stat(idle_log).st_size
            except OSError:
                cur_size = size
            if cur_size != size:
                size, grew, base = cur_size, now, None
            elif base is None or base[1] is None:
                base = (now, tree_cpu(proc.pid))
                if base[1] is None and now - grew >= IDLE_TIMEOUT and not warned:
                    warned = True    # CPU не узнать — не гасим, только предупреждение (раз за прогон)
                    log_event(kind="test-silent-nocpu", log=idle_log,
                              why=f"лог молчит {round(now - grew)} с, CPU дерева не узнать (libproc, ps) — не гашу")
            elif now - grew >= IDLE_TIMEOUT and now - base[0] >= IDLE_TIMEOUT / 2:
                cpu = tree_cpu(proc.pid)
                if cpu is None:      # CPU не узнать — не гасим, только предупреждение (раз за прогон)
                    if not warned:
                        warned = True
                        log_event(kind="test-silent-nocpu", log=idle_log,
                                  why=f"лог молчит {round(now - grew)} с, CPU дерева не узнать (libproc, ps) — не гашу")
                elif (cpu - base[1]) < IDLE_CPU * (now - base[0]):
                    last = last_line(idle_log)
                    extra = strays(proc.pid)
                    _signal(proc.pid, extra, signal.SIGKILL)
                    kill_group(proc.pid)
                    proc.wait()
                    raise Silent(now - grew, last)
                else:
                    base = (now, cpu)   # дерево считает без вывода (load высокий — не зависание): окно заново


_SWEEP_ERR = []


def sweep_quiet():
    """sweep() посреди чужой работы прохода: его сбой не роняет прогон тестов, в журнал — один раз."""
    try:
        sweep()
    except Exception as e:  # noqa: BLE001 — прогон тестов важнее; сам сбой виден в журнале и на следующем sweep()
        if not _SWEEP_ERR:
            _SWEEP_ERR.append(e)
            log_event(kind="sweep-error", why=f"{type(e).__name__}: {e}")


def started(pid):
    """Время старта процесса по ps (lstart, LC_ALL=C, TZ=UTC: смена пояса или летнего времени за жизнь сервера иначе
    меняет строку, и живой сервер сочли бы чужим) или None — процесса нет."""
    try:
        r = subprocess.run([PS, "-o", "lstart=", "-p", str(int(pid))], capture_output=True, text=True,
                           timeout=10, env={"LC_ALL": "C", "TZ": "UTC", "PATH": "/usr/bin:/bin"})
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return " ".join(r.stdout.split()) or None


def foreign(pid, when):
    """Номер pid сервера занял другой процесс: жив, а время старта не то, что записано при запуске. Такой не гасить —
    только снять запись (metis-0606). Записи без времени (до этой правки) и умерший pid — не чужие."""
    if not pid or not when:
        return False
    now = started(pid)
    return now is not None and now != when


def alive(pid):
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, os.WNOHANG)
    try:
        os.killpg(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# --- запись tests для шлюза слияния ------------------------------------------------------------------------------

def records_file():
    return os.path.join(P.STATE, "merge-gate", "records.jsonl")


def read_records():
    try:
        fd = os.open(records_file(), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return []
    out = []
    with os.fdopen(fd, "rb") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(rec, dict) and isinstance(rec.get("repo"), list) and isinstance(rec.get("sha"), str):
                out.append(rec)
    return out


def append_tests(repos, sha, cwd, line, window, rid, by_tree=None, rerun=None):
    """Строка tests в журнал шлюза — формат записи хука guard (merge_gate.record), by — проход. Сверх него — дерево
    коммита (tree) и скрытые входы прогона (env, run_env): по ним зелёный полный набор переносится на коммит с тем же
    деревом (tree_record, metis-0732); by_tree — коммит, чей прогон перенесён (запись без своего прогона); rerun —
    {rerun_of, files, map} зелёного дозапуска после красного полного набора (metis-0735, rerun_plan)."""
    d = os.path.dirname(records_file())
    if os.path.islink(d):
        raise OSError("merge-gate — ссылка")
    os.makedirs(d, mode=0o700, exist_ok=True)
    rec = {"v": 1, "kind": "tests", "repo": repos, "pr": None, "sha": sha,
           "by": {"agent_type": "pantheon-outside", "agent_id": "", "session_id": "", "window": window or "",
                  "request": rid},
           "cwd": cwd, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool_use_id": "", "cmd": line}
    tree = tree_of(cwd, sha)
    if tree:
        rec.update(tree=tree, env=run_env(line))
    if by_tree:
        rec["by_tree"] = by_tree
    if rerun:
        rec.update(rerun_of=rerun["rerun_of"], files=list(rerun["files"]), map=rerun["map"])
    fd = os.open(records_file(), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return rec


# --- зелёная запись по дереву (metis-0732) ------------------------------------------------------------------------

def tree_of(d, sha):
    """Дерево коммита sha (`git rev-parse <sha>^{tree}`) в папке d или None."""
    t = (git(d, "rev-parse", "--verify", "-q", f"{sha}^{{tree}}") or "").strip().lower()
    return t if SHA_RE.fullmatch(t) else None


def run_env(line):
    """Скрытые входы прогона, которых нет в дереве: настоящий путь python команды (у Homebrew в нём версия:
    Cellar/python@3.14/3.14.0/…) по PATH окружения команды и версия macOS. Другой python или macOS — запись по дереву
    не переносится."""
    import platform
    exe = None
    for w in line.split():
        if re.fullmatch(r"python3(\.\d+)?", os.path.basename(w)):
            exe = w if "/" in w else shutil.which(w, path=sandbox_env("", "test")["PATH"])
            break
    return {"python": os.path.realpath(exe) if exe else "", "os": platform.mac_ver()[0] or platform.release()}


def tree_record(rid, d, window, qdir, sha=None):
    """Проверка проекта в d без прогона, если её зелёный полный набор уже есть на этом дереве (metis-0732): в журнале
    шлюза — запись прохода (agent_type pantheon-outside) с той же командой, а она — полный набор репозитория
    (full_tests_record), с тем же деревом (поле tree и `git rev-parse <её sha>^{tree}`), теми же скрытыми входами
    (run_env) и репозиториями. На тот же коммит — итог done без новой записи; на другой (rebase без конфликтов, правка
    сообщения) — запись tests на HEAD тем же путём append_tests с отметкой by_tree. Красный прогон записи не даёт —
    переносить нечего. Дерево не чистое, такой записи нет, запись не легла — None: идёт обычный прогон. sha — коммит
    копии test --sha (metis-0779): запись — на него, HEAD и дерево папки не читаются (дерево коммита — из объектов git)."""
    sha, clean = (sha, True) if sha else head_state(d)
    if not sha or not clean:
        return None
    repos = remotes(d)
    argv, line = command(d, "test")
    m = P.merge_mod()
    if not argv or not repos or not any(m.full_tests_record(r, {"cmd": line}) for r in repos):
        return None
    tree = tree_of(d, sha)
    if not tree:
        return None
    env = run_env(line)
    want = {r.lower() for r in repos}
    for rec in reversed(read_records()):
        by = rec.get("by") if isinstance(rec.get("by"), dict) else {}
        if (rec.get("kind") != "tests" or by.get("agent_type") != "pantheon-outside" or rec.get("cmd") != line
                or rec.get("tree") != tree or rec.get("env") != env
                or not want <= {str(r).lower() for r in rec["repo"]}
                or not SHA_RE.fullmatch(rec["sha"]) or tree_of(d, rec["sha"]) != tree):
            continue
        src = rec["by"].get("request") or "?"
        res = {"state": "done", "kind": "test", "sha": sha, "code": 0, "cmd": line, "dir": d, "record": True,
               "tree": tree, "by_tree": rec["sha"]}
        if rec["sha"] == sha:
            res["note"] = f"запись tests на {sha[:12]} уже есть (прогон {src}) — без прогона"
        else:
            # дозапуск-источник переносит и свои поля: запись на новом коммите остаётся дозапуском (metis-0735)
            rr = ({k: rec[k] for k in ("rerun_of", "files", "map")}
                  if all(k in rec for k in ("rerun_of", "files", "map")) else None)
            try:
                append_tests(repos, sha, d, line, window, rid, by_tree=rec["sha"], rerun=rr)
            except OSError:
                return None
            res["note"] = (f"по дереву {tree[:12]}: зелёный полный набор на {rec['sha'][:12]} (прогон {src}) — "
                           f"запись на {sha[:12]} без прогона")
        log_event(id=rid, kind="test", window=window, dir=d, sha=sha, code=0, record=True, by_tree=rec["sha"])
        return save_result(qdir, rid, res)
    return None


# --- дозапуск после красного полного набора (metis-0735) ----------------------------------------------------------

# правка этих файлов меняет сам выбор тестов или их общую опору — дозапуск не годится, весь набор: раннер и карта
# (их путь — из команды), heavy, общие модули тестов tests/_*.py любого плагина, строка проверки .pantheon-verify
FORCE_FULL_RE = re.compile(r"(?:^|/)bin/heavy$|(?:^|/)tests/_[^/]*\.py$|^\.pantheon-verify$")
# строки run-tests.py (report и summary): «ok   плагин/test_x.py · …», «FAIL плагин/test_x.py · …», последняя —
# «итого: файлов N, ok A, FAIL B…»
REPORT_RE = re.compile(r"(ok|FAIL)\s+([A-Za-z0-9_.-]+/test_[^\s/]+\.py) · ")
TOTAL_RE = re.compile(r"итого: файлов (\d+), ok (\d+), FAIL (\d+)\b")
LOG_MAX = 64 * 1024 * 1024
_RUNNER = []


def full_file():
    """Журнал прогонов полного набора (metis-0735): пишет только проход, роли и команде под профилем STATE закрыт."""
    return root("full.jsonl")


def read_full():
    try:
        fd = os.open(full_file(), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return []
    out = []
    with os.fdopen(fd, "rb") as fh:
        for raw in fh:
            try:
                e = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(e, dict) and isinstance(e.get("rid"), str) and isinstance(e.get("repo"), list):
                out.append(e)
    return out


def append_full(entry):
    d = root()
    if os.path.islink(d):
        raise OSError("outside — ссылка")
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd = os.open(full_file(), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps({"v": 1, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **entry},
                                 ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def run_failed(text):
    """Вывод run-tests.py → (метки ok, метки FAIL), отсортированные; None — итог не разобрать. Строки файлов — только
    до хвостов упавших («===== …»: там вывод самих файлов, и в нём бывают свои ok/FAIL), последняя непустая строка —
    итог, и числа в нём сходятся со строками: прерванный, убитый по таймауту или чужой вывод даёт None, а не пустой
    список упавших."""
    lines = text.splitlines()
    last = next((ln.strip() for ln in reversed(lines) if ln.strip()), "")
    m = TOTAL_RE.match(last)
    if not m:
        return None
    n, n_ok, n_fail = (int(x) for x in m.groups())
    ok, fail = set(), set()
    for ln in lines:
        if ln.startswith("===== "):
            break
        r = REPORT_RE.match(ln)
        if r:
            (ok if r[1] == "ok" else fail).add(r[2])
    if ok & fail or len(ok) != n_ok or len(fail) != n_fail or n_ok + n_fail != n:
        return None
    return sorted(ok), sorted(fail)


def log_text(log):
    try:
        fd = os.open(log, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return ""
    with os.fdopen(fd, "rb") as fh:
        return fh.read(LOG_MAX).decode("utf-8", "replace")


def runner_mod():
    """scripts/run-tests.py установленного плагина (не ветки PR: код прохода вне песочницы — только свой): его select,
    load_map, stale_tests и collect выбирают файлы дозапуска по карте так же, как --affected."""
    if not _RUNNER:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_run_tests",
                                                      os.path.join(P.PLUGIN, "scripts", "run-tests.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _RUNNER.append(mod)
    return _RUNNER[0]


def runner_args(cmd):
    """Команда полного набора (без heavy) → (путь run-tests.py от корня, [папки плагинов]) или None: дозапуск умеет
    только run-tests.py с папками и ключами -j/--timeout/--log-dir — без --affected, --base и --only."""
    try:
        words = shlex.split(re.sub(r"\s#.*\Z", "", cmd, flags=re.S))
    except ValueError:
        return None
    i = next((k for k, w in enumerate(words) if os.path.basename(w) == "run-tests.py"), None)
    if i is None:
        return None
    rest, dirs = iter(words[i + 1:]), []
    for w in rest:
        if w in ("-j", "--jobs", "--timeout", "--log-dir"):
            if next(rest, None) is None:
                return None
        elif w.startswith("-"):
            return None
        else:
            dirs.append(w)
    rel = [words[i]] + dirs
    if not dirs or any(os.path.isabs(x) or ".." in x.split("/") for x in rel):
        return None
    return os.path.normpath(words[i]), [os.path.normpath(x) for x in dirs]


def branch_of(d):
    return (git(d, "symbolic-ref", "-q", "--short", "HEAD") or "").strip() or None


def rerun_plan(d, sha, argv, line, repos):
    """Дозапуск вместо полного набора (metis-0735) → (план или None, почему весь набор). План — {rerun_of, prev, files,
    map, ancestor, argv}: argv — команда полного набора с `--only <файлы>`. Опора — последний настоящий полный прогон
    (не дозапуск) этого репозитория на той же ветке папки из журнала full.jsonl: красный, со списком упавших, с той же
    командой и env. Файлы — упавшие в нём и затронутые диффом его коммит → HEAD (`git diff` двух коммитов как есть,
    предок он или нет) по карте affected-map.json рядом с раннером, выбор — select раннера, как у --affected. Весь
    набор, если дифф задевает файл вне карты или общий (FULL раннера), раннер, карту, heavy, tests/_*.py, .pantheon-verify;
    карта не читается или устарела (хоть один файл тестов изменён после её сборки); упавших больше половины; дозапуск —
    весь набор; run-tests.py в HEAD не знает --only."""
    parsed = runner_args(argv[2]) if argv[:2] == ["/bin/sh", "-c"] and len(argv) == 3 else None
    if not parsed:
        return None, "команда полного набора — не run-tests.py с папками плагинов"
    script, dirs = parsed
    branch = branch_of(d)
    if not branch:
        return None, "HEAD без ветки — прошлый полный прогон не найти"
    want = {r.lower() for r in repos}
    prev = next((e for e in reversed(read_full()) if e.get("branch") == branch and not e.get("rerun_of")
                 and want <= {str(r).lower() for r in e["repo"]}), None)
    if not prev:
        return None, f"на ветке {branch} ещё нет полного прогона"
    pid, psha, failed = prev["rid"], prev.get("sha"), prev.get("failed")
    if prev.get("code") == 0:
        return None, f"последний полный прогон ветки ({pid}) зелёный"
    try:
        age = time.time() - datetime.strptime(str(prev.get("time")), "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        age = None
    if age is None or age > RERUN_MAX_AGE:
        return None, f"полному прогону {pid} больше {RERUN_MAX_AGE // 3600} ч или время не разобрать — весь набор"
    if prev.get("cmd") != line or prev.get("env") != run_env(line):
        return None, f"у прошлого полного прогона {pid} другая команда или env"
    if not isinstance(failed, list) or not failed or not all(isinstance(x, str) for x in failed):
        return None, f"в прошлом полном прогоне {pid} нет списка упавших файлов"
    if not (isinstance(psha, str) and SHA_RE.fullmatch(psha)) or git(d, "cat-file", "-e", f"{psha}^{{commit}}") is None:
        return None, f"коммита прошлого полного прогона {pid} нет в клоне"
    if "--only" not in (_show(d, sha, script) or ""):
        return None, f"{script} в HEAD не знает --only"
    out = git(d, "diff", "--name-only", "--no-renames", "-z", psha, sha, "--")
    if out is None:
        return None, f"git diff {psha[:12]}..{sha[:12]} не удался"
    changed = sorted({x for x in out.split("\0") if x})
    mp = os.path.join(os.path.dirname(script), "affected-map.json")
    forced = [x for x in changed if x in (script, mp) or FORCE_FULL_RE.search(x)]
    if forced:
        return None, f"дифф задевает {forced[0]}"
    rt = runner_mod()
    amap, why = rt.load_map(os.path.join(d, mp))
    if amap is None:
        return None, why
    items = rt.collect([os.path.join(d, x) for x in dirs])
    stale = rt.stale_tests(items, amap)
    if stale:
        return None, f"карта устарела: {len(stale)} файлов тестов изменены после её сборки ({stale[0]})"
    chosen, unknown, _ = rt.select(changed, d, items, amap)
    if unknown:
        return None, f"дифф: {unknown[0][0]} — {unknown[0][1]}"
    labels = {lb for _, lb in items}
    if len(failed) * 2 > len(labels):
        return None, f"упавших в прошлом полном прогоне {len(failed)} из {len(labels)} — больше половины"
    files = sorted({x for x in failed if x in labels} | {lb for _, lb in chosen})
    if not files or len(files) >= len(labels):
        return None, "дозапуск — весь набор" if files else "дозапускать нечего"
    try:
        with open(os.path.join(d, mp), "rb") as fh:
            mhash = hashlib.sha256(fh.read()).hexdigest()
    except OSError as e:
        return None, f"карту не прочесть: {e}"
    return {"rerun_of": pid, "prev": psha, "files": files, "map": mhash,
            "ancestor": git(d, "merge-base", "--is-ancestor", psha, sha) is not None,
            # хвост-комментарий строки (« # …») срезан: иначе --only попал бы в комментарий и sh гнал весь набор
            "argv": argv[:2] + [re.sub(r"\s#.*\Z", "", argv[2], flags=re.S) + " --only "
                                + shlex.quote(",".join(files))]}, None


# --- итоги --------------------------------------------------------------------------------------------------------

def save_result(qdir, rid, res):
    """Итог — в STATE/outside/runs/<ID>.json и, если заявка из папки, в <ID>.result.json рядом с ней."""
    res = {"id": rid, "updated": P.stamp(), **res}
    text = json.dumps(res, ensure_ascii=False, indent=1)
    os.makedirs(root("runs"), mode=0o700, exist_ok=True)
    P.write_json(root("runs", rid + ".json"), {**res, "qdir": qdir} if qdir else res)   # qdir — для recover_results
    if qdir:
        dfd = _open_dir(qdir)
        if dfd is not None:
            try:
                with contextlib.suppress(OSError):
                    _write_in(dfd, rid + ".result.json", text)
            finally:
                os.close(dfd)
    return res


def new_log(rid):
    os.makedirs(root("runs"), mode=0o700, exist_ok=True)
    p = root("runs", rid + ".log")
    return p, os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)


# --- тесты --------------------------------------------------------------------------------------------------------

def run_test(rid, d, script, window, qdir, roots, record=True, src=None, expect=None):
    """Проверка проекта в папке d на её HEAD → итог. Запись tests — при коде 0 и том же чистом HEAD, только у проверки
    проекта: с --script записи нет. src — папка заявки, когда d — своя копия на коммите (test --sha, run_test_at): по
    ней live_test находит идущую заявку. expect — коммит копии: HEAD не он или дерево не чистое (установка зависимостей
    сдвинула HEAD или правит дерево) — ни прогона, ни записи; после прогона HEAD и чистота сверяются как всегда."""
    def off(sha, clean):
        """Копия ушла с коммита заявки (expect) → итог failed; иначе None."""
        if not expect or (sha == expect and clean):
            return None
        why = (f"копия {d} — не чистый коммит заявки {expect[:12]} (HEAD {(sha or '?')[:12]}, "
               f"чистое: {'да' if clean else 'нет'}) — прогона и записи нет")
        log_event(id=rid, kind="refused", window=window, dir=d, sha=expect, why=why)
        return save_result(qdir, rid, {"state": "failed", "kind": "test", "sha": expect, "why": why,
                                       **({"src": src} if src else {})})

    res = off(*head_state(d)) if expect else None
    if res:
        return res
    record = record and not script
    # metis-0732: зелёный полный набор на этом дереве уже есть; у копии — на коммите заявки, а не на HEAD
    res = record and tree_record(rid, d, window, qdir, sha=expect)
    if res:
        return res
    sha, clean = head_state(d)
    res = off(sha, clean)   # между проверками HEAD мог сдвинуться: дальше sha — только expect
    if res:
        return res
    if not sha:
        return save_result(qdir, rid, {"state": "failed", "kind": "test", "why": "папка не репозиторий git или нет коммитов"})
    if not clean:
        return save_result(qdir, rid, {"state": "failed", "kind": "test", "sha": sha,
                                       "why": "дерево не чистое — тесты идут на коммит: закоммить правки"})
    argv, line = command(d, "test", script)
    if not argv:
        return save_result(qdir, rid, {"state": "failed", "kind": "test", "sha": sha, "why": line})
    repos0 = remotes(d) if record else []
    full = bool(repos0) and any(P.merge_mod().full_tests_record(r, {"cmd": line}) for r in repos0)
    plan, full_why = None, None
    if full:   # metis-0735: после красного полного набора — дозапуск упавших и затронутых
        try:
            plan, full_why = rerun_plan(d, sha, argv, line, repos0)
        except Exception as e:   # сбой расчёта — не повод не гонять: весь набор
            plan, full_why = None, f"дозапуск не рассчитан: {type(e).__name__}: {e}"
    extra = {"rerun_of": plan["rerun_of"], "files": plan["files"]} if plan else \
        ({"full_why": full_why} if full_why else {})
    if src:
        extra["src"] = src
    if expect:   # test --sha: итог running несёт pin, live_test не сцепляет с ним обычную заявку (metis-0796)
        extra["pin"] = True
    save_result(qdir, rid, {"state": "running", "kind": "test", "sha": sha, "cmd": line, "dir": d,
                            **({"script": script} if script else {}), **extra})
    log, fd = new_log(rid)
    tmp = tempfile.mkdtemp(prefix="outside-")
    code, timed_out = None, False
    try:
        with contextlib.suppress(OSError):
            os.write(fd, (f"$ {line}  (папка {d}, {sha})\n" + (
                f"дозапуск после красного полного набора {plan['rerun_of']} на {plan['prev'][:12]}: "
                f"{', '.join(plan['files'])}\n$ {plan['argv'][2]}\n" if plan else "")).encode())
        try:
            proc = subprocess.Popen(wrap(plan["argv"] if plan else argv, write_profile(roots)), cwd=d,
                                    env=sandbox_env(tmp, "test"),
                                    stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, start_new_session=True)
        except OSError as e:
            return save_result(qdir, rid, {"state": "failed", "kind": "test", "sha": sha, "cmd": line,
                                           "why": f"команда не запустилась: {e}", "log": log})
        try:
            code = wait_proc(proc, TEST_TIMEOUT, idle_log=log)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_group(proc.pid)
            code = proc.wait()
        except Silent as e:      # завис без вывода и CPU: тот же журнал, что отказ запуска (metis-0770)
            with contextlib.suppress(OSError):
                os.write(fd, f"\n{e.why}\n".encode())
            log_event(kind="test-silent", id=rid, why=e.why)
            return save_result(qdir, rid, {"state": "failed", "kind": "test", "sha": sha, "cmd": line, "why": e.why,
                                           "log": log, "tail": tail(log)})
    finally:
        os.close(fd)
        shutil.rmtree(tmp, ignore_errors=True)
    sha2, clean2 = head_state(d)
    res = {"state": "done", "kind": "test", "sha": sha, "code": code, "cmd": line, "dir": d, "log": log,
           "tail": tail(log), "record": False, **extra}
    got = run_failed(log_text(log)) if full else None
    if plan:
        res["note"] = (f"дозапуск после красного полного набора {plan['rerun_of']} на {plan['prev'][:12]}: файлов "
                       f"{len(plan['files'])}" + ("" if plan["ancestor"] else
                                                   "; прошлый head не предок HEAD — дифф двух коммитов как есть"))
    if timed_out:
        res["why"] = f"тесты дольше {TEST_TIMEOUT} с — остановлены"
    elif sha2 != sha or not clean2:
        res["why"] = f"команда изменила HEAD или дерево (стало {sha2 or '?'}, чистое: {'да' if clean2 else 'нет'}) — записи нет"
    elif code == 0 and not record:
        res["note"] = "запись tests для шлюза — только у проверки проекта (без --script)"
    elif code == 0:
        repos = remotes(d)
        if empty_command(line):
            res["why"] = f"команда «{line}» ничего не проверяет — записи tests нет"
        elif not repos:
            res["why"] = "у репозитория нет remote — записи tests нет"
        elif plan and (not got or got[1] or got[0] != plan["files"]):
            res["why"] = (f"дозапуск: вывод run-tests не сошёлся со списком файлов ({len(plan['files'])}) — "
                          "записи tests нет")
        else:
            try:
                append_tests(repos, sha, d, line, window, rid, rerun=plan)
                res["record"] = True
            except OSError as e:
                res["why"] = f"запись tests не сделана: {e}"
    if full and not timed_out and sha2 == sha and clean2:
        # журнал полных прогонов: опора следующего дозапуска (только запись без rerun_of) и след самих дозапусков
        entry = {"rid": rid, "repo": repos0, "sha": sha, "tree": tree_of(d, sha), "branch": branch_of(d), "dir": d,
                 "cmd": line, "env": run_env(line), "code": code, "failed": got[1] if got else None}
        if plan:
            entry.update(rerun_of=plan["rerun_of"], files=plan["files"], map=plan["map"])
        try:
            append_full(entry)
        except OSError as e:
            res["note"] = (res.get("note", "") + "; " if res.get("note") else "") + f"журнал full.jsonl: {e}"
    log_event(id=rid, kind="test", window=window, dir=d, sha=sha, code=code, record=res["record"],
              **({"rerun_of": plan["rerun_of"]} if plan else {}))
    return save_result(qdir, rid, res)


TEST_WORK = "test-"   # приставка копий test --sha в work_root(): drop_orphan_work (только ID) их не берёт


def run_test_at(rid, d, req, window, qdir, roots):
    """Проверка проекта на коммите заявки (test --sha, metis-0779) → итог. Окно роли не переключит свою worktree на
    ветку PR, если в ней другой .claude/ проекта (запись туда закрыта), поэтому прогон идёт в своей копии: `git worktree
    add --detach` клона d (проверен в resolve_dir) в work_root()/test-<ID>, зависимости (prepare), run_test в копии —
    запись tests на полный SHA. Копия снимается всегда; бывший head открытого PR — отказ, как у test без --sha."""
    script, common = req.get("script"), d.common
    ref = req.get("sha")
    base = {"kind": "test", "src": d, "pin": True, **({"script": script} if script else {})}

    def fail(why, **kw):
        log_event(id=rid, kind="refused", window=window, dir=d, why=why)
        return save_result(qdir, rid, {"state": "failed", **base, "why": why, **kw})

    sha = resolve_sha(common, ref) if ref else None
    if not sha:
        return fail(f"коммита {ref or '?'} нет в клоне {d.clone}: сделай git fetch в своей копии и повтори")
    why = None if script else stale_head(d, sha)
    if why:
        return fail(why, sha=sha)
    work = os.path.join(work_root(), TEST_WORK + rid)
    save_result(qdir, rid, {"state": "running", **base, "sha": sha, "dir": work})
    try:
        why = checkout(common, sha, work)
        if why:
            return fail(why, sha=sha)
        _clone, wcommon, wgitdir = trusted_clone(work)
        if wcommon != common:
            return fail(f"копия {work} — не worktree клона {d.clone}", sha=sha)
        w = checked(work, d.clone, common, wgitdir)
        code = prepare(w, rid, timeout=INSTALL_TIMEOUT)
        reap(work)   # остатки установки (фоновые процессы lifecycle-скриптов) не двигают HEAD во время теста
        if code not in (None, 0):
            log = root("runs", rid + ".log")
            return fail(f"установка зависимостей копии вышла с кодом {code}", sha=sha, log=log, tail=tail(log))
        return run_test(rid, w, script, window, qdir, roots, record=not script, src=d, expect=sha)
    finally:
        reap(work)
        remove_work(common, work)


def drop_test_work():
    """Копии test --sha (test-<ID>) в work_root() — снять: процессы в них погасить, папку удалить. Зовёт только проход
    тестов под замком outside-run до своей очереди: прогона на копии в этот момент нет, всякая копия — от упавшего
    прохода. Метаданные worktree в клоне остаются, их помечает prunable сам git. → число снятых."""
    try:
        names = os.listdir(work_root())
    except OSError:
        return 0
    n = 0
    for name in names:
        work = os.path.join(work_root(), name)
        if not (name.startswith(TEST_WORK) and ID_RE.fullmatch(name[len(TEST_WORK):])) or os.path.islink(work) \
                or not os.path.isdir(work):
            continue
        reap(work)
        remove_work(None, work)
        log_event(id=name[len(TEST_WORK):], kind="work-orphan", why="копия теста без прогона снята")
        n += 1
    return n


# --- серверы ------------------------------------------------------------------------------------------------------

def servers():
    s = P.read_json(root("servers.json"), {})
    return s if isinstance(s, dict) else {}


def save_servers(s):
    os.makedirs(root(), mode=0o700, exist_ok=True)
    P.write_json(root("servers.json"), s)


def port_free(port):
    s = socket.socket()
    try:
        # без SO_REUSEADDR: с ним macOS даёт занять 127.0.0.1:порт, когда его уже держит слушатель на 0.0.0.0 (metis-0592)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def port_open(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port(taken):
    return next((p for p in SERVER_PORTS if p not in taken and p not in OWNER_PORTS and port_free(p)), None)


# --- копия заявки и ключи (metis-0614) -----------------------------------------------------------------------------

def _small(p, limit=4096):
    """Текст обычного файла p (не ссылки) до limit байт; иначе None."""
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        return os.read(fd, limit + 1).decode("utf-8", "replace")
    finally:
        os.close(fd)


def trusted_clone(d):
    """Клон папки d (настоящий путь) по файлам (metis-0614): .git-папка → клон d; .git-файл → только worktree клона —
    gitdir <клон>/.git/worktrees/<имя>, его commondir ведёт на <клон>/.git, а gitdir — обратно на d/.git. У common нет
    своего commondir, config — обычный файл, .git, worktrees и gitdir — не ссылки; итог подтверждает сам git
    (rev-parse --git-dir --git-common-dir через этот gitdir). → (клон, common, gitdir) или (None, причина, None).
    .git-файл, ведущий куда-то ещё, — отказ: такой gitdir и его конфиг пишет роль, а .git/config клона окну роли закрыт
    (deny write ~/**/.git/config). Зовёт его только resolve_dir — один раз на заявку."""
    def no(why):
        return None, why, None

    dotgit = os.path.join(d, ".git")
    try:
        st = os.lstat(dotgit)
    except OSError:
        return no(f"папка {d} — не корень репозитория git (нет .git)")
    if stat.S_ISDIR(st.st_mode):
        gd = common = dotgit
    else:
        m = re.fullmatch(r"gitdir: *(\S[^\n]*?) *\n?", _small(dotgit) or "") if stat.S_ISREG(st.st_mode) else None
        if not m:
            return no(f"{dotgit} — не папка и не ссылка gitdir")
        gd = os.path.realpath(os.path.join(d, m.group(1)))
        common = os.path.dirname(os.path.dirname(gd))
        back = (_small(os.path.join(gd, "gitdir")) or "").strip()
        cdir = (_small(os.path.join(gd, "commondir")) or "").strip()
        if (os.path.basename(os.path.dirname(gd)) != "worktrees" or os.path.basename(common) != ".git"
                or not cdir or os.path.realpath(os.path.join(gd, cdir)) != common
                or not back or os.path.realpath(os.path.join(gd, back)) != os.path.realpath(dotgit)):
            return no(f"{dotgit} ведёт на {gd} — это не worktree клона (<клон>/.git/worktrees/<имя>)")
    clone = os.path.dirname(common)
    if any(os.path.islink(x) for x in (common, os.path.join(common, "worktrees"), gd)) or not _is_dir(common):
        return no(f"в пути {gd} — ссылка: git возьмёт не ту папку, что проверена")
    if os.path.lexists(os.path.join(common, "commondir")):
        return no(f"у {common} свой commondir — конфиг возьмётся из другой папки")
    try:
        if not stat.S_ISREG(os.lstat(os.path.join(common, "config")).st_mode):
            return no(f"{common}/config — не обычный файл")
    except OSError:
        return no(f"нет {common}/config")
    out = (git_dir(gd, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir") or "").split("\n")
    if [os.path.realpath(x) for x in out[:2] if x] != [gd, common]:
        return no(f"git видит у {d} другой gitdir или common, чем проверено")
    return clone, common, gd


def git_env():
    """Окружение git копии: только конфиг клона — ни системного, ни ~/.gitconfig, ни GIT_* тика, без вопросов."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
               GIT_NO_REPLACE_OBJECTS="1")
    return env


def git_dir(common, *args, timeout=30):
    """git --git-dir=<.git клона> с GIT_SAFE и git_env(); вывод или None."""
    try:
        r = subprocess.run(["git", f"--git-dir={common}", *GIT_SAFE, *args], capture_output=True, text=True,
                           timeout=timeout, env=git_env(), cwd=os.path.dirname(os.path.realpath(common)),
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


FSMONITOR_OFF = {"", "false", "no", "off", "0", "true", "yes", "on", "1"}   # true — встроенный монитор git, не команда
# последнее слово ключа — команда, которую git может исполнить (core.sshCommand, diff.<x>.command, diff.<x>.textconv,
# merge.<x>.driver, credential.helper, gpg.program, core.pager, core.editor…): у владельца в клонах реестра их нет
# (сверка 01.11), а вне песочницы любая из них — чужой код у прохода
EXEC_KEY_TAILS = ("command", "textconv", "driver", "helper", "program", "cmd", "pager", "editor", "askpass")


def unsafe_config(common):
    """Ключи конфига клона, которые исполнят чужую команду у прохода и не перекрываются -c: include/includeIf (конфиг из
    любого файла), filter.* (smudge/process при checkout), extensions.worktreeConfig (конфиг из папки worktree), команда в
    core.fsmonitor, ключи-команды (*.command, *.textconv, *.driver, *.helper, *.program, pager.*, alias.*).
    → причина отказа или None. Конфиг читается как файл (git config --file — без include)."""
    out = git_dir(common, "config", "--file", os.path.join(common, "config"), "--list", "-z")
    if out is None:
        return f"конфиг {common}/config не прочитать"
    bad = []
    for item in out.split("\0"):
        k, _, v = item.partition("\n")
        k = k.lower()
        if (k.startswith(("include.", "includeif.", "filter.", "pager.", "alias.")) or k == "extensions.worktreeconfig"
                or (k == "core.fsmonitor" and v.strip().lower() not in FSMONITOR_OFF)
                or (k and k.rsplit(".", 1)[-1].endswith(EXEC_KEY_TAILS))):
            bad.append(k)
    if bad:
        return f"в конфиге клона {common} — {', '.join(sorted(set(bad)))}: вне песочницы это исполнится, копию не делаю"
    return None


def origin_id(common):
    """owner/repo из remote.origin.url конфига клона (только origin: остальные remote ключей не дают); нет — None."""
    url = (git_dir(common, "config", "--file", os.path.join(common, "config"), "--get", "remote.origin.url")
           or "").strip()
    return remote_id(url) if url else None


def resolve_sha(common, ref):
    """Полный SHA коммита ref в клоне (его .git); нет такого коммита (или короткий неоднозначен) — None."""
    out = (git_dir(common, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}") or "").strip().lower()
    return out if SHA_RE.fullmatch(out) else None


def checkout(common, sha, work):
    """git worktree add --detach work sha в клоне common (GIT_SAFE, без ~/.gitconfig). → None или причина."""
    os.makedirs(os.path.dirname(work), mode=0o700, exist_ok=True)
    if git_dir(common, "worktree", "add", "--detach", work, sha, timeout=300) is None:
        return f"копия на {sha[:12]} не создана (git worktree add в {os.path.dirname(common)})"
    return None


def remove_work(common, work):
    """Снять копию: git worktree remove, затем папку целиком — только внутри work_root()."""
    if not work or not inside(os.path.realpath(work), [work_root()]):
        return
    if common:
        for args in (["worktree", "remove", "--force", work], ["worktree", "prune"]):
            git_dir(common, *args, timeout=300)
    shutil.rmtree(work, ignore_errors=True)


def _env_file(name):
    """Текст файла ключей name в env_dir(): обычный файл владельца, не ссылка; иначе None."""
    dfd = _open_dir(env_dir())
    if dfd is None:
        return None
    try:
        return _read_in(dfd, name)
    finally:
        os.close(dfd)


def parse_env(text):
    """KEY=VALUE (export впереди, кавычки, # — комментарий) → ({ключ: значение}, [пропущенные служебные имена])."""
    out, skipped = {}, []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("export "):
            ln = ln[len("export "):].lstrip()
        k, sep, v = ln.partition("=")
        k, v = k.strip(), v.strip()
        if not sep or not ENV_KEY_RE.fullmatch(k):
            continue
        if k in RESERVED_ENV or k.startswith(RESERVED_ENV_PREFIX):
            skipped.append(k)
            continue
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        else:
            v = re.sub(r"\s+#.*$", "", v)
        out[k] = v
    return out, skipped


def env_names(repo, app=None):
    """Имена файлов ключей проекта repo — owner/repo из origin клона реестра (origin_id), а не из конфига папки роли:
    <owner>__<repo>.env и, у приложения, <owner>__<repo>__<app>.env."""
    names = []
    for rid in [repo] if repo else []:
        base = rid.replace("/", "__")
        names.append(base + ".env")
        if app and app != ".":
            names.append(f"{base}__{re.sub(r'[^A-Za-z0-9._-]', '_', app.lstrip('@'))}.env")
    return names


def dev_keys(repo, app=None):
    """→ (ключи, файлы, откуда взяты, пропущенные имена). Приложение перекрывает проект."""
    keys, used, skipped = {}, [], []
    for name in env_names(repo, app):
        text = _env_file(name)
        if text is None:
            continue
        got, skip = parse_env(text)
        keys.update(got)
        used.append(name)
        skipped += skip
    return keys, used, skipped


# --- серверы: запуск ----------------------------------------------------------------------------------------------

class Cancelled(Exception):
    pass


class Busy(RuntimeError):
    pass


def stop_requests():
    """{ID: [(папка заявок, окно)]} — файлы <ID>.stop во всех папках заявок (metis-0614: стоп из окна координатора
    лежит в его папке, а не в папке окна, поднявшего сервер)."""
    out = {}
    for qdir, window in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            for name in os.listdir(dfd):
                rid = name[:-len(".stop")]
                if not name.endswith(".stop") or not ID_RE.fullmatch(rid):
                    continue
                with contextlib.suppress(OSError):
                    if stat.S_ISREG(os.lstat(name, dir_fd=dfd).st_mode):
                        out.setdefault(rid, []).append((qdir, window))
        finally:
            os.close(dfd)
    return out


def clear_stop(rid, where):
    for qdir, _ in where:
        dfd = _open_dir(qdir)
        if dfd is not None:
            _unlink_in(dfd, rid + ".stop")
            os.close(dfd)


def _stop_age(rid, where, t):
    ages = []
    for qdir, _ in where:
        with contextlib.suppress(OSError):
            ages.append(t - os.lstat(os.path.join(qdir, rid + ".stop")).st_mtime)
    return min(ages) if ages else 0


def busy_why(live):
    """Причина отказа новому серверу (лимит серверов, давление памяти) или None (решение владельца 01.11)."""
    if len(live) >= MAX_SERVERS:
        who = "; ".join(f"{r} ({s.get('src') or s.get('dir')}, до {P.stamp(float(s.get('until') or 0))})"
                        for r, s in sorted(live.items()))
        return (f"уже идут {len(live)} сервера из {MAX_SERVERS}: {who} — погаси один (pantheon outside stop ID) "
                "или дождись срока")
    level = P._memory_pressure_direct()
    if level == 4:
        return "давление памяти критичное — сервер не поднимаю, повтори позже"
    if level == 2 and live:
        return "давление памяти — предупреждение, а один сервер уже идёт: второй не поднимаю, погаси прежний"
    return None


def run_serve(rid, d, req, window, qdir):
    """Сервер заявки rid из папки заявки d: своя копия на коммите, зависимости, порт из ряда → итог."""
    script, app, minutes = req.get("script"), req.get("app"), req.get("minutes", SERVE_MIN)
    base = {"kind": "serve", "src": d, **({"app": app} if app else {})}

    def fail(why, **kw):
        log_event(id=rid, kind="serve", window=window, dir=d, ok=False, why=why)
        return save_result(qdir, rid, {"state": "failed", **base, "why": why, **kw})

    why = busy_why(servers())
    if why:
        return fail(why, busy=True)
    clone, common = d.clone, d.common   # проверены в resolve_dir (trusted_clone, реестр, unsafe_config)
    ref = req.get("sha")
    if not ref:
        return fail("в заявке нет коммита — подай заново: pantheon outside serve")
    sha = resolve_sha(common, ref)
    if not sha:
        return fail(f"коммита {ref} нет в клоне {clone}: сделай git fetch в своей копии и повтори")
    work = os.path.join(work_root(), rid)
    base.update({"sha": sha, "dir": work})
    save_result(qdir, rid, {"state": "preparing", **base})
    log, fd = new_log(rid)
    tmp, proc, port, cancelled, busy, why, keys, used, skipped = None, None, None, False, False, None, {}, [], []

    def tick():
        """Сторож других серверов и «стоп» этой заявки, пока копия, зависимости и порт."""
        sweep_quiet()
        return rid in stop_requests()

    try:
        with contextlib.suppress(OSError):
            os.write(fd, f"$ git worktree add --detach {work} {sha}  (клон {clone}, заявка из {d})\n".encode())
        why = checkout(common, sha, work)
        if why:
            raise RuntimeError(why)
        if tick():
            raise Cancelled
        argv, line, cwd = serve_command(work, script, app)
        if not argv:
            raise RuntimeError(line)
        base["cmd"] = line
        code = prepare(work, rid, heavy=False, tick=tick, timeout=INSTALL_TIMEOUT)
        if rid in stop_requests():
            raise Cancelled
        if code not in (None, 0):
            raise RuntimeError(f"установка зависимостей вышла с кодом {code}")
        live = servers()   # заново: сторож мог погасить прежние, пока шла установка
        why = busy_why(live)
        if why:
            raise Busy(why)
        port = pick_port({int(v.get("port") or 0) for v in live.values()})
        if not port:
            raise RuntimeError(f"нет свободного порта {SERVER_PORTS.start}–{SERVER_PORTS.stop - 1}")
        keys, used, skipped = dev_keys(origin_id(common), app)
        tmp = tempfile.mkdtemp(prefix="outside-")
        with contextlib.suppress(OSError):
            os.write(fd, f"$ PORT={port} {line}  (папка {cwd}; ключи: {', '.join(sorted(keys)) or 'нет'})\n".encode())
        save_result(qdir, rid, {"state": "starting", **base, "port": port})
        try:
            proc = subprocess.Popen(wrap(argv, write_profile(registry(None)), heavy=False), cwd=cwd,
                                    env=sandbox_env(tmp, "serve", port, keys), stdin=subprocess.DEVNULL, stdout=fd,
                                    stderr=fd, start_new_session=True)
        except OSError as e:
            raise RuntimeError(f"сервер не запустился: {e}") from e
        last = deadline = time.monotonic()
        deadline += READY_SEC
        while time.monotonic() < deadline and proc.poll() is None and not port_open(port):
            time.sleep(0.5)
            if time.monotonic() - last >= SWEEP_EVERY:
                last = time.monotonic()
                if tick():
                    raise Cancelled
        if proc.poll() is not None or not port_open(port):
            raise RuntimeError(f"сервер вышел с кодом {proc.returncode}" if proc.poll() is not None
                               else f"порт {port} не открылся за {READY_SEC} с")
    except Cancelled:
        cancelled = True
    except RuntimeError as e:
        why, busy = str(e), isinstance(e, Busy)
    except Exception as e:  # noqa: BLE001 — любой сбой: сервер, копия и tmp сняты, итог failed, а не preparing
        why = f"сбой прохода: {type(e).__name__}: {e}"
    finally:
        os.close(fd)
    if cancelled or why:
        if proc:
            kill_group(proc.pid)
        reap(work)
        remove_work(common, work)
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        if cancelled:
            where = stop_requests().get(rid, [])
            clear_stop(rid, where)
            log_event(id=rid, kind="stop", why="заявка «стоп» до запуска", by=[w for _, w in where])
            return save_result(qdir, rid, {"state": "stopped", **base, "why": "заявка «стоп» до запуска сервера",
                                           "log": log, "tail": tail(log)})
        return fail(why, log=log, tail=tail(log), **({"busy": True} if busy else {}))
    until = P.now() + minutes * 60
    srv = servers()   # заново: сторож в ожидании порта мог погасить и убрать прежние
    srv[rid] = {"pid": proc.pid, "started": started(proc.pid), "port": port, "until": until, "qdir": qdir,
                "window": window, "src": d, "work": work, "common": common, "sha": sha, "tmp": tmp,
                **({"app": app} if app else {})}
    save_servers(srv)
    log_event(id=rid, kind="serve", window=window, dir=d, work=work, sha=sha, port=port, ok=True, minutes=minutes,
              keys=sorted(keys))
    notes = []
    if not used:
        notes.append(f"dev-ключей нет: их кладут в {os.path.join(env_dir(), (env_names(origin_id(common), app) or ['<owner>__<repo>.env'])[0])} "
                     "(KEY=VALUE) — .env.local папки серверу закрыт")
    if skipped:
        notes.append(f"служебные имена из файла ключей не переданы: {', '.join(sorted(set(skipped)))}")
    if req.get("dirty"):
        notes.append(f"в папке заявки были незакоммиченные правки — сервер на коммите {sha[:12]}, без них")
    return save_result(qdir, rid, {"state": "serving", **base, "port": port, "url": f"http://127.0.0.1:{port}",
                                   "until": P.stamp(until), "log": log, "keys": sorted(keys), "tail": tail(log),
                                   **({"note": "; ".join(notes)} if notes else {})})


# --- серверы: сторож ----------------------------------------------------------------------------------------------

def sweep(t=None, stops=None):
    """Серверы со сроком, «стопом» из любой папки заявок или умершим процессом — погасить. → число погашенных."""
    t = P.now() if t is None else t
    stops = stop_requests() if stops is None else stops
    srv, n, table = servers(), 0, None
    for rid, s in list(srv.items()):
        pid = int(s.get("pid") or 0)
        alien = foreign(pid, s.get("started"))
        why = ("срок вышел" if t >= float(s.get("until") or 0) else "заявка «стоп»" if rid in stops
               else "процесс завершился" if not pid or alien or not alive(pid) else None)
        if not why:
            table = ps_table() if table is None else table   # один ps на круг сторожа
            mb = tree_mb(pid, table)
            if mb > SERVER_MEM_MB:
                why = f"память: {mb} МБ — больше лимита {SERVER_MEM_MB} МБ на сервер"
        if not why:
            continue
        qdir, port = s.get("qdir"), int(s.get("port") or 0)
        save_result(qdir, rid, {"state": "stopping", "kind": "serve", "port": port, "why": why})
        if pid and not alien:
            kill_group(pid)
        orphans = reap(s.get("work"))   # свои по папке копии — и у чужого номера процесса тоже
        if s.get("tmp"):
            shutil.rmtree(s["tmp"], ignore_errors=True)
        where = stops.get(rid, [])
        clear_stop(rid, where)
        del srv[rid]
        save_servers(srv)
        n += 1
        busy = bool(port) and port_open(port)
        log_event(id=rid, kind="stop", why=why, by=[w for _, w in where], **({"orphans": orphans} if orphans else {}),
                  **({"port_busy": port} if busy else {}))
        save_result(qdir, rid, {"state": "stopped", "kind": "serve", "port": port, "why": why,
                                **{k: s[k] for k in ("src", "sha", "app") if s.get(k)},
                                **({"dir": s["work"]} if s.get("work") else {}),
                                "log": root("runs", rid + ".log"), "tail": tail(root("runs", rid + ".log")),
                                **({"note": f"порт {port} после гашения ещё отвечает: его держит процесс вне дерева "
                                            "сервера и вне его копии"} if busy else {})})
        remove_work(s.get("common"), s.get("work"))   # после итога: снимать node_modules — секунды, стоп уже сделан
    return n


def drop_orphan_stops(stops=None, t=None):
    """«Стоп» без живого сервера и без заявки в очереди, старше STOP_ORPHAN_AGE, — убрать (тесты и уже погашенные
    серверы гасить нечего; молодой — может ждать свою заявку). → число убранных."""
    t = P.now() if t is None else t
    stops = stop_requests() if stops is None else stops
    live = set(servers())
    queued = {rid for rid, _ in _queued_ids()}
    n = 0
    for rid, where in stops.items():
        if rid in live or rid in queued or _stop_age(rid, where, t) < STOP_ORPHAN_AGE:
            continue
        clear_stop(rid, where)
        log_event(id=rid, kind="stop-unknown", by=[w for _, w in where])
        n += 1
    return n


def drop_orphan_work(t=None):
    """Копии <ID> в work_root() без записи в servers.json и старше WORK_ORPHAN_AGE (mtime папки) — снять: процессы
    в ней погасить (reap), папку удалить. Так уходят копии прохода, упавшего посреди заявки, или после перезагрузки
    Mac. Зовёт только проход серверов под замком outside-serve, после своих заявок: своих копий в подготовке у него
    в этот момент нет. Метаданные worktree в клоне остаются, их помечает prunable сам git. → число снятых."""
    t = P.now() if t is None else t
    root = work_root()
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    live, n = set(servers()), 0
    for name in names:
        work = os.path.join(root, name)
        if name in live or not ID_RE.fullmatch(name):
            continue
        try:
            st = os.lstat(work)
        except OSError:
            continue
        if not stat.S_ISDIR(st.st_mode) or t - st.st_mtime < WORK_ORPHAN_AGE:
            continue
        reap(work)
        remove_work(None, work)
        log_event(id=name, kind="work-orphan", why="копия без сервера снята")
        n += 1
    return n


def _stale(t=None):
    """[(папка заявок, имя)] — итоги <ID>.result.json и брошенные <ID>.stop старше RESULT_TTL (по mtime, обычные
    файлы, не ссылки); у живого сервера его файлы не трогаем."""
    t = P.now() if t is None else t
    live, out = set(servers()), []
    for qdir, _ in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            for name in os.listdir(dfd):
                rid, _, ext = name.partition(".")
                if ext not in ("result.json", "stop") or not ID_RE.fullmatch(rid) or rid in live:
                    continue
                try:
                    st = os.lstat(name, dir_fd=dfd)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode) and t - st.st_mtime > RESULT_TTL:
                    out.append((qdir, name))
        finally:
            os.close(dfd)
    return out


def prune(t=None):
    """Уборка папок заявок (кэш окна и STATE/outside/queue): итоги и «стоп» старше суток — удалить. → число."""
    n = 0
    for qdir, name in _stale(t):
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            st = os.lstat(name, dir_fd=dfd)
            if stat.S_ISREG(st.st_mode):
                _unlink_in(dfd, name)
                n += 1
        except OSError:
            pass
        finally:
            os.close(dfd)
    if n:
        log_event(kind="prune", removed=n)
    return n


# --- заявки -------------------------------------------------------------------------------------------------------

def _req_kind(req):
    """Чей проход берёт заявку: serve — проход серверов, всё прочее (test, битые, чужие виды) — проход тестов."""
    return "serve" if isinstance(req, dict) and req.get("kind") == "serve" else "test"


def _parse(text):
    try:
        return json.loads(text) if text is not None else None
    except ValueError:
        return None


def _queued_ids(kinds=KINDS):
    """[(id, вид прохода)] заявок, лежащих в папках заявок, — без удаления (тику и сторожу)."""
    out = []
    for qdir, _ in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            for name in sorted(os.listdir(dfd)):
                if name.endswith(".req.json"):
                    k = _req_kind(_parse(_read_in(dfd, name)))
                    if k in kinds:
                        out.append((name[:-len(".req.json")], k))
        except OSError:
            pass
        finally:
            os.close(dfd)
    return out


def _gone(dfd, name):
    """Файла name в папке dfd больше нет (после unlink): заявку отдаём, только если она действительно снята."""
    try:
        os.stat(name, dir_fd=dfd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def requests(kinds=KINDS, limit=None, taken=None):
    """[(время, вид, qdir, окно, id, заявка)] по всем папкам — только заявки своих проходов (kinds): чужие остаются
    лежать (metis-0614: проход тестов не съедает заявки серверов и наоборот). Битые и подложенные — удаляются с итогом
    failed. Отдаются самые ранние limit заявок (все, если limit не задан) и только они снимаются с диска (metis-0716:
    убитый заход не теряет остальные); заявка, которую снять не удалось, не отдаётся — иначе проход крутился бы на ней.
    taken — {qdir: сколько заявок окна уже взято в этом заходе}: начальный номер круга между окнами (limit=1 иначе
    считал бы его с нуля при каждом вызове)."""
    found = []
    for qdir, window in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            for name in sorted(os.listdir(dfd)):
                if not name.endswith(".req.json"):
                    continue
                rid = name[:-len(".req.json")]
                text = _read_in(dfd, name)
                req = _parse(text)
                if _req_kind(req) not in kinds:
                    continue
                if not ID_RE.fullmatch(rid):
                    _unlink_in(dfd, name)
                    continue
                why = check_request(req, rid)
                if why:
                    _unlink_in(dfd, name)
                    save_result(qdir, rid, {"state": "failed", "why": why})
                    log_event(id=rid, kind="refused", window=window, why=why)
                    continue
                found.append((str(req.get("time") or ""), req["kind"], qdir, window, rid, req))
        finally:
            os.close(dfd)
    # порядок — по времени из id (его ставит CLI и проверяет ID_RE; req["time"] пишет клиент), по кругу между окнами:
    # за круг одна заявка от окна (metis-0716), чтобы окно не вставало первым своими временами и не держало очередь
    found.sort(key=lambda x: x[4])
    seen_n, ranked = dict(taken or {}), []
    for item in found:
        n = seen_n.get(item[2], 0)
        seen_n[item[2]] = n + 1
        ranked.append((n, item[4], item))
    ranked.sort(key=lambda x: x[:2])
    found = [x[2] for x in ranked]
    out = []
    for item in found[:limit]:
        dfd = _open_dir(item[2])
        if dfd is None:
            continue
        try:
            name = item[4] + ".req.json"
            _unlink_in(dfd, name)
            if _gone(dfd, name):
                out.append(item)
        finally:
            os.close(dfd)
    return out


FUTURE_SLACK = 60                   # заявка со временем позже now+60 с отклоняется (metis-0604)


def check_request(req, rid):
    if not isinstance(req, dict) or req.get("v") != 1 or req.get("id") != rid:
        return "заявка не в формате (v1, id = имя файла)"
    if req.get("kind") not in KINDS:
        return f"вид заявки «{req.get('kind')}» — только test или serve"
    if not isinstance(req.get("dir"), str) or not os.path.isabs(req["dir"]):
        return "в заявке нет папки"
    s = req.get("script")
    if s is not None and not (isinstance(s, str) and SCRIPT_RE.fullmatch(s)):
        return "имя скрипта не по образцу (буквы, цифры, : _ . -)"
    m = req.get("minutes", SERVE_MIN)
    if not isinstance(m, int) or isinstance(m, bool) or not 1 <= m <= SERVE_MAX:
        return f"срок сервера — от 1 до {SERVE_MAX} минут"
    w = req.get("wait", 0)
    if not isinstance(w, int) or isinstance(w, bool) or not 0 <= w <= WAIT_MAX:
        return f"ожидание заявки — от 0 до {WAIT_MAX} секунд"
    sha = req.get("sha")
    if sha is not None and not (isinstance(sha, str) and SHORT_SHA_RE.fullmatch(sha)):
        return "коммит заявки — от 7 до 40 знаков 0-9a-f"
    pin = req.get("pin")
    if pin is not None and (pin is not True or req["kind"] != "test" or sha is None):
        return "pin — только true, у заявки test с коммитом (test --sha)"
    app = req.get("app")
    if app is not None and not (isinstance(app, str) and APP_RE.fullmatch(app)):
        return "имя приложения не по образцу (имя пакета, @scope/имя, папка или «.»)"
    if req.get("time") is not None and (_epoch(req) or 0) > P.now() + FUTURE_SLACK:
        return "время заявки — позже, чем сейчас на часах прохода"
    return None


def resolve_dir(req_dir, window):
    """Папка заявки → (Repo — корень репозитория с проверенными клоном, common и gitdir, папки реестра окна) или
    (None, причина). Клон проверяется здесь один раз; run_test и run_serve берут его из Repo, а не из .git папки."""
    roots = registry(window)
    if not roots:
        return None, (f"окно «{window}» — не направление из реестра: проверки вне окна только для папок направлений"
                      if window else "в реестре (domains.json) нет папок")
    d = os.path.realpath(req_dir)
    if not inside(d, roots):
        return None, f"папка {d} — не из папок {'направления ' + window if window else 'реестра'}"
    clone, common, gitdir = trusted_clone(d)   # metis-0614: один раз; дальше git только через этот gitdir
    if not clone:
        return None, common
    d = checked(d, clone, common, gitdir)
    if not inside(clone, roots):
        return None, f"клон {clone} папки {d} — не из папок {'направления ' + window if window else 'реестра'}"
    why = unsafe_config(common)
    if why:
        return None, why
    if not remotes(d):
        return None, f"у репозитория {d} нет remote — это не копия репозитория владельца"
    return d, roots


def handle(qdir, window, rid, req):
    d, roots = resolve_dir(req["dir"], window)
    if d is None:
        log_event(id=rid, kind="refused", window=window, why=roots)
        return save_result(qdir, rid, {"state": "failed", "kind": req["kind"], "why": roots})
    if req["kind"] == "serve":
        return run_serve(rid, d, req, window, qdir)
    if req.get("pin"):   # test --sha (metis-0779): своя копия на коммите, а не HEAD папки
        return run_test_at(rid, d, req, window, qdir, registry(None) or roots)
    res = before_test(qdir, window, rid, req, d)   # metis-0726: устаревший head, дубли
    if res:
        return res
    return run_test(rid, d, req.get("script"), window, qdir, registry(None) or roots, record=not req.get("script"))


# --- перед стартом заявки test (metis-0726) ------------------------------------------------------------------------

def before_test(qdir, window, rid, req, d):
    """Перед прогоном заявки test в папке d: HEAD — бывший head открытого PR (stale_head) — итог failed без прогона
    (только проверка проекта: --script — для себя, не для шлюза); иначе ждущие заявки на ту же проверку снимаются
    (drop_dupes) и идёт прогон этой. Дерево не чистое или HEAD нет — None: отказ даст run_test."""
    sha, clean = head_state(d)
    if not sha or not clean:
        return None
    why = None if req.get("script") else stale_head(d, sha)
    if why:
        log_event(id=rid, kind="refused", window=window, dir=d, sha=sha, why=why)
        return save_result(qdir, rid, {"state": "failed", "kind": "test", "sha": sha, "why": why})
    drop_dupes(qdir, rid, req, d, sha, window)
    return None


def stale_head(d, sha, t=None):
    """sha — бывший head ещё открытого PR репозитория папки d по кэшу `autoclose fetch` (old_heads, autoclose.
    former_heads), а у PR сейчас другой head → причина отказа; кэша нет, он старше AUTO_HEADS_TTL, gh не ответил по
    репозиторию, sha там нет (коммит ещё не пушили) — None: прогон как раньше."""
    cache = _fresh_cache(t)
    errs = {str(r).lower() for r in cache.get("errors") or {}} if isinstance(cache.get("errors"), dict) else set()
    old = {str(r).lower(): v for r, v in (cache.get("old_heads") or {}).items() if isinstance(v, dict)} \
        if isinstance(cache.get("old_heads"), dict) else {}
    prs = {str(r).lower(): v for r, v in (cache.get("open_prs") or {}).items() if isinstance(v, list)} \
        if isinstance(cache.get("open_prs"), dict) else {}
    for repo in remotes(d):
        num = old.get(repo, {}).get(sha)
        if num is None or repo in errs:
            continue
        if any(isinstance(p, dict) and str(p.get("head") or "").lower() == sha for p in prs.get(repo, ())):
            continue   # sha сейчас head какого-то открытого PR (бывший head #1 стал head #2; force-push назад) — не устарел
        cur = next((str(p.get("head") or "").lower() for p in prs.get(repo, ())
                    if isinstance(p, dict) and p.get("number") == num), "")
        if cur and cur != sha:
            return (f"head устарел, подай на текущий: {sha[:12]} — бывший head PR #{num} {repo}, сейчас head "
                    f"{cur[:12]}; прогона не было")
    return None


def _queued_tests():
    """[(qdir, окно, id, заявка)] ждущих заявок test в формате (check_request) — без снятия с диска."""
    out = []
    for qdir, window in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            for name in sorted(os.listdir(dfd)):
                rid = name[:-len(".req.json")]
                if not name.endswith(".req.json") or not ID_RE.fullmatch(rid):
                    continue
                req = _parse(_read_in(dfd, name))
                if _req_kind(req) == "test" and not check_request(req, rid):
                    out.append((qdir, window, rid, req))
        except OSError:
            pass
        finally:
            os.close(dfd)
    return out


def drop_dupes(qdir, rid, req, d, sha, window=None):
    """Ждущие заявки на ту же проверку, что заявка rid (её папка d на HEAD sha): тот же --script и та же папка или
    папка того же репозитория на том же чистом HEAD. Тесты идут на HEAD папки во время прогона, поэтому они прогнали бы
    то же самое ещё раз (metis-0726: 21 заявка на 11 worktree). Каждая снимается с диска с итогом failed «дубль
    <rid>»; не снялась — остаётся. → число снятых."""
    repos, me, n = set(remotes(d)), os.path.realpath(d), 0
    for q2, w2, rid2, req2 in _queued_tests():
        if (q2, rid2) == (qdir, rid) or (req2.get("script") or None) != (req.get("script") or None) \
                or req2.get("pin"):   # test --sha идёт на своём коммите, а не на HEAD папки (metis-0779)
            continue
        d2, _roots = resolve_dir(req2["dir"], w2)
        if d2 is None or not (os.path.realpath(d2) == me
                              or head_state(d2) == (sha, True) and repos & set(remotes(d2))):
            continue
        dfd = _open_dir(q2)
        if dfd is None:
            continue
        try:
            _unlink_in(dfd, rid2 + ".req.json")
            gone = _gone(dfd, rid2 + ".req.json")
        finally:
            os.close(dfd)
        if gone:
            # status чужого окна заявку rid не видит — подсказки status нет, только где искать итог
            why = (f"дубль {rid}: та же проверка на {sha[:12]} идёт заявкой {rid} — итог у заявки {rid} в окне "
                   f"{window or '?'}")
            save_result(q2, rid2, {"state": "failed", "kind": "test", "sha": sha, "why": why, "dup": rid,
                                   "dup_window": window})
            log_event(id=rid2, kind="refused", window=w2, why=why)
            n += 1
    return n


# --- «принять» без тестов: тревога ----------------------------------------------------------------------------------------

def _epoch(rec):
    """Время записи или заявки в секундах: «…T…:%S%z» (журнал шлюза, заявки CLI) или «ГГГГ-ММ-ДД ЧЧ:ММ» (P.stamp,
    заявки до этой правки) — у второго точность минута, берётся её конец, чтобы не занижать ожидание; не разобрать — None."""
    t = str(rec.get("time"))
    try:
        return datetime.strptime(t, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        pass
    try:
        return datetime.strptime(t, "%Y-%m-%d %H:%M").timestamp() + 59
    except ValueError:
        return None


AUTO_HEADS_TTL = 3600               # с: кэш открытых PR старше часа — «gh не ответил»: отказ stale_head и тревога стоят (metis-0716)


def _fresh_cache(t=None):
    """Кэш `autoclose fetch` (STATE/autoclose-prs.json), если он не старше AUTO_HEADS_TTL; иначе {}."""
    t = P.now() if t is None else t
    cache = P.read_json(P.path("autoclose-prs.json"), {})
    fetched = cache.get("fetched") if isinstance(cache, dict) else None
    if isinstance(fetched, bool) or not isinstance(fetched, (int, float)) or not 0 <= t - fetched <= AUTO_HEADS_TTL:
        return {}
    return cache


def open_pr_heads(t=None):
    """{(repo, sha): номер PR} открытых PR по кэшу `autoclose fetch`; репозиторий, про который gh не ответил, кэш
    старше AUTO_HEADS_TTL или нечитаемый — пусто (для них тревоги нет)."""
    cache = _fresh_cache(t)
    by_repo = cache.get("open_prs")
    if not isinstance(by_repo, dict):
        return {}
    errs = cache.get("errors") if isinstance(cache.get("errors"), dict) else {}
    return {(str(r).lower(), str(p.get("head") or "").lower()): p.get("number")
            for r, prs in by_repo.items() if isinstance(prs, list) and r not in errs
            for p in prs if isinstance(p, dict)}


def overdue_accepts(recs=None, t=None):
    """[(repo, sha, номер PR | None)] — «принять» argus старше ALERT_AFTER и не старше AUTO_TTL, SHA — head открытого PR
    (по кэшу), записи tests на (repo, SHA) нет и тревога о нём ещё не подавалась (auto.json alerted). Тестов сам проход не
    запускает (решение владельца 03.11): заявку подаёт роль; это только срок, после которого дежурному пора знать."""
    t = P.now() if t is None else t
    heads = open_pr_heads(t)
    if not heads:
        return []                   # кэша нет — журнал шлюза не читается (тик зовёт это каждый проход)
    recs = read_records() if recs is None else recs
    alerted = P.read_json(root("auto.json"), {}).get("alerted") or {}
    tested = {(str(x).lower(), r["sha"].lower()) for r in recs if r.get("kind") == "tests" for x in r["repo"]}
    out, seen = [], set()
    for r in recs:
        by = r.get("by") if isinstance(r.get("by"), dict) else {}
        e = _epoch(r) if r.get("kind") == "accept" and by.get("agent_type") == "argus" else None
        if e is None or not ALERT_AFTER < t - e <= AUTO_TTL:
            continue
        for repo in r["repo"]:
            key = (str(repo).lower(), r["sha"].lower())
            if key in heads and key not in tested and key not in seen and f"{key[0]}@{key[1]}" not in alerted:
                seen.add(key)
                out.append((*key, heads[key] if heads[key] is not None else r.get("pr")))
    return out


def alert_overdue(t=None):
    """Тревога дежурному про каждый просроченный «принять» без tests (overdue_accepts), одна на (repo, sha): метка пишется
    до тревоги, повтор не шлётся. → число тревог."""
    t = P.now() if t is None else t
    todo = overdue_accepts(t=t)
    if not todo:
        return 0
    a = P.read_json(root("auto.json"), {})
    al = {k: v for k, v in (a.get("alerted") or {}).items() if isinstance(v, (int, float)) and 0 <= t - v <= 2 * AUTO_TTL}
    for repo, sha, pr in todo:
        al[f"{repo}@{sha}"] = t
    a["alerted"] = al
    os.makedirs(root(), mode=0o700, exist_ok=True)
    P.write_json(root("auto.json"), a)
    for repo, sha, pr in todo:
        P.alert(f"«принять» argus {repo}@{sha[:12]}" + (f" (PR #{pr})" if pr else "") + f" без записи tests дольше "
                f"{ALERT_AFTER // 3600} ч, head ещё открыт: тесты сами не идут — роль подаёт `pantheon outside test` "
                "на итоговый head", "pantheon-outside")
    return len(todo)


def prepare(d, rid, heavy=True, tick=None, timeout=TEST_TIMEOUT):
    """Свежий worktree без node_modules: зависимости ставит `<pm> install --frozen-lockfile` под тем же профилем.
    → код установки; None — ставить нечего (нет package.json или node_modules уже есть), -1 — не запустилась или
    дольше timeout. tick — сторож прохода серверов (см. wait_proc)."""
    pkg = _pkg(d)
    if not pkg or os.path.exists(os.path.join(d, "node_modules")):
        return None
    pm = package_manager(d, pkg)
    argv = [pm, "install", "--frozen-lockfile"] if pm in ("pnpm", "yarn") else [pm, "ci"]
    log, fd = new_log(rid)
    tmp = tempfile.mkdtemp(prefix="outside-")
    code = -1
    try:
        os.write(fd, f"$ {' '.join(argv)}  (зависимости свежего worktree)\n".encode())
        for attempt in range(PREPARE_SPAWN_TRIES):
            try:
                proc = subprocess.Popen(wrap(argv, write_profile(registry(None)), heavy=heavy), cwd=d,
                                        env=sandbox_env(tmp, "test"), stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
                                        start_new_session=True)
                break
            except OSError as e:
                # под нагрузкой fork/exec даёт временный отказ (EAGAIN, ETXTBSY): повтор, а не «код -1» (metis-0731)
                if e.errno not in SPAWN_RETRY_ERRNO or attempt == PREPARE_SPAWN_TRIES - 1:
                    raise
                time.sleep(1 + attempt)
        try:
            code = wait_proc(proc, timeout, tick)
        except subprocess.TimeoutExpired:
            kill_group(proc.pid)
            proc.wait()
    except (OSError, subprocess.SubprocessError) as e:
        with contextlib.suppress(OSError):   # причина в журнал: «код -1» без неё не разобрать (metis-0731)
            os.write(fd, f"установка не запустилась: {type(e).__name__}: {e}\n".encode())
    finally:
        os.close(fd)
        shutil.rmtree(tmp, ignore_errors=True)
    return code


# --- тик и проходы -----------------------------------------------------------------------------------------------

def _zombies(t=None):
    """Итоги, которые чинит recover_results, но заход ради них не шёл: running в runs/ (живого захода нет — замок
    outside-run свободен) и queued без .req.json старше LOST_AFTER. → число."""
    t = P.now() if t is None else t
    if P.locked("outside-run"):
        return 0                    # заход жив: running — его, queued ещё разбирается
    n = 0
    runs = root("runs")
    for name in os.listdir(runs) if os.path.isdir(runs) else ():
        rid = name[:-len(".json")]
        res = P.read_json(os.path.join(runs, name), {}) if name.endswith(".json") and ID_RE.fullmatch(rid) else {}
        if isinstance(res, dict) and res.get("kind") == "test" and res.get("state") == "running":
            n += 1
    for qdir, _ in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            names = os.listdir(dfd)
            for name in names:
                rid = name[:-len(".result.json")]
                if not name.endswith(".result.json") or not ID_RE.fullmatch(rid) or rid + ".req.json" in names:
                    continue
                res = _parse(_read_in(dfd, name, 1024 * 1024))
                try:
                    old = t - os.lstat(name, dir_fd=dfd).st_mtime > LOST_AFTER
                except OSError:
                    continue
                if old and isinstance(res, dict) and res.get("kind") == "test" and res.get("state") == "queued":
                    n += 1
        finally:
            os.close(dfd)
    return n


def pending_test():
    """Тику: дело проходу тестов — заявки test (и битые), старые итоги, «принять» без tests дольше ALERT_AFTER, сторож."""
    return (bool(_queued_ids(("test",))) or bool(_stale()) or bool(_zombies()) or bool(overdue_accepts())
            or bool(_watch_due()))


def pending_serve():
    """Тику: дело проходу серверов — заявки serve, живые серверы (сторож) или «стоп»."""
    return bool(_queued_ids(("serve",))) or bool(servers()) or bool(stop_requests())


def pending():
    return pending_test() or pending_serve()


def _in_claude():
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        err("pantheon outside run: только плановый проход, не из окна Claude Code")
        return True
    return False


MAX_ROUNDS = 100                    # кругов цикла захода тестов: предел на случай, когда очередь не разбирается


def run_test_queue():
    """Заход прохода тестов (metis-0716): явные заявки test, по одной — самая ранняя, снимается с диска только она, после
    каждого дела очередь читается заново (поданная за время прогона идёт следующей). Автопрогонов нет (решение владельца
    03.11): тесты идут только по заявке роли. Заход конечен: не больше MAX_ROUNDS кругов, взятая заявка не берётся
    второй раз."""
    seen, taken = set(), {}
    for _ in range(MAX_ROUNDS):
        reqs = [r for r in requests(("test",), limit=1, taken=taken) if (r[2], r[4]) not in seen]
        if not reqs:
            break
        for _t, _k, qdir, window, rid, req in reqs:
            seen.add((qdir, rid))
            taken[qdir] = taken.get(qdir, 0) + 1
            handle(qdir, window, rid, req)


LOST_AFTER = 300                    # с: итог queued без заявки старше этого — заявка потеряна (metis-0716)


def _result_running(qdir, rid):
    """В папке заявок qdir есть <rid>.result.json теста в состоянии running."""
    dfd = _open_dir(qdir)
    if dfd is None:
        return False
    try:
        res = _parse(_read_in(dfd, rid + ".result.json", 1024 * 1024))
    finally:
        os.close(dfd)
    return isinstance(res, dict) and res.get("kind") == "test" and res.get("state") == "running"


def recover_results(t=None):
    """Под замком outside-run (захода больше нет): итог теста queued без .req.json старше LOST_AFTER — failed «заявка
    потеряна»; running — failed «заход прерван», но только то, что сам заход записал в STATE/outside/runs/<ID>.json
    (файл из кэша окна роль может подложить; у старых записей без qdir итог ищется во всех папках заявок, где он
    тоже running). Итог пишется минимальным объектом из своих полей, чужое содержимое
    result.json не копируется. Serve не трогает: им ведёт свой проход. → число."""
    t = P.now() if t is None else t
    n = 0
    qdirs = {q for q, _ in queue_dirs()}
    for qdir in sorted(qdirs):
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            names = os.listdir(dfd)
            for name in names:
                rid = name[:-len(".result.json")]
                if not name.endswith(".result.json") or not ID_RE.fullmatch(rid):
                    continue
                res = _parse(_read_in(dfd, name, 1024 * 1024))
                if not isinstance(res, dict) or res.get("kind") != "test" or res.get("state") != "queued":
                    continue
                try:
                    old = t - os.lstat(name, dir_fd=dfd).st_mtime > LOST_AFTER
                except OSError:
                    continue
                if old and rid + ".req.json" not in names:
                    why = "заявка потеряна (заход прерван до запуска), подай заново"
                    save_result(qdir, rid, {"kind": "test", "state": "failed", "why": why})
                    log_event(id=rid, kind="recovered", why=why)
                    n += 1
        finally:
            os.close(dfd)
    runs = root("runs")
    for name in os.listdir(runs) if os.path.isdir(runs) else ():
        rid = name[:-len(".json")]
        res = P.read_json(os.path.join(runs, name), {}) if name.endswith(".json") and ID_RE.fullmatch(rid) else {}
        if isinstance(res, dict) and res.get("kind") == "test" and res.get("state") == "running":
            qd = res.get("qdir") if res.get("qdir") in qdirs else None
            targets = [qd] if qd else [q for q in sorted(qdirs) if _result_running(q, rid)]   # старые записи без qdir
            for q in targets or [None]:
                save_result(q, rid, {"kind": "test", "state": "failed", "why": "заход прерван, подай заново"})
            log_event(id=rid, kind="recovered", why="заход прерван")
            n += 1
    return n


WATCH_RUNNING = TEST_TIMEOUT + 1800   # с: running дольше — заход завис; не меньше предела прогона TEST_TIMEOUT (metis-0723)
WATCH_QUEUED = 4 * 3600               # с: queued с лежащей заявкой дольше — очередь стоит, тревога без снятия (metis-0723)


def _run_holder():
    """Номер процесса, держащего замок outside-run (lsof по файлу замка); нет или не определить → None."""
    try:
        out = subprocess.run([LSOF, "-t", P.path("locks", "outside-run.lock")], capture_output=True, text=True,
                             timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pids = [int(x) for x in out.split() if x.isdigit() and int(x) != os.getpid()]
    return pids[0] if len(pids) == 1 else None


def _mark(rid):
    """Метка runs/<ID>.alerted: тревога о заявке уже была. → True, если метку поставили сейчас (первая тревога)."""
    os.makedirs(root("runs"), mode=0o700, exist_ok=True)
    try:
        os.close(os.open(root("runs", rid + ".alerted"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    except OSError:
        return False
    return True


def _watch_due(t=None):
    """[(вид, папка заявок, id)] того, что сторож должен разобрать: running теста в runs/ старше WATCH_RUNNING (по mtime
    записи захода) и queued с лежащей .req.json старше WATCH_QUEUED, о котором ещё не было тревоги."""
    t = P.now() if t is None else t
    out = []
    runs = root("runs")
    for name in os.listdir(runs) if os.path.isdir(runs) else ():
        rid = name[:-len(".json")]
        if not name.endswith(".json") or not ID_RE.fullmatch(rid):
            continue
        res = P.read_json(os.path.join(runs, name), {})
        try:
            old = t - os.lstat(os.path.join(runs, name)).st_mtime > WATCH_RUNNING
        except OSError:
            continue
        if (old and isinstance(res, dict) and res.get("kind") == "test" and res.get("state") == "running"
                and not os.path.lexists(root("runs", rid + ".alerted"))):
            out.append(("running", res.get("qdir"), rid))
    for qdir, _ in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            names = os.listdir(dfd)
            for name in names:
                rid = name[:-len(".result.json")]
                if not name.endswith(".result.json") or not ID_RE.fullmatch(rid) or rid + ".req.json" not in names:
                    continue
                if os.path.lexists(root("runs", rid + ".alerted")):
                    continue
                res = _parse(_read_in(dfd, name, 1024 * 1024))
                try:
                    old = t - os.lstat(name, dir_fd=dfd).st_mtime > WATCH_QUEUED
                except OSError:
                    continue
                if old and isinstance(res, dict) and res.get("kind") == "test" and res.get("state") == "queued":
                    out.append(("queued", qdir, rid))
        finally:
            os.close(dfd)
    return out


def watchdog(t=None):
    """Сторож заявок test (metis-0723); зовётся до замка, чтобы видеть и живой заход. running дольше WATCH_RUNNING при
    живом заходе: заход (SIGKILL — итога за собой он не запишет) и его группы процессов гаснут, итог failed «сторож:
    дольше N»; замок держит не определить — только тревога. queued с лежащей заявкой дольше WATCH_QUEUED: одна тревога
    на заявку (метка runs/<ID>.alerted), без снятия. Захода нет — running чинит recover_results. → число."""
    t = P.now() if t is None else t
    n = 0
    for kind, qdir, rid in _watch_due(t):
        if kind == "queued":
            why = f"проверка заявок: заявка в очереди дольше {WATCH_QUEUED // 3600} ч, очередь стоит"
            if _mark(rid):
                P.alert(f"outside {rid}: {why} (pantheon outside status {rid})", who="outside")
                log_event(id=rid, kind="watchdog", why=why)
                n += 1
            continue
        if not P.locked("outside-run"):
            continue                # захода нет — recover_results
        holder = _run_holder()
        if holder is None:
            if _mark(rid):
                P.alert(f"outside {rid}: running дольше {WATCH_RUNNING // 60} мин, заход не определить — снять "
                        f"вручную", who="outside")
            continue
        why = f"проверка заявок: дольше {WATCH_RUNNING // 60} мин — снято"
        table = ps_table()
        kids = [p for p, (pp, g, _r) in table.items() if pp == holder and g == p]
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(holder, signal.SIGKILL)
        for k in kids:
            kill_group(k)
        qdirs = {q for q, _ in queue_dirs()}
        targets = [qdir] if qdir in qdirs else [q for q in sorted(qdirs) if _result_running(q, rid)]
        for q in targets or [None]:
            save_result(q, rid, {"kind": "test", "state": "failed", "why": why})
        log_event(id=rid, kind="watchdog", why=why)
        P.alert(f"outside {rid}: {why}", who="outside")
        n += 1
    return n


def cmd_run():
    """Проход тестов (замок outside-run): серверы не смотрит — их ведёт свой проход (metis-0614)."""
    if _in_claude():
        return 2
    watchdog()      # до замка: живой заход с зависшим running виден только отсюда (metis-0723)
    with P.lock("outside-run", block=False) as got:
        if not got:
            return 0
        recover_results()
        drop_test_work()   # копии test --sha упавшего прохода (metis-0779): под замком прогона на них нет
        alert_overdue()
        run_test_queue()
        prune()
    return 0


def serve_round(t=None):
    """Один круг прохода серверов: сторож, заявки serve, снова сторож, уборка брошенных «стопов» и копий."""
    sweep(t)
    for _t, _k, qdir, window, rid, req in requests(("serve",)):
        where = stop_requests().get(rid)
        age = P.now() - (_epoch(req) or P.now())
        if where:
            clear_stop(rid, where)
            log_event(id=rid, kind="stop", why="отменена до запуска", by=[w for _, w in where])
            save_result(qdir, rid, {"state": "stopped", "kind": "serve", "why": "заявка «стоп» до запуска — отменена"})
        elif age > REQ_TTL:
            why = f"заявка пролежала {int(age // 60)} мин (дольше {REQ_TTL // 60}) — не запускаю, подай заново"
            log_event(id=rid, kind="refused", window=window, why=why)
            save_result(qdir, rid, {"state": "failed", "kind": "serve", "why": why})
        else:
            try:
                handle(qdir, window, rid, req)
            except Exception as e:  # noqa: BLE001 — сбой до копии (папка, коммит, журнал): итог failed, круг идёт
                why = f"сбой прохода: {type(e).__name__}: {e}"
                log_event(id=rid, kind="serve-error", window=window, why=why)
                save_result(qdir, rid, {"state": "failed", "kind": "serve", "why": why})
        sweep()
    drop_orphan_stops()
    drop_orphan_work()


def cmd_run_serve(once=False):
    """Проход серверов (замок outside-serve): живёт сторожем, пока есть серверы или заявки serve, круг — каждые
    SWEEP_EVERY с, не дольше RESIDENT_MAX (дальше — следующий тик с новой версией кода)."""
    if _in_claude():
        return 2
    with P.lock("outside-serve", block=False) as got:
        if not got:
            return 0
        t0 = time.monotonic()
        while True:
            serve_round()
            if once or time.monotonic() - t0 >= RESIDENT_MAX:
                break
            if not servers() and not _queued_ids(("serve",)):
                break
            time.sleep(SWEEP_EVERY)
    return 0


# --- команды роли -------------------------------------------------------------------------------------------------

def _flags(args, allowed):
    out, i = {}, 0
    while i < len(args):
        a = args[i]
        if a not in allowed or i + 1 >= len(args):
            return None
        out[a] = args[i + 1]
        i += 2
    return out


def cmd_request(kind, args):
    f = _flags(args, {"--script", "--wait", "--sha"} | ({"--minutes", "--app"} if kind == "serve" else set()))
    if f is None:
        err(f"pantheon outside: {USAGE}")
        return 2
    try:
        wait = max(0, min(int(f.get("--wait", 0)), WAIT_MAX))
        minutes = int(f.get("--minutes", SERVE_MIN))
    except ValueError:
        err("pantheon outside: --wait и --minutes — целые числа")
        return 2
    d = toplevel(os.getcwd())
    if not d:
        err("pantheon outside: папка не репозиторий git — запускай из корня копии проекта")
        return 2
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    req = {"v": 1, "id": rid, "kind": kind, "dir": d, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "by": " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "").split())[:40]}
    if f.get("--script"):
        req["script"] = f["--script"]
    if kind == "test":   # metis-0706: коммит при заявке — по нему видно, что такой же тест уже ждёт или идёт
        if f.get("--sha"):   # metis-0779: тест на этом коммите в своей копии прохода, полный SHA — здесь же
            ref = f["--sha"].lower()
            head = (git(d, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}") or "").strip().lower() \
                if SHORT_SHA_RE.fullmatch(ref) else ""
            if not SHA_RE.fullmatch(head):
                err(f"pantheon outside: --sha {f['--sha']} — не коммит этой копии (7–40 знаков 0-9a-f; "
                    "нет — сделай git fetch)")
                return 2
            req["pin"] = True
        else:
            head, _clean = head_state(d)
        if head:
            req["sha"] = head
            prev = live_test(d, head, f.get("--script"), pin=bool(req.get("pin")))
            if prev:   # тот же head, та же папка, прежняя заявка жива — не плодить дубль: её ID и ждать её
                print(f"заявка {prev[1]}: тот же коммит {head[:12]} в {d} уже в очереди или идёт — новой заявки нет")
                if not wait:
                    print(f"итог: pantheon outside status {prev[1]}")
                    return 0
                return wait_result(prev[0], prev[1], wait)
    if kind == "serve":
        req["minutes"] = minutes
        req["wait"] = wait
        if f.get("--app"):
            req["app"] = f["--app"]
        if f.get("--sha"):
            req["sha"] = f["--sha"].lower()
        else:   # коммит фиксируется при заявке: копия сервера — на нём, что бы ни случилось с папкой потом
            head, clean = head_state(d)
            if not head:
                err("pantheon outside: в папке нет коммитов — серверу не на чем стоять")
                return 2
            req["sha"] = head
            if not clean:
                req["dirty"] = True
    why = check_request(req, rid)
    if why:
        err(f"pantheon outside: {why}")
        return 2
    q = own_qdir()
    try:
        dfd = _open_dir(q, create=True)
        if dfd is None:
            raise OSError(f"{q} — не папка")
        try:
            _write_in(dfd, rid + ".req.json", json.dumps(req, ensure_ascii=False))
            with contextlib.suppress(OSError):   # состояние queued — видно в status до прохода
                _write_in(dfd, rid + ".result.json", json.dumps(
                    {"id": rid, "state": "queued", "kind": kind, "src": d, "updated": P.stamp(),
                     **{k: req[k] for k in ("sha", "app", "script", "pin") if req.get(k)}}, ensure_ascii=False,
                    indent=1))
        finally:
            os.close(dfd)
    except OSError as e:
        err(f"pantheon outside: заявку не записать ({e})")
        return 1
    at = f" на {req['sha'][:12]}" if req.get("sha") else ""
    print(f"заявка {rid}: {kind} в {d}{at} — её исполнит плановый проход (раз в минуту)")
    if req.get("dirty"):
        print("в папке есть незакоммиченные правки — сервер поднимется на коммите, без них")
    if req.get("pin"):
        print("тест — в своей копии прохода на этом коммите; папка и её дерево не нужны")
    if not wait:
        print(f"итог: pantheon outside status {rid}")
        return 0
    return wait_result(q, rid, wait)


def live_test(d, sha, script=None, pin=False):
    """(папка заявок, ID) живой заявки test на этот head и эту папку или None (--sha и обычная на одном SHA не сцеплены,
    metis-0796: у pin-заявки свой прогон в копии, у обычной — по дереву папки с её правками): в очереди (лежит .req.json) или идёт
    (итог running свежее TEST_TIMEOUT). Смотрит все папки заявок; недоступную пропускает."""
    d = os.path.realpath(d)
    now = P.now()
    for qdir, _w in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            names = sorted(os.listdir(dfd), reverse=True)
            for name in names:
                if not name.endswith(".result.json"):
                    continue
                rid = name[:-len(".result.json")]
                try:
                    res = json.loads(_read_in(dfd, name, 1024 * 1024) or "")
                except ValueError:
                    continue
                if not isinstance(res, dict) or res.get("kind") != "test" or res.get("sha") != sha \
                        or res.get("script") != script or bool(res.get("pin")) != pin:
                    continue
                where = res.get("src") or res.get("dir")
                if not isinstance(where, str) or os.path.realpath(where) != d:
                    continue
                if res.get("state") == "queued" and (rid + ".req.json") in names:
                    return qdir, rid
                if res.get("state") == "running":
                    t = _epoch({"time": res.get("updated")})
                    if t is not None and now - t < TEST_TIMEOUT + 300:
                        return qdir, rid
        except OSError:
            continue
        finally:
            os.close(dfd)
    return None


def load_result(q, rid):
    dfd = _open_dir(q)
    if dfd is None:
        return None
    try:
        text = _read_in(dfd, rid + ".result.json", 1024 * 1024)
    finally:
        os.close(dfd)
    try:
        res = json.loads(text) if text else None
    except ValueError:
        return None
    return res if isinstance(res, dict) else None


def show(res):
    print(f"{res.get('id')}: {res.get('state')}" + (f", код {res['code']}" if res.get("code") is not None else "")
          + (f", {res['sha'][:12]}" if res.get("sha") else "") + (f" — {res['cmd']}" if res.get("cmd") else ""))
    if res.get("kind") == "serve" and (res.get("src") or res.get("dir")):
        print(f"копия: {res.get('dir') or '—'}" + (f" (из {res['src']})" if res.get("src") else "")
              + (f", приложение {res['app']}" if res.get("app") else ""))
    if res.get("url"):
        print(f"адрес: {res['url']} до {res.get('until')} (погасить раньше: pantheon outside stop {res['id']})")
    if res.get("rerun_of"):
        print(f"дозапуск после красного полного набора {res['rerun_of']}: {', '.join(res.get('files') or [])}")
    if res.get("full_why"):
        print(f"полный набор, а не дозапуск: {res['full_why']}")
    if res.get("record"):
        print("запись tests для шлюза слияния сделана")
    if res.get("why"):
        print(f"причина: {res['why']}")
    if res.get("note"):
        print(res["note"])
    if res.get("tail"):
        print("--- хвост журнала ---\n" + res["tail"])


def result_code(res):
    if res.get("state") == "serving":
        return 0
    if res.get("state") == "failed" and res.get("dup"):
        return 75   # снятый дубль: своего итога нет, он у первой заявки (в этом окне его не прочесть) — «итога ещё нет»
    if res.get("state") == "failed" and res.get("busy"):
        return 75   # два сервера уже идут или давление памяти — отказ «занято», как истёкшее ожидание
    if res.get("state") == "done" and isinstance(res.get("code"), int) and not res.get("why"):
        return res["code"]
    return 1


def wait_result(q, rid, wait):
    deadline = time.monotonic() + wait
    res = None
    while time.monotonic() < deadline:
        res = load_result(q, rid)
        if res and res.get("state") in FINAL:
            show(res)
            return result_code(res)
        time.sleep(2)
    print(f"итога за {wait} с нет (состояние: {(res or {}).get('state', 'в очереди')}) — pantheon outside status {rid}")
    return 75


def cmd_status(args):
    q = own_qdir()
    if args:
        if len(args) != 1 or not ID_RE.fullmatch(args[0]):
            err("pantheon outside status [ID]")
            return 2
        res = load_result(q, args[0]) or (P.read_json(root("runs", args[0] + ".json"), None)
                                           if q == root("queue") else None)
        if not res:
            print(f"{args[0]}: итога нет (заявка ещё в очереди или не из этого окна)")
            return 1
        show(res)
        return 0
    try:
        names = sorted((n for n in os.listdir(q) if n.endswith(".result.json")), reverse=True)[:10]
    except OSError:
        names = []
    if q == root("queue"):
        try:
            names = sorted((n[:-5] + ".result.json" for n in os.listdir(root("runs")) if n.endswith(".json")),
                           reverse=True)[:10]
        except OSError:
            pass
    if not names:
        print("итогов нет")
    for n in names:
        rid = n[:-len(".result.json")]
        res = load_result(q, rid) or P.read_json(root("runs", rid + ".json"), {})
        print(f"{rid}  {res.get('state', '?'):<8} {res.get('kind', '')}  "
              + (res.get("url") or (f"код {res['code']}" if res.get("code") is not None else res.get("why", ""))))
    return 0


def _known(q, rid):
    """Что известно о заявке rid из этого окна: свой итог, итог прохода в STATE, запись сервера, лежащая заявка."""
    res = load_result(q, rid) or P.read_json(root("runs", rid + ".json"), None)
    return (res if isinstance(res, dict) else None), rid in servers(), rid in {r for r, _ in _queued_ids()}


def _cancel_queued_test(q, rid):
    """Тест, ещё лежащий заявкой в своей папке q, снимается: заявка удалена, итог stopped (metis-0706). True — снят;
    False — не тест, не здесь или проход уже взял (тогда он идёт до конца)."""
    dfd = _open_dir(q)
    if dfd is None:
        return False
    try:
        req = _parse(_read_in(dfd, rid + ".req.json"))
        if not isinstance(req, dict) or req.get("kind") != "test" or not _take_in(dfd, rid + ".req.json"):
            return False
    finally:
        os.close(dfd)
    save_result(q, rid, {"state": "stopped", "kind": "test", "why": "отменена до запуска",
                         **{k: req[k] for k in ("sha",) if req.get(k)}})
    log_event(id=rid, kind="stop", why="отменена до запуска")
    print(f"{rid}: тест был в очереди — снят, итог stopped")
    return True


def cmd_stop(args):
    if not args or not ID_RE.fullmatch(args[0]):
        err("pantheon outside stop ID [--wait С]")
        return 2
    rid, f = args[0], _flags(args[1:], {"--wait"})
    try:
        wait = max(0, min(int((f or {}).get("--wait", STOP_WAIT)), WAIT_MAX)) if f is not None else None
    except ValueError:
        wait = None
    if wait is None:
        err("pantheon outside stop ID [--wait С]")
        return 2
    q = own_qdir()
    res, live, queued = _known(q, rid)
    if not res and not live and not queued:
        print(f"{rid}: нет такой заявки — ни итога, ни сервера, ни заявки в очереди (status покажет свои)")
        return 1
    if queued and _cancel_queued_test(q, rid):
        return 0
    if (res or {}).get("kind") == "test" and not live and res.get("state") != "stopped":
        print(f"{rid}: это тесты, а не сервер — они идут до конца (не дольше {TEST_TIMEOUT // 60} мин)")
        return 1
    if res and res.get("state") in ("stopped", "failed", "done") and not live and not queued:
        print(f"{rid}: уже {res['state']}" + (f" — {res['why']}" if res.get("why") else ""))
        return 0
    dfd = _open_dir(q, create=True)
    if dfd is None:
        err(f"pantheon outside: {q} — не папка")
        return 1
    try:
        _write_in(dfd, rid + ".stop", "")
    except OSError as e:
        err(f"pantheon outside: «стоп» не записать ({e})")
        return 1
    finally:
        os.close(dfd)
    if not wait:
        print(f"{rid}: «стоп» записан — сервер погасит проход серверов (до {SWEEP_EVERY} с, если он идёт, иначе до "
              f"минуты); итог: pantheon outside status {rid}")
        return 0
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(1)
        res, live, _q = _known(q, rid)
        if res and res.get("state") in ("stopped", "failed") and not live:
            show(res)
            return 0
    print(f"{rid}: за {wait} с не погас (состояние: {(res or {}).get('state', '?')}) — «стоп» лежит, проход серверов "
          f"погасит его на следующем круге; итог: pantheon outside status {rid}")
    return 75


def main(rest):
    sub = rest[0] if rest else ""
    if sub in KINDS:
        return cmd_request(sub, rest[1:])
    if sub == "status":
        return cmd_status(rest[1:])
    if sub == "stop":
        return cmd_stop(rest[1:])
    if sub == "run" and len(rest) == 1:
        return cmd_run()
    if sub == "run" and rest[1:] == ["--serve"]:
        return cmd_run_serve()
    err(f"pantheon outside: {USAGE}")
    return 2
