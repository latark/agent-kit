# agent-kit

Маркетплейс плагинов Claude Code для системы агентов «Пантеон». Общие части собираются здесь сразу,
поэтому на другой установке работает то же, что у владельца; роли армии, хранилище знаний и ключи у каждого свои.
Приватный репозиторий `latark/agent-kit`; ведёт его metis-pantheon (изменения — после «да» владельца).

| Плагин | Что делает | Состояние |
| --- | --- | --- |
| `guard` | Правила, которые Claude Code проверяет сам: dev-server, attribution, cdp, tg-secret, nextjs, domain, pantheon-acl, protect-config, private, cdp-role, push, terminal; модель угроз и режимы — `plugins/guard/README.md` | работает с 14.10 (шаг 0.4); управляемые настройки — шаг 0.6, ставятся через `sudo` |
| `pantheon` | Планировщик `pantheon-tick` (launchd, раз в 60 с), команда `pantheon`, копия `~/ai/pantheon-view` для Obsidian, задачи и доска владельца, коммит `~/ai/pantheon`, настройки окон ролей с песочницей и строгим guard, сверка карты решений; хуки контекста (подсказка «пора очистить», продолжение после `/clear`, файл состояния после сжатия) и журнал ваших слов owner-log; запуск сессий (`pantheon start`, `wake`), сборка ролей (`pantheon roles build`), заранее разрешённое (`pantheon approve`), обёртка `heavy`, Stop-хук разработчика; дежурный без модели (`pantheon watch`: сессии, swap, worktree, версия Claude Code, паузы, самозапуск по вашим решениям, журналы ваших слов), пересмотры, остановка и пауза, технический перезапуск, продолжение сессий `claude respawn` с текстом через хук | работает с 14.10 (шаг 0.4); хуки — с шага 1.1; роли и запуск — с шага 1.2; дежурный и перезапуск — с 0.10.0 (шаг 1.4) |
| `project-tools` | Инструменты проекта по карте стеков `stacks.json`: MCP-серверы (next-devtools, chrome-devtools, shadcn) — в `.mcp.json` проекта с одобрением, плагины (Supabase) — в настройки проекта, блок для Codex; команда `project-tools` (check, apply, skip, outdated), навык, подсказка при старте сессии; отпечатки одобренных записей — предупреждение о подмене после `git pull` | с 14.10 (шаг 0.7) |

## Где что лежит

- `plugins/guard/hooks/guard.py` — все правила; шапка файла перечисляет их и выключатель `GUARD_OFF`.
  Данные: `~/.local/state/pantheon/domains.json` (собирает `pantheon domains build` из
  `~/ai/pantheon/directions.toml`) и `~/.claude/pantheon/policy.toml` — привилегии (образец —
  `plugins/guard/policy.example.toml`), правит только metis-pantheon.
- `plugins/pantheon/lib/pantheon.py` — планировщик и команда; `pantheon help` — список команд.
  Задачи — `~/ai/pantheon/schedule.toml`, метки и журналы запусков — `~/.local/state/pantheon/` (свои у каждого Mac).
- Требуется Python 3.11+ (`tomllib`). Системный `/usr/bin/python3` на macOS — 3.9, он не подходит; `bin/pantheon` и
  `bin/pantheon-tick` сами ищут 3.11+ (`lib/find-python.sh`): `PANTHEON_PYTHON`, затем `python = "…"` из
  `STATE/config.toml` (его пишет `pantheon-setup`), затем `python3` из PATH, `python3.14`…`3.11`, Homebrew, python.org.
  Не нашли — строка «нужен Python 3.11+» и код 1, у планового прохода ещё строка в `alerts.md` не чаще раза в сутки. Новой установке
  Python ставит `pantheon-setup` (uv, Python 3.14); вручную — `brew install python@3.14`. Хуки guard идут на `python3`
  из PATH и работают на любом Python 3.9+. `pantheon infra-check` показывает строку «Python установки».
- Установка для нового человека (macOS): `plugins/pantheon/bin/pantheon-setup` из клона agent-kit, одной командой.
  Загрузчик на bash до всего проверяет, что это macOS, что `~/ai/pantheon` (`PANTHEON_HOME`) нет или он пуст, что `claude`
  на PATH и клон — репозиторий; при отказе ничего не ставит. Дальше ставит uv (`UV_NO_MODIFY_PATH=1`, профили
  оболочки не правит) и Python 3.14, уже стоящие Python не трогает, и передаёт дело `lib/setup.py`. Он идёт по шагам,
  у каждого итог «ок / пропуск / не вышло»: путь Python в `config.toml`; маркетплейс и плагины guard, pantheon,
  project-tools; пустой `~/ai/pantheon` из `plugins/pantheon/template/pantheon/` с `git init`; `pantheon install`;
  `pantheon roles build`; вход git в GitHub через gh (`gh auth setup-git` — только после явного «да»);
  terminal-notifier; проверка личных следов (`scripts/check-traces.py` по файлам установщика и собранным ролям, маркеры —
  `--markers ФАЙЛ` или `PANTHEON_TRACE_MARKERS`, нет файла — пропуск); Codex (`--codex`, `--no-codex`, без флагов —
  вопрос, по умолчанию нет). `pantheon-setup --add codex` — только шаг Codex на готовой установке. К системе
  `setup.py` ходит через `lib/platform_macos.py` (Homebrew, launchd, sandbox-exec, Связка ключей, текст про
  уведомления). Тест — `plugins/pantheon/tests/test_setup.py`, все внешние программы в нём — заглушки.
- Настройки человека — `STATE/config.toml` (`~/.local/state/pantheon/`, свои у каждого Mac): `python`, таблица
  `[executors] set` (Claude всегда, Codex — дополнение) и `[codex]` (состояние проверки). Читает и пишет только
  `lib/pconfig.py` (`load`, `update`).
- Исполнители (`lib/executors.py`): `pantheon executors` — набор и состояние, `check` — проверка Codex (на PATH, вход,
  hello-проба), `--add codex`, `--remove codex`, `pick <id задачи>` — кто пишет задачу. `pantheon exec codex <папка
  worktree> <файл поручения>` — запуск Codex в worktree; коды выхода: 0 — коммит есть, 1 — отказ (ошибка хода,
  защищённые пути, нет изменений), 2 — неверный вызов или worktree не чистый (игнорируемое не в счёт), 3 — Codex
  недоступен (задачу на dev-*), 4 — занят.
- Лёгкий плановый проход: `pantheon` идёт модулем через `lib/run.py` (байт-код в `lib/__pycache__`, при read-only папке молча
  без кэша), `--help` ~34 мс вместо ~62. Задачи `view --quiet`, `board`, `sync-answers`, `agents` плановый проход пропускает, если
  их входы (отпечаток stat, таблица входов — `TICK_SKIP` в `lib/pantheon.py`) не менялись с прошлого удачного прогона;
  не реже раза в 15 минут они идут в любом случае, ручной вызов и `run-job` — всегда. Пропуски — `tick-skipped.json`.
- Размер песочницы окна (с 0.11.17): Seatbelt не собирает профиль больше 64 КБ, и тогда Bash окна не запускается
  совсем. Поэтому `sandbox_build` считает байты путей песочницы окна. Выше предела — 48 КБ, переменная
  `PANTHEON_SANDBOX_LIMIT` — окно не пересобирается: остаётся прежний файл, приходит одна тревога «песочница окна …».
  Пританей закрывает чужие папки в `/tmp/claude-<uid>` и `~/.claude/projects` шаблонами по префиксам, а не перечислением,
  поэтому мусор тестов список не раздувает. Корень `/tmp/claude-<uid>` и папки в нём на `tmp` открыты: это `$TMPDIR`
  песочницы, в нём временные файлы heredoc и mktemp и временные папки `mktemp -d` и `tempfile`.
- Окна ролей (с 0.11.14, `sandbox_build`): мастерской и Пританею правила слияния нет. Окну координатора направления
  `allow` для `gh pr merge` не даётся совсем (`COORDINATOR_ALLOW` пуст, metis-0137): слияние без вопроса пускает только
  правило autoMode «Pantheon Gated Merge» (шлюз слияния, ниже), а каждое слияние дополнительно проверяет guard: главная
  сессия domain-coordinator или лид её направления (`hephaestus-*`, `apollo-*`; metis-0054), свои папки, без `--admin`
  и `--auto`.
  Проверка проектных allow (metis-0137): `.claude/settings.json` проекта сливается с `--settings` окна, а правило allow
  срабатывает раньше классификатора auto. Поэтому `Bash(gh *)` в `.claude/settings.json` или `settings.local.json`
  папки запуска возвращало бы слияние `--admin`/`--auto` мимо шлюза. `sandbox_build` проверяет оба файла: правило
  `Bash`, `Bash(*)` или `Bash(<шаблон>)`, где начало шаблона до первой `*` — начало `gh pr merge` (`gh *`, `gh pr *`,
  `g*`) или само начинается с `gh pr merge` (`gh pr merge --admin *`, точное `gh pr merge 32`), а также старая форма
  `:*`. Пробелы схлопываются, регистр не важен, ведущие `VAR=значение` снимаются, путь к программе сводится к имени
  (`/opt/homebrew/bin/gh *` — это `gh *`). Обёртки, пускающие любую команду, снимаются с начала шаблона, и остаток
  проверяется так же: `env` с флагами и `VAR=`, `command`, `xargs` с флагами, `eval`, `bash|sh|zsh -c` с кавычкой.
  Поэтому ловятся `env *`, `/usr/bin/env -i *`, `bash -c *`, `bash *`, `command /opt/homebrew/bin/gh *`. Обёртка без
  `*` и без команды после неё безопасна: `env`, `command -v gh`; запуск своего скрипта `bash ./scripts/test.sh *` —
  тоже. Не ловятся свои скрипты-обёртки (`./run.sh *`), `sudo`, `nohup`, `timeout`, `exec gh *`, `time gh *`,
  `nice gh *`: граница — песочница и guard.
  При таком правиле окно направления не собирается, прежние файлы
  окна и запуска (`settings/run/<имя>.json`, его берёт `claude respawn`) убираются, в stderr строка с файлом и
  правилом (убрать правило или сузить до `gh pr view *`, `gh pr checks *`), плюс тревога. `pantheon check` и
  `pantheon direction check` показывают то же предупреждение по каждому направлению. Пританей и мастерская не проверяются.
  Без файла окна сессию не поднимает никто: `pantheon start`, `wake`, дежурный и техперезапуск (respawn, `--resume`,
  свежий старт) отказывают с тревогой — одной на причину; `--resume` без `--settings` не запускается никогда.
  Правило перепроверяется и при каждом подъёме сессии, и в `check --quiet`, а не только при сборке: `--if-changed`
  сравнивает время изменения файлов, и allow со старым mtime (`cp -p`, `rsync -a`, распаковка tar) сборку не запускает.
  Нашлось правило — оба файла окна убираются и подъём идёт тем же путём «нет окна»; respawn и `--resume` к тому же
  проверяют папку сессии (`cwd` из `claude agents`), если она не папка запуска.
  Claude Code перечитывает настройки на ходу, поэтому живую сессию с таким правилом останавливает плановый проход
  (`domains build --if-changed` и `check --quiet`): `claude stop` и тревога. Ручной `domains build` её не трогает —
  его зовут и тесты с настоящим `claude` в PATH.
  Мимо песочницы gh (в ней не работает) — только чтение: `gh pr view|checks|diff|list`, `gh run view|list|watch`,
  `gh repo view`, `gh auth status`; `gh api`, `gh issue` и `gh run cancel|rerun|delete` в песочнице падают.
  `gh pr create|merge` и сетевой git (push, fetch, pull) — у окна каждого направления; мастерской — только сетевой
  git и только при SSH-remote; у Пританея ничего из этого нет (metis-0064).
  С 0.11.26 (metis-0098) окнам координаторов, Метиды в их числе, сборка кладёт и `autoMode.allow` — исключения
  классификатора auto: `"$defaults"` (встроенные исключения остаются), «Pantheon Gated Merge», «Pantheon Lead
  Delivery» и «Pantheon Review Record» (`coordinator_auto_allow`).
  Lead Delivery (с 0.11.38, metis-0215) разрешает лиду сдать работу по поручению координатора без отказа Auto-Mode
  Bypass: push рабочей ветки в `origin`, запуск ревьюера `argus`, `pantheon night report` и `gh pr create` для этой
  ветки. Push не покрывает `main`, `master` и ветку по умолчанию, а также `--force`, `-f`, `--force-with-lease`,
  `+refspec`, удаление ветки, другие remote, `cd` и цепочки команд. Репозитории — только из `[merge_repos]`
  направления; без такой записи правила сдачи нет, как и правила слияния. Слияние это правило не покрывает: его
  пускает только Gated Merge.
  Gated Merge описывает ровно форму, которую пускает шлюз слияния guard:
  `gh pr merge <N> -R|--repo <owner/repo> --match-head-commit <sha>`, а последующие `gh pr view` или `git fetch`
  классификатор считает обычными. `--admin`, `--auto`, `gh api` и ядро защит (`plugins/guard/`,
  `plugins/pantheon/roles/`, `plugins/pantheon/lib/window_rules.py`, `.claude-plugin/marketplace.json`) это правило не покрывает. Репозитории в правиле — ровно `[merge_repos]` направления
  из `policy.toml`; направлению без такой записи правила слияния нет. Окну с доступом к личному (`[private]`
  `coordinators`, сейчас mnemo-brain) правило слияния не выдаётся и при `[merge_repos]`: его PR сливает владелец
  (metis-0156). Имён владельца, направлений и репозиториев в
  коде правил нет: у каждой установки правило собирается из её `policy.toml`. Review Record снимает с
  `pantheon review test|accept|reject|talos|status` метки Self-Approval и CI Bypass — только с самой обёртки: команду
  после `--` (тест-раннер проекта) классификатор судит как отдельную, merge, push, `gh`, сеть, правка файлов и
  `sh -c`/`python3 -c` там остаются Self-Approval или CI Bypass (metis-0156). Пританею, мастерской и окнам задач
  `autoMode` не дают. Классификатор читает `autoMode` из `--settings` окна, а из `.claude/settings.json` проекта — нет.
  Запись в `.claude/agents` (metis-0140): песочница окна закрывает на запись `.claude/agents` в каждой разрешённой
  папке и `**/.claude/agents` во вложенных (в том числе в worktree внутри репозитория); `guard` закрывает то же хуком.
  Последствие для git: в репозиториях, где `.claude/agents` лежит в git,
  `git pull`, `merge`, `checkout` и `worktree add`, которые меняют эти файлы, в окне упадут; подтягивает их владелец
  у себя. Это намеренно: роли агентов репозитория окно менять не должно.
  Зарезервированные имена (metis-0163): `hq`, `workshop` и всё вида `job-*` — имена окон системы
  (`settings/hq.json`, `workshop.json`, `job-<роль>.json`); направлением в `directions.toml` их назвать нельзя —
  `pantheon domains build` и `pantheon direction check` отказывают понятной строкой.
  Раздел `[private]` в `policy.toml` (кто и какие пути считает личными) читается по правилу guard 0.5.9: умолчание
  (roles `hq`, `chiron`; coordinators `mnemo-brain`; четыре личных пути) действует и без `policy.toml` вовсе, пустые
  `roles` и `coordinators` означают «никого», пустой `paths` — умолчание. Тест `test_private_conf` сверяет умолчание
  с `DEFAULT_PRIVATE` у guard.
  Задачи расписания `claude -p --agent <роль>` идут в песочнице окна задачи `settings/job-<роль>.json` (metis-0063):
  роли — только из `JOB_ROLES` (clio, prometheus, iris; iris — с `--model sonnet`), плановый проход сам добавляет `--settings`.
  Окно пишет только своё (clio и prometheus — `~/ai/knowledge`, iris — `~/ai/pantheon/scout`), память ролей и свой
  кэш; личное закрыто на чтение и запись; сети у Bash нет; мимо песочницы — только `pantheon alert`. Нет файла окна
  — задача не идёт, приходит одна тревога; `domains build --if-changed` пересобирает пропавшее окно. Субагентов
  роль задачи зовёт только из `agents` своей строки `JOB_ROLES` (сейчас — никого): хук `agents.py` с заглушкой
  «никого» и `deny Agent(…)` встроенным типам, ролям из `~/.claude/agents` и лидам; обычный навык идёт.
  Песочница всех окон (направления, мастерская, Пританей) пускает запись в `~/.claude/agent-memory/<роль>` каждой
  роли-субагента, у которой в шапке `~/.claude/agents/<роль>.md` есть ключ `memory:` (роли главных сессий не берутся;
  папку сборка создаёт, ссылку вместо папки пропускает). Новый файл роли плановый проход подхватывает сам. Риск: песочница пускает
  Bash-запись в память всех таких ролей, а guard (правило domain) — каждую роль только в её собственную папку, для
  Write/Edit и для тех записей Bash, которые он распознаёт. Запись в память чужой роли (например, argus) остаётся
  возможной только командой Bash, которую guard не разобрал (скрипт, интерпретатор). Исключение — главная сессия
  Пританея: правило domain её не ограничивает (`check_domain` в guard.py), поэтому Зевс пишет в память любой такой роли
  и через Write/Edit (как и раньше), и обычной командой Bash (с 0.11.14). Субагенты в окне Пританея ограничены своей
  папкой, как везде. Граница та же, что у остальных папок окна: guard — защита от ошибок, а не от намеренного обхода.
- `plugins/pantheon/lib/watch.py` — дежурный и управление сессиями (шаг 1.4): `pantheon watch [--dry-run]`, `agents`,
  `who`, `revisits`, `wake <имя>`, `stop|resume <имя>|--all`, `pause <имя>|--all --reason limit|swap|manual`,
  `restart --prepare|--status|--go|--cancel`, `saved`, `infra-check`. Подключает его `pantheon.py` (`watch_cmd`).
- Службы (с 0.11.0, SCHED-05): `[[service]]` в `schedule.toml` — постоянный процесс, своя задача launchd
  `pantheon.svc.<имя>` с KeepAlive, запуск через `pantheon service-run <имя>` (команда — только `pantheon …`
  или скрипт плагина). Плановый проход сверяет launchd с расписанием; `pantheon jobs pause|resume|disable|enable <служба>` действует
  сразу, `pantheon jobs` показывает pid. `pantheon jobs pause --all` и нечитаемый `schedule.toml` службы не трогают:
  они идут как шли (плановый проход выходит раньше сверки), пауза службы — только по её имени.
  Служба по требованию (с 0.11.47, metis-0151): ключ `socket = <порт>` (и `idle_min`, по умолчанию 30) вместо
  KeepAlive даёт сокет launchd на 127.0.0.1:<порт>. Первое соединение запускает службу, после простоя она выходит
  сама (прокси `lib/ondemand.py`); «загружена, процесса нет» для неё — ожидание запроса, а не сбой.
- Обновления плагинов (с 0.11.8, metis-0052): `pantheon plugins update [--quiet]` — плановый проход раз в 10 минут, вне песочницы.
  Обновляет каталог agent-kit (не вышло — код 75), для установленных плагинов уровня пользователя с новой версией в
  каталоге гоняет `tests/test_*.py` новой и установленной версии во временной папке на `python3` и `/usr/bin/python3`.
  Новых падений нет — `claude plugin update <плагин>@agent-kit` без `-y` и тревога «обновлён X → Y»; есть — не ставит,
  тревога с логом, эту версию больше не гоняет. Метки, журнал и логи тестов — `~/.local/state/pantheon/plugins/`.
  Встало не то, что проверялось (другая версия или хеш дерева), — критическая тревога. Проверить ту же версию заново —
  удалить запись плагина из `~/.local/state/pantheon/plugins/marks.json`.
- `plugins/pantheon/lib/qmd.py` — общий поиск qmd (шаг 1.5): `pantheon qmd config|update|embed|serve|install|status`.
  Коллекции — `~/ai/pantheon/qmd.toml` (только Пританей); `~/.config/qmd/index.yml` пересобирается из него перед каждым
  запуском qmd и без ключа `update` (его qmd исполняет через bash). Сервер MCP — служба `qmd` на 127.0.0.1:8181
  (с `socket = 8181` в её `[[service]]` — по требованию: qmd поднимается первым запросом, гаснет после простоя);
  подключение на новом Mac — `npm install -g @tobilu/qmd`, затем `pantheon qmd install` (MCP уровня пользователя).
  Хук `ctx.py qmd-query` пропускает только поиск `vec`/`lex` в названных коллекциях с `rerank: false` (QMD-04).
- `plugins/pantheon/lib/window_rules.py` — правила окон координаторов для слияния через шлюз guard
  (`permissions.allow` и `autoMode.allow`, metis-0174); их собирает `pantheon domains build`. Файл — в ядре защит:
  PR, который его задевает, ждёт слияния владельцем.
- `plugins/pantheon/lib/view-sync.sh` — копия `~/ai/pantheon` только для чтения для Obsidian. Если в копии нет
  `.obsidian`, кладёт образец настроек из `plugins/pantheon/share/pantheon-view-obsidian/` (сниппеты, закладки, базовые
  плагины; существующую папку не трогает). Тему и плагин Style Settings владелец ставит в Obsidian сам.
- `plugins/pantheon/hooks/ctx.py` — хуки контекста и журнала ваших слов (шаг 1.1): `owner-log` (UserPromptSubmit,
  в фоне — строка только для ввода, который Claude Code сам пометил в транскрипте как ваш), `stop` (подсказка
  «пора очистить» на 150 тыс. и далее каждые +100 тыс.), `start` (после сжатия — файл состояния, Пританею — новые
  тревоги и сводка журналов), `rewake` (после `/clear` будит Claude, если файл состояния обновлён после вашего
  последнего сообщения). Состояние — `~/.local/state/pantheon/ctx/` и `…/owner-log/` (ввод без пометки транскрипта —
  в `…/owner-log/unconfirmed/`, это не ваши слова); выключатель хуков контекста — `PANTHEON_CTX_OFF=1`. Хуки запускают
  `python3` из PATH (3.9+): на чистом Mac нужны Command Line Tools (`xcode-select --install`), иначе это заглушка.
- `ctx.py` с 0.10.0 (шаг 1.4): `maint-post` и `maint-pre` — при метке техперезапуска сессия из списка один раз получает
  «сохранись», после `pantheon saved` ей закрыты инструменты (кроме отчёта Зевсу); `push` (SessionStart, asyncRewake) —
  отдаёт сессии текст из `~/.local/state/pantheon/push/<сессия>.txt` после `claude respawn`. Уборку журналов ваших слов
  делает дежурный, хук только дописывает.
- `plugins/pantheon/hooks/agents.py` (0.11.19, P0-6) — PreToolUse `Agent|Task|Skill` в окнах Пританея и координаторов:
  главная сессия зовёт только субагентов из списка окна, навык с `context: fork` проверяется по своему `agent:`.
  Субагенты окна (лиды с их dev-*, argus) не проверяются. Списки — в `pantheon.py`: `HQ_AGENTS`, `COORDINATOR_AGENTS`
  (argus, talos, prometheus, Explore и разработчики dev-haiku, dev-sonnet, dev-opus: координатор отдаёт им мелкие
  правки сам; codex-dev не входит — его зовёт только лид), `COORDINATOR_EXTRA_AGENTS`, у координатора ещё свои лиды из
  реестра. В окна добавлены и правила `deny Agent(…)`:
  Пританею — все лиды и главные роли, направлению — chiron, главные роли и лиды других направлений. Любой сбой хука —
  код 2, то есть отказ. После выпуска нужны `pantheon domains build` и перезапуск окон. С 0.11.23 Пританею открыт
  momus — ревизор навыка audit (`agent: momus`): только чтение и веб, пишет лишь свой отчёт в `~/ai/knowledge/Inbox`.
- `plugins/pantheon/bin/heavy` — тяжёлые команды через общую блокировку: два места, `--server` — один долгий процесс (MEM-03).
- `plugins/pantheon/hooks/dev-stop-verify.py` — Stop разработчика (в шапке ролей dev-*): красная проверка проекта
  возвращает, не больше трёх раз; очередь `heavy` — не возврат (DONE-02).
- `plugins/pantheon/scripts/git-crypt-merge.sh` — слияние файлов под git-crypt как текста (для `~/ai/pantheon` и `me/`).
- `plugins/pantheon/scripts/decision-map-check.py` — сверка карты решений с `revisits.toml`.
- `plugins/pantheon/scripts/baseline.py` — замер «как сейчас» по git и транскриптам (ORD-06); правила подсчёта — в шапке.
- `plugins/pantheon/scripts/config-check.py` — проверка правок `~/.claude` для `sync.sh`: код и подозрительное — в
  карантин с объяснением на доске, остальное уходит само (SEC-15).
- `plugins/guard/managed-settings.json` — управляемые настройки (SEC-28), ставятся через `sudo` (README guard).
- `plugins/project-tools/stacks.json` — карта стеков (признак → что подключить); `plugins/project-tools/lib/project_tools.py`
  — команда `project-tools`. Пишет только записи из карты; в окнах ролей запись в `.mcp.json` и `.claude/settings*.json`
  запрещена песочницей и guard — там только `check`.

## Проверки

    python3 -I plugins/guard/tests/test_guard.py      # карта прав ~/ai/pantheon, domain, привилегии, protect-config, режимы
    python3 -I plugins/guard/tests/test_shell_diff.py # разбор Bash против настоящих zsh и bash
    python3 -I plugins/pantheon/tests/test_board.py   # задачи и доска владельца
    python3 -I plugins/pantheon/tests/test_config_check.py   # правила карантина правок ~/.claude (SEC-15)
    bash plugins/pantheon/tests/test_sync_quarantine.sh ~/.claude/sync.sh "$(readlink ~/.local/bin/pantheon)" "$PWD/plugins/pantheon"
    python3 -I plugins/pantheon/tests/test_start.py   # start, wake, roles build, approve, heavy, Stop-хук разработчика
    python3 -I plugins/pantheon/tests/test_watch.py   # дежурный: самозапуск, сбои, паузы, стоп, техперезапуск, журналы, пересмотры
    python3 -I plugins/pantheon/tests/test_tick.py    # планировщик: сон, пробуждение, питание, простой, лимит, главный Mac
    python3 -I plugins/pantheon/tests/test_plugins_update.py   # обновления agent-kit плановым проходом: тесты, база, метки, коды
    python3 -I plugins/pantheon/tests/test_baseline.py   # замер «как сейчас»: задачи по git commit, сообщения, возвраты, цена
    python3 -I plugins/pantheon/tests/test_hooks.py   # хуки контекста и owner-log (и на системном: CTX_TEST_PYTHON=/usr/bin/python3)
    python3 -I plugins/project-tools/tests/test_project_tools.py   # карта стеков, apply, одобрения, Codex, подсказка
    claude plugin validate .  &&  claude plugin validate plugins/guard  &&  claude plugin validate plugins/pantheon  &&  claude plugin validate plugins/project-tools

Изменение защит проверяется вживую в изоляции: временные папки, `--plugin-dir` и `--settings` на одну
сессию, Haiku, хеш `~/.claude/settings.json` до и после.
